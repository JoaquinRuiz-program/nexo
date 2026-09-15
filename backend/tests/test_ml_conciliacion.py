"""
Conciliación de comisiones con la facturación real de Mercado Libre (14 de
septiembre de 2026). Mercado Libre mockeado con respx; formato de la
facturación tomado de la doc oficial "Billing Reports by Orders and Packs".
"""

from __future__ import annotations

import httpx
import respx

from app.db.models import MercadoLibreCategoryFee, OrderBilling, Product, SyncJob
from app.domain.ml_billing import COINCIDE, DIFERENCIA, SIN_ESTIMACION, SIN_FACTURAR, estado_conciliacion, resumir_cargos, tipo_de_publicacion
from tests.test_mercadolibre_endpoints import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    NOW,
    _pedido_ml,
    _producto,
    a_store,
    client,
    cuenta_conectada,
    db_session,
)

ML = r"https://api\.mercadolibre\.com"
PEDIDO = "2000001234"


def _detalle(sub_tipo, monto, item_type="gold_special"):
    return {
        "charge_info": {"detail_amount": monto, "detail_type": "CHARGE", "detail_sub_type": sub_tipo},
        "sales_info": [{"order_id": int(PEDIDO), "payer_nickname": "COMPRADOR", "state_name": "RM"}],
        "items_info": [{"item_id": "MLC1", "item_type": item_type, "item_price": 10000, "item_amount": 1, "order_id": int(PEDIDO)}],
    }


def _facturacion(*detalles):
    return {"offset": 0, "limit": 150, "total": 1 if detalles else 0, "results": [{"order_id": int(PEDIDO), "details": list(detalles)}] if detalles else []}


def _preparar(db_session, a_store, monkeypatch, *, con_comision_cacheada=True):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    variante = _producto(db_session, a_store, sku="CONC-1", nombre="Cuaderno", precio=10000)
    producto = db_session.get(Product, variante.product_id)
    producto.ml_category_id = "MLC180937"
    if con_comision_cacheada:
        db_session.add(MercadoLibreCategoryFee(
            store_id=a_store.id, category_id="MLC180937", listing_type_id="gold_special", price=10000,
            percentage_fee=12, fixed_fee=0, sale_fee_amount=1200, fetched_at=NOW,
        ))
    db_session.commit()
    respx.get(url__regex=ML + r"/orders/search.*").mock(return_value=httpx.Response(200, json={"results": [_pedido_ml(PEDIDO, "CONC-1")]}))


# ------------------------------------------------------------------
# Dominio puro
# ------------------------------------------------------------------


def test_resumir_cargos_separa_venta_envio_y_otros():
    cargos = resumir_cargos([_detalle("CV", 1200), _detalle("CXD", 3000), _detalle("PADS", 500), {"charge_info": {"detail_type": "BONUS", "detail_amount": 99}}])
    assert cargos == {"hay_cargos": True, "cargo_venta": 1200.0, "cargo_envio": 3000.0, "otros_cargos": 500.0}


def test_sin_detalles_no_hay_cargos():
    assert resumir_cargos([])["hay_cargos"] is False


def test_tipo_de_publicacion_solo_si_es_uno():
    assert tipo_de_publicacion([_detalle("CV", 1)]) == "gold_special"
    assert tipo_de_publicacion([_detalle("CV", 1), _detalle("CV", 1, item_type="gold_pro")]) is None


def test_estados_de_conciliacion():
    assert estado_conciliacion(False, 0, None) == SIN_FACTURAR
    assert estado_conciliacion(True, 1200, None) == SIN_ESTIMACION
    assert estado_conciliacion(True, 1200.4, 1200) == COINCIDE
    assert estado_conciliacion(True, 1500, 1200) == DIFERENCIA


# ------------------------------------------------------------------
# Integración: importar ventas -> conciliación -> GET /conciliacion
# ------------------------------------------------------------------


@respx.mock
def test_comision_facturada_igual_a_la_de_nexo_coincide(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _preparar(db_session, a_store, monkeypatch)
    respx.get(url__regex=ML + r"/billing/integration/group/ML/order/details.*").mock(
        return_value=httpx.Response(200, json=_facturacion(_detalle("CV", 1200), _detalle("CXD", 3000)))
    )

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 200, res.text
    assert res.json()["conciliacion"] == {"pedidosRevisados": 1, "conFacturacion": 1, "conDiferencia": 0}
    body = client.get("/api/mercadolibre/conciliacion").json()
    assert body["resumen"]["ventasComparadas"] == 1
    assert body["resumen"]["comisionFacturada"] == 1200.0
    assert body["resumen"]["comisionEstimada"] == 1200.0
    pedido = body["pedidos"][0]
    assert pedido["pedidoId"] == PEDIDO
    assert pedido["envioFacturado"] == 3000.0
    assert pedido["estado"] == "coincide"
    assert "COMPRADOR" not in str(body)  # nunca datos del comprador


@respx.mock
def test_comision_facturada_distinta_marca_diferencia(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _preparar(db_session, a_store, monkeypatch)
    respx.get(url__regex=ML + r"/billing/integration/group/ML/order/details.*").mock(
        return_value=httpx.Response(200, json=_facturacion(_detalle("CV", 1500)))
    )

    client.post("/api/mercadolibre/importar-ventas")

    body = client.get("/api/mercadolibre/conciliacion").json()
    assert body["pedidos"][0]["estado"] == "diferencia"
    assert body["pedidos"][0]["diferencia"] == 300.0
    assert body["resumen"]["ventasConDiferencia"] == 1
    job = db_session.query(SyncJob).filter_by(direction="ml_conciliacion").one()
    assert job.status == "success"


@respx.mock
def test_sin_comision_cacheada_no_inventa_estimacion(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _preparar(db_session, a_store, monkeypatch, con_comision_cacheada=False)
    respx.get(url__regex=ML + r"/billing/integration/group/ML/order/details.*").mock(
        return_value=httpx.Response(200, json=_facturacion(_detalle("CV", 1200)))
    )

    client.post("/api/mercadolibre/importar-ventas")

    pedido = client.get("/api/mercadolibre/conciliacion").json()["pedidos"][0]
    assert pedido["estado"] == "sin_estimacion"
    assert pedido["comisionEstimada"] is None


@respx.mock
def test_pedido_aun_sin_facturar_no_se_vuelve_a_pedir_el_mismo_dia(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _preparar(db_session, a_store, monkeypatch)
    ruta = respx.get(url__regex=ML + r"/billing/integration/group/ML/order/details.*").mock(
        return_value=httpx.Response(200, json=_facturacion())
    )

    client.post("/api/mercadolibre/importar-ventas")
    client.post("/api/mercadolibre/importar-ventas")

    assert ruta.calls.call_count == 1
    assert client.get("/api/mercadolibre/conciliacion").json()["pedidos"][0]["estado"] == "sin_facturar"


@respx.mock
def test_pedido_ya_facturado_nunca_se_vuelve_a_pedir(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _preparar(db_session, a_store, monkeypatch)
    ruta = respx.get(url__regex=ML + r"/billing/integration/group/ML/order/details.*").mock(
        return_value=httpx.Response(200, json=_facturacion(_detalle("CV", 1200)))
    )

    client.post("/api/mercadolibre/importar-ventas")
    client.post("/api/mercadolibre/importar-ventas")

    assert ruta.calls.call_count == 1
    assert db_session.query(OrderBilling).count() == 1


@respx.mock
def test_si_ml_rechaza_la_facturacion_importar_ventas_no_falla(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _preparar(db_session, a_store, monkeypatch)
    respx.get(url__regex=ML + r"/billing/integration/group/ML/order/details.*").mock(return_value=httpx.Response(403, json={"message": "forbidden"}))

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 200
    assert res.json()["conciliacion"] is None
    assert db_session.query(SyncJob).filter_by(direction="ml_conciliacion").one().status == "error"


def test_sin_ventas_la_conciliacion_esta_vacia(client, a_store):
    body = client.get("/api/mercadolibre/conciliacion").json()
    assert body["pedidos"] == []
    assert body["resumen"]["ventasComparadas"] == 0
