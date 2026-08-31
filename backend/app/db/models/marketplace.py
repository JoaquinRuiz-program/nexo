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

Multiempresa (Nexo es un SaaS: cada `Store` es una empresa cliente
distinta, Librería Central es solo la primera): `store_id` es lo que hace
que cada empresa tenga su propia conexión, tokens y seller de Mercado
Libre, completamente aislados de las demás — nunca hay una sola conexión
"global" de Nexo. A propósito `external_account_id` (el seller_id de
Mercado Libre) NO tiene una constraint de unicidad global: la única
constraint es `(store_id, marketplace)` — una empresa no puede tener dos
conexiones activas del mismo marketplace a la vez, pero nada impide que dos
empresas distintas conecten cada una su propio seller. No agregar una
unique constraint sobre `external_account_id` solo salvo que aparezca una
razón de negocio real para prohibir que dos empresas usen el mismo seller
(ej. una agencia gestionando la misma cuenta ML desde dos Stores de Nexo).
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
    # Nickname y site_id (ej. "MLC") que devuelve GET /users/me — solo para
    # que el dueño pueda confirmar de un vistazo "esta es mi cuenta real",
    # nunca datos personales (nombre real, email, teléfono, dirección
    # también vienen en /users/me pero jamás se guardan acá).
    external_account_nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_account_site_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    # ID del "User Product" real de Mercado Libre (ej. "MLCU1234567") — lo
    # devuelve gratis la misma respuesta de POST /items, ver
    # MercadoLibreAdapter.create_item (29 de agosto de 2026, fase de
    # publicación). Nadie lo usa todavía en v1 (que no actualiza ni agrupa
    # variantes) — se guarda ahora para no necesitar otra migración el día
    # que sí haga falta. Nullable siempre: no todas las publicaciones
    # necesariamente lo tendrán (ver User Products, ítems previos al
    # modelo nuevo).
    user_product_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # `family_name` real mandado a Mercado Libre (30 de agosto de 2026,
    # soporte User Products) — solo se llena cuando la cuenta es
    # `user_product_seller` (ver domain/ml_seller_capabilities.py); NULL en
    # cualquier publicación hecha con el modelo clásico (`title`). Es
    # puramente de auditoría: Nexo v1 no agrupa variantes en una familia
    # real de Mercado Libre todavía, cada publicación es independiente.
    family_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
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


class MercadoLibreCategoryFee(Base):
    """Caché de la comisión REAL de Mercado Libre (GET /listing_prices) por
    categoría + tipo de publicación + precio exacto, ver app/domain/ml_fees.py.

    Scopeada por `store_id` a propósito: aunque hoy la comisión de Mercado
    Libre parece ser la misma para cualquier vendedor en una categoría dada,
    nunca se asume — ML puede aplicar descuentos de comisión por reputación
    u otras condiciones propias de cada cuenta, así que la comisión que
    consultó la Empresa A nunca se le muestra a la Empresa B como si fuera
    la suya. Cache exacta (no por rango de precio): evita mostrar un número
    aproximado como si fuera el real.
    """

    __tablename__ = "mercadolibre_category_fees"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "category_id", "listing_type_id", "price",
            name="uq_ml_category_fee_store_category_listing_type_price",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    category_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # "gold_special" (Clásica) | "gold_pro" (Premium) — ver LISTING_TYPE_IDS
    # en app/domain/ml_fees.py.
    listing_type_id: Mapped[str] = mapped_column(String(30), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    percentage_fee: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    fixed_fee: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    sale_fee_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship()  # noqa: F821
