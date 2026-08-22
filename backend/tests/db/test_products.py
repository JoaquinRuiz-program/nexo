"""
Pruebas de creación de productos, variantes, y la regla central del
modelo: todo producto (simple o variable) tiene al menos una variante, y
el SKU (cuando existe) es único dentro de la tienda.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Product, ProductVariant


def test_producto_simple_tiene_una_variante(db_session, a_store, now):
    product = Product(
        store=a_store,
        internal_sku="LC-1000",
        name="Cuaderno modelo 1",
        product_type="simple",
        category="Cuadernos",
        created_at=now,
        updated_at=now,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(
        product=product,
        store_id=a_store.id,
        variant_sku="LC-1000",
        price=1990,
        stock_quantity=12,
        manage_stock=True,
        stock_status="instock",
        created_at=now,
        updated_at=now,
    )
    db_session.add(variant)
    db_session.commit()

    assert product.id is not None
    assert len(product.variants) == 1
    assert product.variants[0].stock_quantity == 12


def test_producto_variable_tiene_una_variante_por_color(db_session, a_store, now):
    product = Product(
        store=a_store,
        internal_sku=None,  # el padre "variable" no tiene SKU propio, igual que en WooCommerce real
        name="Cuaderno modelo 6",
        product_type="variable",
        category="Cuadernos",
        created_at=now,
        updated_at=now,
    )
    db_session.add(product)
    db_session.flush()
    colores = ["Rojo", "Azul", "Verde"]
    variants = [
        ProductVariant(
            product=product,
            store_id=a_store.id,
            variant_sku=f"LC-1006-{color[:3].upper()}",
            variant_label=color,
            price=2490,
            stock_quantity=5,
            manage_stock=True,
            stock_status="instock",
            created_at=now,
            updated_at=now,
        )
        for color in colores
    ]
    db_session.add_all(variants)
    db_session.commit()

    assert len(product.variants) == 3
    assert {v.variant_label for v in product.variants} == set(colores)


def test_sku_de_producto_es_unico_dentro_de_la_tienda(db_session, a_store, now):
    db_session.add(
        Product(
            store=a_store,
            internal_sku="LC-2000",
            name="Producto A",
            product_type="simple",
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()

    db_session.add(
        Product(
            store=a_store,
            internal_sku="LC-2000",  # mismo SKU, misma tienda -> debe fallar
            name="Producto B (SKU repetido)",
            product_type="simple",
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_varios_productos_sin_sku_no_chocan_entre_si(db_session, a_store, now):
    """Varios productos con internal_sku=None deben poder coexistir — el
    UNIQUE no debe tratar NULL como un valor repetido (WooCommerce real
    trae productos sin SKU con frecuencia)."""
    for i in range(3):
        db_session.add(
            Product(
                store=a_store,
                internal_sku=None,
                name=f"Producto sin SKU {i}",
                product_type="simple",
                created_at=now,
                updated_at=now,
            )
        )
    db_session.commit()  # no debe lanzar IntegrityError

    total = db_session.query(Product).filter(Product.internal_sku.is_(None)).count()
    assert total == 3


def test_sku_de_variante_es_unico_dentro_de_la_tienda(db_session, a_store, now):
    product = Product(store=a_store, name="Producto", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()

    db_session.add(
        ProductVariant(
            product=product, store_id=a_store.id, variant_sku="LC-DUP", created_at=now, updated_at=now
        )
    )
    db_session.commit()

    db_session.add(
        ProductVariant(
            product=product, store_id=a_store.id, variant_sku="LC-DUP", created_at=now, updated_at=now
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
