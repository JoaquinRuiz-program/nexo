"""
Pruebas de la relación con Mercado Libre, y de la idea central de la
sección F del informe: WooCommerce y Mercado Libre NUNCA se relacionan
directamente entre sí — ambos cuelgan del mismo producto/variante interno.
"""

from __future__ import annotations

from app.db.models import (
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingVariant,
    Product,
    ProductVariant,
    WooCommerceProduct,
)


def test_publicacion_y_variante_de_publicacion_se_vinculan_al_producto_interno(db_session, a_store, now):
    product = Product(store=a_store, name="Cuaderno", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product=product, store_id=a_store.id, variant_sku="LC-1", price=1990, created_at=now, updated_at=now)
    db_session.add(variant)
    db_session.flush()

    account = MarketplaceAccount(store=a_store, marketplace="mercadolibre", status="not_connected")
    db_session.add(account)
    db_session.flush()

    listing = MarketplaceListing(account=account, product=product, status="not_published", title="Cuaderno", created_at=now)
    db_session.add(listing)
    db_session.flush()

    listing_variant = MarketplaceListingVariant(listing=listing, variant=variant, price=1990, stock_quantity=10)
    db_session.add(listing_variant)
    db_session.commit()

    assert product.marketplace_listings[0].variants[0].variant_id == variant.id


def test_stock_full_queda_marcado_y_no_se_confunde_con_el_stock_compartido(db_session, a_store, now):
    product = Product(store=a_store, name="Libro", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product=product, store_id=a_store.id, variant_sku="LC-2", stock_quantity=20, manage_stock=True, created_at=now, updated_at=now)
    db_session.add(variant)
    db_session.flush()

    account = MarketplaceAccount(store=a_store, marketplace="mercadolibre")
    listing = MarketplaceListing(account=account, product=product, created_at=now)
    db_session.add_all([account, listing])
    db_session.flush()

    full_stock = MarketplaceListingVariant(listing=listing, variant=variant, stock_quantity=8, is_full_fulfillment=True)
    db_session.add(full_stock)
    db_session.commit()

    # El stock propio de la variante (compartido/WooCommerce) sigue en 20 —
    # el stock de Full (8) vive segregado en su propia fila, nunca mezclado.
    assert variant.stock_quantity == 20
    assert full_stock.stock_quantity == 8
    assert full_stock.is_full_fulfillment is True


def test_user_product_id_se_persiste_y_es_opcional(db_session, a_store, now):
    """29 de agosto de 2026 — fase de publicación, commit 2/N: el campo
    todavía no lo llena ningún endpoint (se agrega recién ahora, ver
    migración 2ac0d9aaa3de), pero el modelo tiene que aceptar guardarlo Y
    aceptar que quede vacío (publicaciones existentes/futuras sin ese dato)."""
    product = Product(store=a_store, name="Cuaderno con User Product", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    account = MarketplaceAccount(store=a_store, marketplace="mercadolibre")
    db_session.add(account)
    db_session.flush()

    con_user_product = MarketplaceListing(
        account=account, product=product, external_listing_id="MLC111111111",
        user_product_id="MLCU1234567", status="active", created_at=now,
    )
    db_session.add(con_user_product)
    db_session.commit()
    db_session.refresh(con_user_product)
    assert con_user_product.user_product_id == "MLCU1234567"

    # Nullable de verdad: una publicación sin este dato no debe fallar.
    sin_user_product = MarketplaceListing(
        account=account, product=product, external_listing_id="MLC222222222",
        status="active", created_at=now,
    )
    db_session.add(sin_user_product)
    db_session.commit()
    db_session.refresh(sin_user_product)
    assert sin_user_product.user_product_id is None


def test_un_producto_de_woocommerce_y_su_publicacion_de_ml_se_identifican_por_el_mismo_producto_interno(db_session, a_store, now):
    """Verifica la relación F del informe: no existe una tabla que conecte
    un ID de WooCommerce con un ID de Mercado Libre directamente — la forma
    de saber que corresponden al mismo producto es que ambos apuntan al
    mismo `product_id` interno."""
    product = Product(store=a_store, name="Agenda 2027", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()

    db_session.add(WooCommerceProduct(product=product, store_id=a_store.id, woocommerce_product_id=4242))
    account = MarketplaceAccount(store=a_store, marketplace="mercadolibre")
    db_session.add(account)
    db_session.flush()
    listing = MarketplaceListing(account=account, product=product, external_listing_id="MLC123456789", created_at=now)
    db_session.add(listing)
    db_session.commit()

    # Reconstruyo la relación como lo haría el motor de sincronización:
    # busco por product_id, no por ningún cruce directo Woo<->ML.
    woo_link = product.woocommerce_link
    ml_listings = product.marketplace_listings
    assert woo_link.woocommerce_product_id == 4242
    assert ml_listings[0].external_listing_id == "MLC123456789"
    assert woo_link.product_id == ml_listings[0].product_id == product.id
