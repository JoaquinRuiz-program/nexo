"""
Devoluciones reales de Mercado Libre (14 de septiembre de 2026): se
sincronizan al importar ventas y se listan por empresa. Mercado Libre
mockeado con respx (formas de respuesta tomadas de la doc oficial).
"""

from __future__ import annotations

import httpx
import respx

from app.db.models import OrderReturn, SyncJob
from tests.test_mercadolibre_endpoints import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    a_store,
    client,
    cuenta_conectada,
    db_session,
)

ML = r"https://api\.mercadolibre\.com"


def _mock_base():
    respx.get(url__regex=ML + r"/orders/search.*").mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__regex=ML + r"/post-purchase/v1/claims/search.*type=return.*").mock(
        return_value=httpx.Response(200, json={
            "paging": {"total": 1, "offset": 0, "limit": 50},
            "data": [{"id": 111, "type": "return", "stage": "claim", "status": "closed", "resource": "order", "resource_id": 2000001, "date_created": "2026-09-10T10:00:00.000-04:00"}],
        })
    )
    respx.get(url__regex=ML + r"/post-purchase/v1/claims/search.*type=mediations.*").mock(
        return_value=httpx.Response(200, json={
            "paging": {"total": 1, "offset": 0, "limit": 50},
            "data": [{"id": 222, "type": "mediations", "stage": "dispute", "status": "opened", "resource": "order", "resource_id": 2000002}],
        })
    )
    respx.get(url__regex=ML + r"/post-purchase/v2/claims/111/returns").mock(
        return_value=httpx.Response(200, json={
            "claim_id": 111, "resource": "order", "resource_id": 2000001, "status": "closed",
            "status_money": "refunded", "refund_at": "delivered", "date_closed": "2026-09-12T12:03:22.464-04:00",
        })
    )
    respx.get(url__regex=ML + r"/post-purchase/v2/claims/222/returns").mock(return_value=httpx.Response(404, json={"message": "not found"}))


@respx.mock
def test_importar_ventas_sincroniza_devoluciones_y_se_listan(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_base()

    res = client.post("/api/mercadolibre/importar-ventas")
    assert res.status_code == 200
    assert res.json()["devoluciones"] == {"nuevas": 1, "actualizadas": 0, "conError": 0}

    # Correrlo de nuevo actualiza, nunca duplica.
    res = client.post("/api/mercadolibre/importar-ventas")
    assert res.json()["devoluciones"] == {"nuevas": 0, "actualizadas": 1, "conError": 0}
    assert db_session.query(OrderReturn).count() == 1

    lista = client.get("/api/mercadolibre/devoluciones").json()["devoluciones"]
    assert len(lista) == 1
    devolucion = lista[0]
    # La mediación sin devolución (404) no se guarda.
    assert devolucion["reclamoId"] == "111"
    assert devolucion["pedidoId"] == "2000001"
    assert devolucion["estadoDevolucion"] == "closed"
    assert devolucion["estadoDinero"] == "refunded"
    assert devolucion["ventaImportada"] is False
    assert devolucion["fechaCierre"] == "2026-09-12T16:03:22.464000"
    assert db_session.query(SyncJob).filter_by(direction="ml_devoluciones").count() == 2


@respx.mock
def test_importar_ventas_no_falla_si_ml_rechaza_los_reclamos(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=ML + r"/orders/search.*").mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__regex=ML + r"/post-purchase/v1/claims/search.*").mock(return_value=httpx.Response(403, json={"message": "forbidden"}))

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 200
    assert res.json()["devoluciones"] is None
    job = db_session.query(SyncJob).filter_by(direction="ml_devoluciones").one()
    assert job.status == "error"


def test_devoluciones_de_otra_empresa_no_se_ven(client, db_session, a_store):
    from datetime import datetime

    from app.db.models import Store, User
    from app.domain.security import hash_password

    otro = User(email="otra@ejemplo.cl", password_hash=hash_password("x"), full_name="Otra", created_at=datetime(2026, 9, 1), updated_at=datetime(2026, 9, 1))
    otra_tienda = Store(owner=otro, name="Otra", created_at=datetime(2026, 9, 1))
    db_session.add_all([otro, otra_tienda])
    db_session.flush()
    db_session.add(OrderReturn(store_id=otra_tienda.id, external_claim_id="999", claim_type="return", fetched_at=datetime(2026, 9, 1)))
    db_session.commit()

    assert client.get("/api/mercadolibre/devoluciones").json() == {"devoluciones": []}
