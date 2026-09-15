"""
Facturas propias adjuntas a ventas de Mercado Libre (15 de septiembre de
2026). Mercado Libre mockeado con respx; formatos de la doc oficial "Cargar y
Obtener Facturas - Emisión Propia" (Chile).
"""

from __future__ import annotations

from datetime import datetime

import httpx
import respx

from app.db.models import Order, OrderInvoice, Store, User
from app.domain.security import hash_password
from tests.test_mercadolibre_endpoints import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    NOW,
    a_store,
    client,
    cuenta_conectada,
    db_session,
)

ML = "https://api.mercadolibre.com"
PEDIDO = "2000009999"
PACK = "2000000089077943"
PDF = b"%PDF-1.4 factura de prueba"
XML = b"<?xml version='1.0'?><DTE/>"


def _venta(db_session, tienda, external=PEDIDO):
    orden = Order(
        store=tienda, channel="mercadolibre", external_order_id=external, order_date=NOW,
        status="completado", total_amount=10000, created_at=NOW, updated_at=NOW,
    )
    db_session.add(orden)
    db_session.commit()
    return orden


def _settings(monkeypatch):
    monkeypatch.setattr("app.api.routes.facturas_ml.get_settings", lambda: CONFIGURED_SETTINGS)


def _subir(client, *, pdf=("factura.pdf", PDF, "application/pdf"), xml=None, pedido=PEDIDO):
    archivos = {"pdf": pdf}
    if xml is not None:
        archivos["xml"] = xml
    return client.post(f"/api/mercadolibre/facturas/{pedido}", files=archivos)


@respx.mock
def test_sube_pdf_y_xml_al_pack_de_la_venta(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    _venta(db_session, a_store)
    respx.get(f"{ML}/orders/{PEDIDO}").mock(return_value=httpx.Response(200, json={"id": int(PEDIDO), "pack_id": int(PACK)}))
    ruta = respx.post(f"{ML}/packs/{PACK}/fiscal_documents").mock(return_value=httpx.Response(200, json={"ids": ["doc-pdf", "doc-xml"]}))

    res = _subir(client, xml=("factura.xml", XML, "application/xml"))

    assert res.status_code == 200, res.text
    assert res.json()["factura"]["archivos"] == ["factura.pdf", "factura.xml"]
    cuerpo = ruta.calls.last.request.content
    assert cuerpo.count(b'name="fiscal_document"') == 2
    fila = db_session.query(OrderInvoice).one()
    assert fila.pack_id == PACK and fila.document_ids == "doc-pdf,doc-xml"
    ventas = client.get("/api/mercadolibre/facturas").json()["ventas"]
    assert ventas[0]["factura"]["archivos"] == ["factura.pdf", "factura.xml"]


@respx.mock
def test_sin_pack_usa_el_id_del_pedido(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    _venta(db_session, a_store)
    respx.get(f"{ML}/orders/{PEDIDO}").mock(return_value=httpx.Response(200, json={"id": int(PEDIDO), "pack_id": None}))
    ruta = respx.post(f"{ML}/packs/{PEDIDO}/fiscal_documents").mock(return_value=httpx.Response(200, json={"ids": ["doc-pdf"]}))

    assert _subir(client).status_code == 200
    assert ruta.called


def test_rechaza_archivos_invalidos_sin_llamar_a_mercado_libre(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    _venta(db_session, a_store)
    with respx.mock(assert_all_called=False) as ml:
        assert _subir(client, pdf=("factura.txt", PDF, "text/plain")).status_code == 400
        assert _subir(client, pdf=("factura.pdf", b"no soy un pdf", "application/pdf")).status_code == 400
        assert _subir(client, pdf=("factura.pdf", b"%PDF" + b"0" * (1024 * 1024), "application/pdf")).status_code == 400
        assert _subir(client, xml=("factura.pdf", XML, "application/xml")).status_code == 400
    assert ml.calls.call_count == 0
    assert db_session.query(OrderInvoice).count() == 0


def test_venta_con_factura_no_acepta_otra(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    orden = _venta(db_session, a_store)
    db_session.add(OrderInvoice(store_id=a_store.id, order_id=orden.id, pack_id=PACK, document_ids="x", file_names="a.pdf", uploaded_at=NOW))
    db_session.commit()
    with respx.mock(assert_all_called=False) as ml:
        assert _subir(client).status_code == 409
    assert ml.calls.call_count == 0


def test_venta_de_otra_empresa_da_404(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    otro = User(email="otra@facturas.cl", password_hash=hash_password("x"), full_name="Otra", created_at=NOW, updated_at=NOW)
    otra_tienda = Store(owner=otro, name="Otra", created_at=NOW)
    db_session.add_all([otro, otra_tienda])
    db_session.commit()
    _venta(db_session, otra_tienda)

    assert _subir(client).status_code == 404
    assert client.delete(f"/api/mercadolibre/facturas/{PEDIDO}").status_code == 404
    assert client.get("/api/mercadolibre/facturas").json() == {"ventas": []}


@respx.mock
def test_envio_full_rechazado_da_mensaje_claro(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    _venta(db_session, a_store)
    respx.get(f"{ML}/orders/{PEDIDO}").mock(return_value=httpx.Response(200, json={"id": int(PEDIDO), "pack_id": int(PACK)}))
    respx.post(f"{ML}/packs/{PACK}/fiscal_documents").mock(
        return_value=httpx.Response(403, json={"message": "Access denied, you must use the biller of MercadoLibre", "error": "forbidden", "status": 403})
    )

    res = _subir(client)

    assert res.status_code == 400
    assert "Full" in res.json()["detail"]
    assert "biller" not in res.text  # nunca el texto crudo de Mercado Libre
    assert db_session.query(OrderInvoice).count() == 0


@respx.mock
def test_quitar_factura_la_borra_en_mercado_libre_y_en_nexo(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    orden = _venta(db_session, a_store)
    db_session.add(OrderInvoice(store_id=a_store.id, order_id=orden.id, pack_id=PACK, document_ids="x", file_names="a.pdf", uploaded_at=NOW))
    db_session.commit()
    ruta = respx.delete(f"{ML}/packs/{PACK}/fiscal_documents").mock(return_value=httpx.Response(200, json={"message": "deleted"}))

    res = client.delete(f"/api/mercadolibre/facturas/{PEDIDO}")

    assert res.status_code == 200, res.text
    assert res.json()["factura"] is None
    assert ruta.called
    assert db_session.query(OrderInvoice).count() == 0


@respx.mock
def test_quitar_factura_ya_borrada_en_mercado_libre_igual_limpia_nexo(client, db_session, a_store, cuenta_conectada, monkeypatch):
    _settings(monkeypatch)
    orden = _venta(db_session, a_store)
    db_session.add(OrderInvoice(store_id=a_store.id, order_id=orden.id, pack_id=PACK, document_ids="x", file_names="a.pdf", uploaded_at=NOW))
    db_session.commit()
    respx.delete(f"{ML}/packs/{PACK}/fiscal_documents").mock(return_value=httpx.Response(404, json={"message": "not found", "status": 404}))

    assert client.delete(f"/api/mercadolibre/facturas/{PEDIDO}").status_code == 200
    assert db_session.query(OrderInvoice).count() == 0


def test_sin_ventas_la_lista_esta_vacia(client, a_store):
    assert client.get("/api/mercadolibre/facturas").json() == {"ventas": []}
