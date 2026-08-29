"""
Conexión con Mercado Libre (u otro marketplace futuro — por eso el campo
`marketplace` es texto, no algo hardcodeado a "mercadolibre").

Actualizado 24 de agosto de 2026 — OAuth real de Mercado Libre
(app/adapters/mercadolibre.py): `access_token_ref` (el placeholder de
cuando esto no existía todavía) se reemplaza por
`access_token_encrypted`/`refresh_token_encrypted` — el token real, SIEMPRE
cifrado (nunca texto plano, ver app/domain/token_crypto.py) con la clave de
`TOKEN_ENCRYPTION_KEY`. `external_account_id` pasa a usarse de verdad: el
`user_id` numérico que Mercado Libre devuelve en `/users/me`, necesario
para pedir los pedidos del vendedor.

Igual que con WooCommerce: el ID de Mercado Libre vive acá, nunca como
clave primaria de nada más. La forma de saber que "este producto de
WooCommerce corresponde a esta publicación de Mercado Libre" es que ambos
apuntan al mismo `product_id`/`variant_id` interno — no hay ninguna tabla
que relacione un ID de WooCommerce con un ID de Mercado Libre directamente.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MarketplaceAccount(Base):
    __tablename__ = "marketplace_accounts"
    __table_args__ = (UniqueConstraint("store_id", "marketplace", name="uq_marketplace_account_store_marketplace"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False, default="mercadolibre")
    external_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # not_connected | connected | error | token_expired
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_connected")
    # Tokens de OAuth real, SIEMPRE cifrados (ver app/domain/token_crypto.py
    # y TOKEN_ENCRYPTION_KEY) — nunca texto plano, ni siquiera en un backup.
    # NULL hasta que exista una conexión real (no se inventa ningún valor).
    access_token_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    store: Mapped["Store"] = relationship(back_populates="marketplace_accounts")  # noqa: F821
    listings: Mapped[list["MarketplaceListing"]] = relationship(back_populates="account")


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"
    __table_args__ = (
        UniqueConstraint("account_id", "external_listing_id", name="uq_listing_per_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    external_listing_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # not_published | active | paused | closed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_published")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    account: Mapped["MarketplaceAccount"] = relationship(back_populates="listings")
    product: Mapped["Product"] = relationship(back_populates="marketplace_listings")  # noqa: F821
    variants: Mapped[list["MarketplaceListingVariant"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class MarketplaceListingVariant(Base):
    __tablename__ = "marketplace_listing_variants"
    __table_args__ = (
        UniqueConstraint("listing_id", "external_variation_id", name="uq_listing_variation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("marketplace_listings.id"), nullable=False)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), nullable=False)
    external_variation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    stock_quantity: Mapped[int | None] = mapped_column(nullable=True)
    # Marca el stock segregado de Mercado Libre Full — NUNCA se mezcla con
    # el stock compartido/propio (ver arquitectura-fase0-decisiones.md).
    is_full_fulfillment: Mapped[bool] = mapped_column(default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    listing: Mapped["MarketplaceListing"] = relationship(back_populates="variants")
    variant: Mapped["ProductVariant"] = relationship(back_populates="listing_variants")  # noqa: F821
