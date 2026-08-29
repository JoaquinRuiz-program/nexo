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
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # simple | variable — mismo vocabulario que ya usa WooCommerce/el backend hoy
    product_type: Mapped[str] = mapped_column(String(20), nullable=False, default="simple")
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Categoría REAL de Mercado Libre (ej. "MLC180937") — distinta de
    # `category` de arriba (texto libre, del Excel del dueño). Se predice a
    # partir del nombre del producto vía GET /domain_discovery (ver
    # app/domain/ml_fees.py) — nunca la elige el dueño a mano ni se inventa;
    # NULL hasta que se calcule. Sirve para consultar la comisión REAL de
    # Mercado Libre para este producto (varía por categoría).
    ml_category_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ml_category_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # De dónde vino este producto — manual | excel_upload | csv_upload |
    # woocommerce | google_sheets | api. Es solo metadata: el resto del
    # sistema (rentabilidad, selección, publicación) trata un producto igual
    # sin importar su origen, tal como se decidió al hacer el catálogo
    # universal (24 de agosto de 2026) — agregar una fuente nueva más
    # adelante (Shopify, Google Sheets) no debería requerir tocar nada de
    # esto, solo un importador nuevo que termine escribiendo las mismas
    # columnas.
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    # active | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship(back_populates="products")  # noqa: F821
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.position"
    )
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
    # EAN/UPC/GTIN — a nivel de variante porque en WooCommerce real cada
    # color de un producto suele tener su propio código de barras (ver
    # find_barcode_candidates en domain/analysis.py).
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


class ProductImage(Base):
    """
    Referencia a una imagen de producto — NUNCA el archivo en sí (nada de
    base64 en la base de datos, a propósito, ver decisión del 24 de agosto
    de 2026). Hoy solo se llena con `url` cuando el Excel importado trae una
    columna de imagen con una URL válida. El resto de fuentes ya está
    modelado para cuando exista el código que las llene:

    - "excel_url": URL que ya venía en el archivo importado (la única que
      escribe algo real hoy).
    - "embedded_excel": imagen incrustada dentro del archivo Excel — el
      importador de hoy no la extrae todavía.
    - "store_sync": importada desde una tienda online conectada (WooCommerce,
      Shopify) — no hay ningún sync real todavía.
    - "manual_upload": el dueño la sube a mano desde el panel — no existe
      endpoint de subida todavía, ni almacenamiento real (S3 o similar).
    """

    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="excel_url")
    position: Mapped[int] = mapped_column(default=0)  # 0 = imagen principal
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="images")
