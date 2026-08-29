"""
Catálogo interno — el corazón del modelo.

Decisión clave (D del informe A-H): TODO producto tiene al menos una
`ProductVariant`, incluso los "simple" (que tienen exactamente una, sin
color/etiqueta). Así el precio/stock/SKU vive siempre en el mismo lugar,
sin importar el tipo — igual que ya asume el frontend hoy (`catalogRows`
trata cada fila igual, sea o no una variante de color) y que
`expand_variable_products`/`expandForTable` ya generan ("una fila por
color").

El identificador interno (`Product.id` / `ProductVariant.id`, autogenerado
por la base) es la única clave usada en el resto del sistema — nunca un ID
externo (WooCommerce o Mercado Libre). Ver `woocommerce.py` y
`marketplace.py` para cómo se conectan esos IDs externos SIN volverse la
clave primaria de nada.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        # SKU interno único DENTRO de la tienda — pero solo cuando existe
        # (no todos los productos tienen todavía un SKU propio definido; ya
        # lo vimos en la auditoría real de WooCommerce). SQLite/Postgres
        # tratan múltiples NULL como no-conflictivos en un UNIQUE, así que
        # esta restricción no bloquea productos sin SKU.
        UniqueConstraint("store_id", "internal_sku", name="uq_product_store_internal_sku"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    internal_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # simple | variable — mismo vocabulario que ya usa WooCommerce/el backend hoy
    product_type: Mapped[str] = mapped_column(String(20), nullable=False, default="simple")
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # active | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship(back_populates="products")  # noqa: F821
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    woocommerce_link: Mapped["WooCommerceProduct | None"] = relationship(  # noqa: F821
        back_populates="product", uselist=False
    )
    marketplace_listings: Mapped[list["MarketplaceListing"]] = relationship(back_populates="product")  # noqa: F821


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("store_id", "variant_sku", name="uq_variant_store_sku"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    # Denormalizado a propósito: permite el UNIQUE de arriba sin un join, y
    # deja buscar "todas las variantes de esta tienda" sin pasar por Product.
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    variant_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Etiqueta de la variante — hoy siempre color en WooCommerce, pero se
    # deja como texto libre por si algún día se varía por otro atributo.
    variant_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Precio de compra (lo que le cuesta al dueño, no lo que cobra) — nunca
    # viene de WooCommerce ni de Mercado Libre, ninguno de los dos lo expone.
    # Hoy solo existe en un Excel del dueño; se carga acá vía
    # app/db/import_costs.py. NULL hasta que se cargue — un producto sin
    # costo no debe mostrar ningún margen inventado (ver domain/profitability.py).
    cost_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Unidades que el dueño decide RESERVAR para vender por Mercado Libre —
    # NO es (ni pretende ser) el stock físico de la tienda. Decisión
    # explícita del dueño (24 de agosto de 2026): el sistema no debe
    # convertirse en un control de inventario físico completo (sin
    # movimientos, ajustes ni transferencias) — la tienda presencial se
    # sigue controlando "al ojo", fuera del sistema. Esto es solo un tope
    # manual: "ofrezco N unidades por ML, sin importar cuántas haya en
    # realidad en el local". None = no se está ofreciendo el producto por
    # ML todavía (distinto de 0, que es "se ofrecía y el dueño lo pausó o ya
    # se vendieron todas las reservadas") — ver app/domain/marketplace_stock.py.
    marketplace_stock: Mapped[int | None] = mapped_column(nullable=True)
    stock_quantity: Mapped[int | None] = mapped_column(nullable=True)  # None = no se gestiona stock
    manage_stock: Mapped[bool] = mapped_column(default=False)
    # instock | outofstock | backorder — igual vocabulario que WooCommerce
    stock_status: Mapped[str] = mapped_column(String(20), nullable=False, default="instock")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="variants")
    woocommerce_link: Mapped["WooCommerceVariation | None"] = relationship(  # noqa: F821
        back_populates="variant", uselist=False
    )
    listing_variants: Mapped[list["MarketplaceListingVariant"]] = relationship(back_populates="variant")  # noqa: F821
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="variant")  # noqa: F821
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="variant")  # noqa: F821
