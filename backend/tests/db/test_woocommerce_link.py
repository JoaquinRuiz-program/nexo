"""
Pruebas de la relación con WooCommerce: el ID de WooCommerce se guarda como
un dato de vinculación, nunca como el identificador interno del producto —
y no puede repetirse dos veces dentro de la misma tienda (evita vincular el
mismo producto de WooCommerce dos veces por error).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Product, ProductVariant, WooCommerceProduct, WooCommerceVariation


def test_producto_simple_se_vincula_a_un_producto_de_woocommerce(db_session, a_store, now):
    product = Product(store=a_store, internal_sku="LC-1", name="Producto", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()

    link = WooCommerceProduct(
        product=product,
        store_id=a_store.id,
        woocommerce_product_id=555,
        woocommerce_type="simple",
    )
    db_session.add(link)
    db_session.commit()

    assert product.woocommerce_link.woocommerce_product_id == 555
    # El ID interno sigue siendo la clave que usa el resto del sistema — el
    # ID de WooCommerce es un dato adicional, no lo reemplaza.
    assert product.id != link.woocommerce_product_id


def test_producto_variable_vincula_cada_variante_a_su_variacion_de_woocommerce(db_session, a_store, now):
    product = Product(store=a_store, name="Cuaderno", product_type="variable", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    db_session.add(WooCommerceProduct(product=product, store_id=a_store.id, woocommerce_product_id=900, woocommerce_type="variable"))

    variant_rojo = ProductVariant(product=product, store_id=a_store.id, variant_label="Rojo", variant_sku="LC-900-ROJ", created_at=now, updated_at=now)
    variant_azul = ProductVariant(product=product, store_id=a_store.id, variant_label="Azul", variant_sku="LC-900-AZU", created_at=now, updated_at=now)
    db_session.add_all([variant_rojo, variant_azul])
    db_session.flush()

    db_session.add(WooCommerceVariation(variant=variant_rojo, store_id=a_store.id, woocommerce_variation_id=901))
    db_session.add(WooCommerceVariation(variant=variant_azul, store_id=a_store.id, woocommerce_variation_id=902))
    db_session.commit()

    assert variant_rojo.woocommerce_link.woocommerce_variation_id == 901
    assert variant_azul.woocommerce_link.woocommerce_variation_id == 902


def test_no_se_puede_vincular_dos_veces_el_mismo_producto_de_woocommerce(db_session, a_store, now):
    p1 = Product(store=a_store, name="Producto 1", product_type="simple", created_at=now, updated_at=now)
    p2 = Product(store=a_store, name="Producto 2", product_type="simple", created_at=now, updated_at=now)
    db_session.add_all([p1, p2])
    db_session.flush()

    db_session.add(WooCommerceProduct(product=p1, store_id=a_store.id, woocommerce_product_id=123))
    db_session.commit()

    db_session.add(WooCommerceProduct(product=p2, store_id=a_store.id, woocommerce_product_id=123))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
