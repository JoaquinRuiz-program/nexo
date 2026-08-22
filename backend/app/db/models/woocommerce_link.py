"""
Conexión entre nuestro catálogo interno y WooCommerce.

Se llama `woocommerce_link.py` (no `woocommerce.py`) para no confundirse con
`app/adapters/woocommerce.py`, que es el cliente HTTP — este archivo es solo
las tablas.

El ID de WooCommerce vive ACÁ, nunca reemplaza a `Product.id` /
`ProductVariant.id` como clave primaria en ningún otro lado del sistema
(ver decisión E del informe: "no depender exclusivamente de IDs externos").
Coherente con `arquitectura-fase0-decisiones.md`: el ID de WooCommerce se
puede usar como clave técnica provisional, pero nunca se muestra como si
fuera el SKU.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WooCommerceProduct(Base):
    """Un producto interno "simple" ↔ un producto de WooCommerce (tipo
    simple o el padre de uno variable)."""

    __tablename__ = "woocommerce_products"
    __table_args__ = (UniqueConstraint("store_id", "woocommerce_product_id", name="uq_woo_product_per_store"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    woocommerce_product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # simple | variable, tal como lo reporta WooCommerce
    woocommerce_type: Mapped[str] = mapped_column(nullable=False, default="simple")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    product: Mapped["Product"] = relationship(back_populates="woocommerce_link")  # noqa: F821


class WooCommerceVariation(Base):
    """Una variante interna (de color) ↔ una variación de WooCommerce.
    Solo existe para productos type:"variable" — un producto simple no
    necesita fila acá, porque su único ID de WooCommerce ya vive en
    WooCommerceProduct."""

    __tablename__ = "woocommerce_variations"
    __table_args__ = (
        UniqueConstraint("store_id", "woocommerce_variation_id", name="uq_woo_variation_per_store"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), unique=True, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    woocommerce_variation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    variant: Mapped["ProductVariant"] = relationship(back_populates="woocommerce_link")  # noqa: F821
