"""
Pruebas de pedidos y ventas:
- un pedido con sus líneas,
- el precio se guarda al momento de la venta y no cambia si el precio del
  producto cambia después,
- la clave de idempotencia (tienda + canal + ID externo del pedido) evita
  procesar el mismo pedido dos veces,
- ningún campo de la tabla guarda datos del comprador.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Order, OrderItem, Product, ProductVariant
from app.db.models.orders import Order as OrderModel


def test_pedido_con_lineas_y_relacion_a_la_variante(db_session, a_store, now):
    product = Product(store=a_store, name="Cuaderno", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product=product, store_id=a_store.id, variant_sku="LC-1", price=1990, stock_quantity=10, manage_stock=True, created_at=now, updated_at=now)
    db_session.add(variant)
    db_session.flush()

    order = Order(
        store=a_store,
        channel="mercadolibre",
        external_order_id="ML-ORDER-1",
        order_date=now,
        status="recibido",
        total_amount=3980,
        commission_amount=398,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(OrderItem(order=order, variant=variant, quantity=2, unit_price=1990, created_at=now))
    db_session.commit()

    assert order.items[0].variant_id == variant.id
    assert order.items[0].quantity == 2


def test_precio_de_venta_no_cambia_si_el_precio_del_producto_cambia_despues(db_session, a_store, now):
    product = Product(store=a_store, name="Libro", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product=product, store_id=a_store.id, variant_sku="LC-2", price=5000, created_at=now, updated_at=now)
    db_session.add(variant)
    db_session.flush()

    order = Order(store=a_store, channel="woocommerce", external_order_id="WC-1", order_date=now, total_amount=5000, created_at=now, updated_at=now)
    db_session.add(order)
    db_session.flush()
    item = OrderItem(order=order, variant=variant, quantity=1, unit_price=5000, created_at=now)
    db_session.add(item)
    db_session.commit()

    # Sube el precio del producto DESPUÉS de la venta.
    variant.price = 6500
    db_session.commit()

    db_session.refresh(item)
    assert item.unit_price == 5000  # la venta ya hecha no se recalcula


def test_no_se_puede_registrar_el_mismo_pedido_externo_dos_veces(db_session, a_store, now):
    db_session.add(
        Order(store=a_store, channel="mercadolibre", external_order_id="ML-DUP", order_date=now, total_amount=1000, created_at=now, updated_at=now)
    )
    db_session.commit()

    db_session.add(
        Order(store=a_store, channel="mercadolibre", external_order_id="ML-DUP", order_date=now, total_amount=1000, created_at=now, updated_at=now)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_mismo_id_externo_en_canales_distintos_no_choca(db_session, a_store, now):
    """El mismo ID externo puede repetirse entre canales distintos (p.ej. un
    número de pedido de WooCommerce que numéricamente coincide con uno de
    Mercado Libre) — la idempotencia es por (tienda, canal, ID), no solo ID."""
    db_session.add(
        Order(store=a_store, channel="woocommerce", external_order_id="1000", order_date=now, total_amount=1000, created_at=now, updated_at=now)
    )
    db_session.add(
        Order(store=a_store, channel="mercadolibre", external_order_id="1000", order_date=now, total_amount=1000, created_at=now, updated_at=now)
    )
    db_session.commit()  # no debe lanzar

    assert db_session.query(OrderModel).count() == 2


def test_orden_sin_variante_emparejada_no_se_pierde(db_session, a_store, now):
    """Si no logramos emparejar el SKU/ID reportado por el marketplace con
    nuestro catálogo, igual se guarda el pedido — nunca se pierde una
    venta por un problema de emparejamiento."""
    order = Order(store=a_store, channel="mercadolibre", external_order_id="ML-SIN-MATCH", order_date=now, total_amount=2500, created_at=now, updated_at=now)
    db_session.add(order)
    db_session.flush()
    db_session.add(OrderItem(order=order, variant=None, external_item_sku="SKU-DESCONOCIDO", quantity=1, unit_price=2500, created_at=now))
    db_session.commit()

    assert order.items[0].variant_id is None
    assert order.items[0].external_item_sku == "SKU-DESCONOCIDO"


def test_ningun_campo_de_orders_guarda_datos_del_comprador():
    """Verificación explícita de la decisión tomada con el dueño: `Order` no
    tiene ninguna columna de nombre, alias, dirección, teléfono o email del
    comprador."""
    columnas = {c.name for c in Order.__table__.columns}
    prohibidas = {"buyer_name", "buyer_email", "buyer_phone", "buyer_address", "customer_name", "customer_email", "nickname"}
    assert columnas.isdisjoint(prohibidas)
