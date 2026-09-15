"""Endpoints de ventas reales de Mercado Libre (15 de septiembre de 2026):
suman lo que la empresa importó y nunca muestran ventas de otra empresa."""

from __future__ import annotations

from datetime import datetime

from app.db.models import Order, OrderItem, Product, ProductVariant, Store, User
from app.domain.security import hash_password
from tests.test_mercadolibre_endpoints import NOW, a_store, client, db_session  # noqa: F401 — fixtures


def _variante(db_session, tienda, sku, nombre):
    producto = Product(store=tienda, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    variante = ProductVariant(product=producto, store_id=tienda.id, variant_sku=sku, price=10000, created_at=NOW, updated_at=NOW)
    db_session.add(variante)
    db_session.flush()
    return variante


def _venta(db_session, tienda, externo, total, items, *, estado="recibido"):
    orden = Order(
        store=tienda, channel="mercadolibre", external_order_id=externo, order_date=datetime.now(), status=estado,
        total_amount=total, created_at=NOW, updated_at=NOW,
    )
    for variante, sku, cantidad, precio in items:
        orden.items.append(OrderItem(variant=variante, external_item_sku=sku, quantity=cantidad, unit_price=precio, created_at=NOW))
    db_session.add(orden)
    db_session.commit()
    return orden


def test_ventas_importadas_aparecen_en_resumen_grafico_mas_vendidos_y_pedidos(client, db_session, a_store):
    audifonos = _variante(db_session, a_store, "SKU-1", "Audífonos")
    _venta(db_session, a_store, "100", 20000, [(audifonos, "SKU-1", 2, 10000)])
    _venta(db_session, a_store, "101", 5000, [(None, "FUERA-1", 1, 5000)])
    _venta(db_session, a_store, "102", 7000, [(audifonos, "SKU-1", 1, 7000)], estado="cancelado")

    resumen = client.get("/api/mercadolibre/ventas/resumen").json()
    assert (resumen["ventasHoy"], resumen["pedidosHoy"], resumen["pedidosCancelados"]) == (25000, 2, 1)
    assert resumen["pedidosPendientes"] is None  # Mercado Libre no informa el envío: sin datos, nunca 0

    grafico = client.get("/api/mercadolibre/ventas/grafico?rango=7d").json()
    assert len(grafico) == 7 and grafico[-1]["ingresos"] == 25000

    top = client.get("/api/mercadolibre/ventas/mas-vendidos?rango=7d&limite=5").json()
    assert top[0] == {"sku": "SKU-1", "nombre": "Audífonos", "cantidad": 2, "ingresos": 20000.0}
    assert top[1]["nombre"] == "Producto fuera del catálogo de Nexo"

    cancelados = client.get("/api/mercadolibre/pedidos?estado=cancelado").json()
    assert [f["externalId"] for f in cancelados["rows"]] == ["102"]
    assert client.get("/api/mercadolibre/pedidos").json()["total"] == 3


def test_nunca_muestra_ventas_de_otra_empresa(client, db_session, a_store):
    otro = User(email="otra@ventas.cl", password_hash=hash_password("x"), full_name="Otra", created_at=NOW, updated_at=NOW)
    otra_tienda = Store(owner=otro, name="Otra empresa", created_at=NOW)
    db_session.add_all([otro, otra_tienda])
    db_session.commit()
    _venta(db_session, otra_tienda, "900", 50000, [(None, "AJENO-1", 1, 50000)])

    assert client.get("/api/mercadolibre/ventas/resumen").json()["ventasHoy"] == 0
    assert client.get("/api/mercadolibre/pedidos").json()["total"] == 0
    assert client.get("/api/mercadolibre/ventas/mas-vendidos").json() == []


def test_rango_invalido_da_422(client, a_store):
    assert client.get("/api/mercadolibre/ventas/grafico?rango=99d").status_code == 422


def test_sin_sesion_da_401(client):
    assert client.get("/api/mercadolibre/ventas/resumen").status_code == 401
    assert client.get("/api/mercadolibre/pedidos").status_code == 401
