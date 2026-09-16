"""Costo de envío ESTIMADO antes de publicar (16 de septiembre de 2026, pedido
del dueño: "que al analizar el margen también analice el envío").

Interpretación pura (domain/ml_shipping.py), caché por (categoría, precio)
(services/ml_comisiones.py) y su efecto en el margen (routes/rentabilidad.py).
Ninguna prueba llama a la API real de Mercado Libre.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.db.models import MercadoLibreShippingEstimate, Product, ProductVariant
from app.domain.ml_shipping import (
    MOTIVO_CATEGORIA_SIN_MERCADO_ENVIOS,
    MOTIVO_ENVIO_NO_OBLIGATORIO,
    categoria_usa_mercado_envios,
    interpretar_estimacion_envio,
    medidas_por_defecto,
)
from app.services import ml_comisiones
from tests.test_publicaciones_endpoint import NOW, a_store, client, db_session  # noqa: F401 — fixtures

# Forma real de GET /categories/{id}/shipping_preferences (verificada en vivo
# contra MLC el 16/09/2026).
PREFERENCIAS_ME2 = {
    "dimensions": {"height": 5, "width": 15, "length": 15, "weight": 300},
    "logistics": [{"types": ["custom"], "mode": "custom"}, {"types": ["drop_off"], "mode": "me2"}],
}
PREFERENCIAS_SIN_ME2 = {
    "dimensions": {"height": 20, "width": 25, "length": 32, "weight": 3500},
    "logistics": [{"types": ["custom"], "mode": "custom"}, {"types": ["default"], "mode": "me1"}],
}
# Forma real de GET /users/{id}/shipping_options/free?dimensions=...&item_price=...
COSTO_OBLIGATORIO = {"coverage": {"all_country": {"list_cost": 3050, "currency_id": "CLP", "discount": {"rate": 0.5, "type": "mandatory"}}}}
COSTO_NO_OBLIGATORIO = {"coverage": {"all_country": {"list_cost": 999.6, "currency_id": "CLP", "discount": {"rate": 0.3, "type": "none"}}}}


def test_medidas_por_defecto_de_la_categoria():
    assert medidas_por_defecto(PREFERENCIAS_ME2) == "5x15x15,300"


@pytest.mark.parametrize("preferencias", [None, {}, {"dimensions": {}}, {"dimensions": {"height": 0, "width": 1, "length": 1, "weight": 1}}])
def test_sin_medidas_validas_no_se_inventan(preferencias):
    assert medidas_por_defecto(preferencias) is None


def test_categoria_con_y_sin_mercado_envios():
    assert categoria_usa_mercado_envios(PREFERENCIAS_ME2) is True
    assert categoria_usa_mercado_envios(PREFERENCIAS_SIN_ME2) is False


def test_interpreta_el_costo_estimado_y_si_el_envio_gratis_es_obligatorio():
    obligatorio = interpretar_estimacion_envio(COSTO_OBLIGATORIO)
    assert (obligatorio.costo, obligatorio.obligatorio, obligatorio.motivo_no_disponible) == (3050.0, True, None)
    opcional = interpretar_estimacion_envio(COSTO_NO_OBLIGATORIO)
    assert (opcional.costo, opcional.obligatorio) == (999.6, False)


@pytest.mark.parametrize("respuesta", [None, {}, {"coverage": {}}, {"coverage": {"all_country": {"list_cost": "3050"}}},
                                       {"coverage": {"all_country": {"list_cost": -1}}}])
def test_respuesta_sin_costo_valido_nunca_inventa_una_estimacion(respuesta):
    assert interpretar_estimacion_envio(respuesta).costo is None


class AdapterFalso:
    def __init__(self, preferencias=PREFERENCIAS_ME2, costo=COSTO_OBLIGATORIO):
        self.preferencias = preferencias
        self.costo = costo
        self.consultas_categoria: list[str] = []
        self.consultas_costo: list[tuple[str, float]] = []

    async def get_category_shipping_preferences(self, access_token, category_id):  # noqa: ARG002
        self.consultas_categoria.append(category_id)
        return self.preferencias

    async def get_free_shipping_cost(self, access_token, user_id, *, dimensions, item_price, listing_type_id="gold_special"):  # noqa: ARG002
        self.consultas_costo.append((dimensions, item_price))
        return self.costo


def _estimar(db, store_id, adapter, pares, user_id="SELLER-1"):
    return asyncio.run(ml_comisiones._actualizar_estimaciones_envio(db, store_id, adapter, "token", user_id, pares))


def test_guarda_una_estimacion_por_categoria_y_precio_y_no_la_vuelve_a_pedir(db_session, a_store):
    adapter = AdapterFalso()
    pares = {("MLC424972", 19990.0), ("MLC424972", 9990.0)}
    assert _estimar(db_session, a_store.id, adapter, pares) == 2
    assert len(adapter.consultas_categoria) == 1  # las medidas se piden una vez por categoría
    assert sorted(adapter.consultas_costo) == [("5x15x15,300", 9990.0), ("5x15x15,300", 19990.0)]

    # Segunda corrida: ya está cacheado, no se vuelve a consultar nada.
    adapter2 = AdapterFalso()
    assert _estimar(db_session, a_store.id, adapter2, pares) == 0
    assert adapter2.consultas_costo == []

    fila = db_session.query(MercadoLibreShippingEstimate).filter_by(store_id=a_store.id, price=19990).one()
    assert (float(fila.shipping_cost), fila.mandatory, fila.dimensions) == (3050.0, True, "5x15x15,300")


def test_categoria_sin_mercado_envios_queda_registrada_sin_costo(db_session, a_store):
    adapter = AdapterFalso(preferencias=PREFERENCIAS_SIN_ME2)
    assert _estimar(db_session, a_store.id, adapter, {("MLC180937", 19990.0)}) == 1
    assert adapter.consultas_costo == []  # no tiene sentido pedir el costo
    fila = db_session.query(MercadoLibreShippingEstimate).filter_by(store_id=a_store.id, category_id="MLC180937").one()
    assert fila.shipping_cost is None and fila.unavailable_reason == MOTIVO_CATEGORIA_SIN_MERCADO_ENVIOS


def test_sin_cuenta_de_vendedor_no_se_estima_nada(db_session, a_store):
    adapter = AdapterFalso()
    assert _estimar(db_session, a_store.id, adapter, {("MLC424972", 19990.0)}, user_id=None) == 0
    assert db_session.query(MercadoLibreShippingEstimate).count() == 0


def _producto_con_categoria(db, store, *, sku: str, precio: float, costo: float, categoria: str = "MLC424972") -> int:
    producto = Product(
        store=store, internal_sku=sku, name=f"Producto {sku}", product_type="simple",
        ml_category_id=categoria, ml_category_name="Categoría de prueba", created_at=NOW, updated_at=NOW,
    )
    db.add(producto)
    db.flush()
    variante = ProductVariant(
        product=producto, store_id=store.id, variant_sku=sku, price=precio, cost_price=costo,
        created_at=NOW, updated_at=NOW,
    )
    db.add(variante)
    db.commit()
    return variante.id


def _guardar_estimacion(db, store_id, *, precio: float, costo: float | None, obligatorio: bool | None, categoria: str = "MLC424972"):
    db.add(MercadoLibreShippingEstimate(
        store_id=store_id, category_id=categoria, price=precio, shipping_cost=costo,
        mandatory=obligatorio, dimensions="5x15x15,300", unavailable_reason=None, fetched_at=datetime.now(),
    ))
    db.commit()


def _fila_de(client, sku: str) -> dict:
    productos = client.get("/api/rentabilidad").json()["productos"]
    return next(f for f in productos if f["sku"] == sku)


def test_el_margen_descuenta_el_envio_estimado_cuando_el_envio_gratis_es_obligatorio(client, db_session, a_store):
    client.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 10, "target_margin_pct": 30, "min_margin_pct": 15})
    _producto_con_categoria(db_session, a_store, sku="EST-1", precio=20000, costo=5000)
    _guardar_estimacion(db_session, a_store.id, precio=20000, costo=3050, obligatorio=True)

    fila = _fila_de(client, "EST-1")
    assert fila["envioMlFuente"] == "estimado_ml"
    assert fila["costoEnvioMl"] == 3050.0
    assert fila["envioMlResuelto"] is True
    # 20.000 − 10 % de comisión − 3.050 de envío − 5.000 de costo
    assert fila["margenMercadoLibreClp"] == pytest.approx(9950.0)


def test_si_el_envio_gratis_no_es_obligatorio_no_se_descuenta_y_el_margen_no_es_provisional(client, db_session, a_store):
    client.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 10, "target_margin_pct": 30, "min_margin_pct": 15})
    _producto_con_categoria(db_session, a_store, sku="EST-2", precio=9990, costo=2000)
    _guardar_estimacion(db_session, a_store.id, precio=9990, costo=999.6, obligatorio=False)

    fila = _fila_de(client, "EST-2")
    assert fila["costoEnvioMl"] is None
    assert fila["envioMlMotivo"] == MOTIVO_ENVIO_NO_OBLIGATORIO
    assert fila["envioMlResuelto"] is True
    assert fila["margenMercadoLibreClp"] == pytest.approx(9990 - 999.0 - 2000, abs=1)


def test_sin_estimacion_no_hay_margen_de_mercado_libre(client, db_session, a_store):
    client.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 10, "target_margin_pct": 30, "min_margin_pct": 15})
    _producto_con_categoria(db_session, a_store, sku="EST-3", precio=20000, costo=5000)

    fila = _fila_de(client, "EST-3")
    assert fila["envioMlFuente"] == "no_disponible"
    assert fila["envioMlResuelto"] is False
    assert fila["margenMercadoLibreClp"] is None
