"""
Prueba del ledger de stock: cada cambio queda registrado en su propia fila,
nunca se sobreescribe un número sin dejar rastro (decisión ya tomada en
arquitectura-fase0-decisiones.md).
"""

from __future__ import annotations

from app.db.models import Product, ProductVariant, StockMovement


def test_los_cambios_de_stock_quedan_en_un_historial_no_se_sobreescriben(db_session, a_store, now):
    product = Product(store=a_store, name="Cuaderno", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product=product, store_id=a_store.id, variant_sku="LC-1", stock_quantity=10, manage_stock=True, created_at=now, updated_at=now)
    db_session.add(variant)
    db_session.flush()

    db_session.add(StockMovement(variant=variant, change_quantity=-2, resulting_quantity=8, reason="order_placed", reference_type="order", reference_id=1, created_at=now))
    variant.stock_quantity = 8
    db_session.add(StockMovement(variant=variant, change_quantity=+20, resulting_quantity=28, reason="sync_woocommerce", created_at=now))
    variant.stock_quantity = 28
    db_session.commit()

    assert len(variant.stock_movements) == 2
    assert variant.stock_quantity == 28
    # El historial completo sigue disponible aunque el valor actual cambió dos veces.
    assert [m.resulting_quantity for m in variant.stock_movements] == [8, 28]
