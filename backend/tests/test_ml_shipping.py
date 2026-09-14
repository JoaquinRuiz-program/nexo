"""
Costo de envío REAL de Mercado Libre (14 de septiembre de 2026):
interpretación pura (domain/ml_shipping.py), adaptador contra respx y
sincronización (services/ml_shipping_sync.py) con un adaptador falso. Ninguna
prueba llama a la API real de Mercado Libre.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreConfig, MercadoLibreRequestError
from app.db.base import Base
from app.db.models import MarketplaceAccount, MarketplaceListing, Product, Store, User
from app.domain.ml_shipping import (
    MOTIVO_ITEM_INEXISTENTE,
    MOTIVO_SIN_COSTO_VALIDO,
    MOTIVO_SIN_MERCADO_ENVIOS,
    interpretar_costo_envio,
    motivo_sin_consulta_de_costo,
)
from app.domain.security import hash_password
from app.services.ml_shipping_sync import sincronizar_costos_envio

NOW = datetime(2026, 9, 14, 12, 0, 0)

ITEM_ME2 = {
    "id": "MLC1", "status": "active", "currency_id": "CLP",
    "shipping": {"mode": "me2", "logistic_type": "drop_off", "free_shipping": True, "tags": []},
}
# Forma documentada de GET /users/{id}/shipping_options/free
RESPUESTA_COSTO = {"coverage": {"all_country": {"list_cost": 3290, "currency_id": "CLP", "billable_weight": 800}}}


def test_interpreta_el_list_cost_real_del_vendedor():
    r = interpretar_costo_envio(ITEM_ME2, RESPUESTA_COSTO)
    assert (r.costo, r.moneda, r.modo, r.logistica, r.envio_gratis, r.motivo_no_disponible) == (3290.0, "CLP", "me2", "drop_off", True, None)


@pytest.mark.parametrize("respuesta", [
    None,
    {},
    {"coverage": {}},
    {"coverage": {"all_country": {"currency_id": "CLP"}}},
    {"coverage": {"all_country": {"list_cost": -1, "currency_id": "CLP"}}},
    {"coverage": {"all_country": {"list_cost": "3290", "currency_id": "CLP"}}},
    {"coverage": {"all_country": {"list_cost": True, "currency_id": "CLP"}}},
    {"coverage": {"all_country": {"list_cost": 3290, "currency_id": "ARS"}}},
    {"coverage": {"all_country": {"list_cost": 3290}}},
])
def test_respuesta_sin_costo_valido_nunca_inventa_un_valor(respuesta):
    r = interpretar_costo_envio(ITEM_ME2, respuesta)
    assert r.costo is None
    assert r.motivo_no_disponible == MOTIVO_SIN_COSTO_VALIDO
    assert r.modo == "me2"  # los datos de shipping del ítem se conservan igual


def test_solo_se_consulta_el_costo_de_publicaciones_con_mercado_envios():
    assert motivo_sin_consulta_de_costo(ITEM_ME2) is None
    # La API real informa el costo también de un ítem no activo (verificado 14/09/2026).
    assert motivo_sin_consulta_de_costo({**ITEM_ME2, "status": "closed"}) is None
    assert motivo_sin_consulta_de_costo({**ITEM_ME2, "shipping": {"mode": "not_specified"}}) == MOTIVO_SIN_MERCADO_ENVIOS
    assert motivo_sin_consulta_de_costo({"status": "active"}) == MOTIVO_SIN_MERCADO_ENVIOS


@pytest.mark.asyncio
@respx.mock
async def test_adaptador_pide_el_costo_del_vendedor_por_item_id():
    ruta = respx.get(url__regex=r"https://api\.mercadolibre\.com/users/123/shipping_options/free\?.*").mock(
        return_value=httpx.Response(200, json=RESPUESTA_COSTO)
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(client_id="x", client_secret="y", redirect_uri="z", max_retries=0, timeout_s=1.0))
    try:
        data = await adapter.get_seller_shipping_cost("token", "123", "MLC1")
    finally:
        await adapter.aclose()
    assert data == RESPUESTA_COSTO
    assert "item_id=MLC1" in str(ruta.calls.last.request.url)
    assert ruta.calls.last.request.headers["Authorization"] == "Bearer token"


# ------------------------------------------------------------------
# Sincronización
# ------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    session = Session(bind=engine, future=True)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


class _AdapterFalso:
    def __init__(self, items: dict, costos: dict):
        self.items = items
        self.costos = costos
        self.llamadas_costo: list[tuple[str, str]] = []

    async def get_item(self, access_token, item_id):
        r = self.items[item_id]
        if isinstance(r, Exception):
            raise r
        return r

    async def get_seller_shipping_cost(self, access_token, user_id, item_id):
        self.llamadas_costo.append((user_id, item_id))
        r = self.costos[item_id]
        if isinstance(r, Exception):
            raise r
        return r


def _cuenta_con_publicaciones(db, estados_por_item: dict[str, str]):
    usuario = User(email="envio@test.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    tienda = Store(owner=usuario, name="Tienda", created_at=NOW)
    cuenta = MarketplaceAccount(store=tienda, marketplace="mercadolibre", status="connected", external_account_id="123")
    db.add_all([usuario, tienda, cuenta])
    db.flush()
    publicaciones = {}
    for i, (item_id, status) in enumerate(estados_por_item.items()):
        producto = Product(store=tienda, internal_sku=f"SKU{i}", name=f"P{i}", product_type="simple", created_at=NOW, updated_at=NOW)
        listing = MarketplaceListing(account=cuenta, product=producto, external_listing_id=item_id, status=status, created_at=NOW)
        db.add_all([producto, listing])
        publicaciones[item_id] = listing
    db.commit()
    return cuenta, publicaciones


@pytest.mark.asyncio
async def test_sincronizar_guarda_el_costo_real_y_marca_no_disponible_sin_inventar(db):
    cuenta, pubs = _cuenta_con_publicaciones(db, {"MLC1": "active", "MLC2": "paused", "MLC3": "active", "MLC4": "active", "MLC5": "closed"})
    pubs["MLC4"].shipping_cost = 1000  # costo real de una sincronización anterior
    db.commit()
    adapter = _AdapterFalso(
        items={
            "MLC1": ITEM_ME2,
            "MLC2": {**ITEM_ME2, "status": "paused"},
            "MLC3": {**ITEM_ME2, "status": "closed"},
            "MLC4": MercadoLibreRequestError("Mercado Libre no responde", status=503),
        },
        costos={
            "MLC1": RESPUESTA_COSTO,
            "MLC2": RESPUESTA_COSTO,
            "MLC3": MercadoLibreRequestError("Item not found", status=404),
        },
    )

    resumen = await sincronizar_costos_envio(db, cuenta, adapter, "token")

    assert resumen == {"publicacionesRevisadas": 4, "conCostoReal": 2, "sinCostoDisponible": 1, "conErrorTemporal": 1}
    assert float(pubs["MLC1"].shipping_cost) == 3290.0
    assert (pubs["MLC1"].shipping_mode, pubs["MLC1"].shipping_free_shipping, pubs["MLC1"].shipping_currency_id) == ("me2", True, "CLP")
    assert float(pubs["MLC2"].shipping_cost) == 3290.0  # pausada: Mercado Libre igual informa el costo
    assert pubs["MLC3"].shipping_cost is None
    assert pubs["MLC3"].shipping_cost_unavailable_reason == MOTIVO_SIN_COSTO_VALIDO
    assert pubs["MLC3"].status == "closed"  # estado local sincronizado con Mercado Libre
    # Error temporal: no es una respuesta sobre el costo, no se pisa lo guardado.
    assert float(pubs["MLC4"].shipping_cost) == 1000.0
    assert pubs["MLC4"].shipping_synced_at is None
    assert pubs["MLC5"].shipping_synced_at is None  # cerrada: no se consulta


@pytest.mark.asyncio
async def test_item_inexistente_queda_no_disponible_y_un_token_invalido_corta(db):
    cuenta, pubs = _cuenta_con_publicaciones(db, {"MLC9": "active"})
    await sincronizar_costos_envio(db, cuenta, _AdapterFalso(items={"MLC9": MercadoLibreRequestError("not found", status=404)}, costos={}), "token")
    assert pubs["MLC9"].shipping_cost_unavailable_reason == MOTIVO_ITEM_INEXISTENTE

    with pytest.raises(MercadoLibreAuthError):
        await sincronizar_costos_envio(db, cuenta, _AdapterFalso(items={"MLC9": MercadoLibreAuthError("token vencido", 401)}, costos={}), "token")


@pytest.mark.asyncio
async def test_sincronizar_costos_deja_registro_de_la_sincronizacion_y_sus_errores(db):
    """14/09/2026 — antes un error temporal quedaba solo en el log del servidor."""
    from app.db.models import SyncJob

    cuenta, _pubs = _cuenta_con_publicaciones(db, {"MLC1": "active", "MLC4": "active"})
    adapter = _AdapterFalso(
        items={"MLC1": ITEM_ME2, "MLC4": MercadoLibreRequestError("Mercado Libre no responde", status=503)},
        costos={"MLC1": RESPUESTA_COSTO},
    )

    await sincronizar_costos_envio(db, cuenta, adapter, "token")

    job = db.query(SyncJob).one()
    assert (job.direction, job.status, job.products_affected, job.store_id) == ("ml_costos_envio", "partial_error", 1, cuenta.store_id)
    assert [log.level for log in job.logs] == ["error"]
    assert "MLC4" in job.logs[0].message
