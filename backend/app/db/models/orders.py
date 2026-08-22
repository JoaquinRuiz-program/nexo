"""
Pedidos y ventas.

Decisión confirmada explícitamente con el dueño antes de este código:
NINGÚN dato del comprador se guarda acá (ni nombre, ni alias, ni dirección,
ni contacto) — solo lo necesario para operar el pedido y calcular métricas
de venta. Si más adelante hace falta mostrar algo del comprador, se agrega
como columna nueva (aditivo), nunca hay que rediseñar esta tabla.

`unit_price` en `OrderItem` se guarda AL MOMENTO DE LA VENTA y nunca se
recalcula después, aunque el precio del producto cambie — ya decidido en
`arquitectura-fase0-decisiones.md`. El estado de `Order` sigue la secuencia
ya acordada: recibido → picking → packing → etiquetado → listo_despacho →
entregado_a_operador → completado, más "cancelado" y "problema" como
excepciones. Los pedidos Full (`shipping_type="full"`) no pasan por el
picking/packing interno de la librería.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

ORDER_STATUSES = (
    "recibido",
    "picking",
    "packing",
    "etiquetado",
    "listo_despacho",
    "entregado_a_operador",
    "completado",
    "cancelado",
    "problema",
)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # La clave de idempotencia ya definida en la arquitectura: antes de
        # procesar un pedido nuevo, se busca por esta combinación. Si ya
        # existe, no se vuelve a procesar.
        UniqueConstraint("store_id", "channel", "external_order_id", name="uq_order_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id"), nullable=True
    )
    # woocommerce | mercadolibre
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    order_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="recibido")
    # normal | full
    shipping_type: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    commission_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship(back_populates="orders")  # noqa: F821
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    # Nullable a propósito: si el marketplace reporta un SKU/ID que no
    # logramos emparejar con nuestro catálogo, igual queremos guardar el
    # pedido — nunca perder una venta por un problema de emparejamiento.
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"), nullable=True)
    external_item_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    # Precio AL MOMENTO DE LA VENTA — nunca se recalcula si el precio del
    # producto cambia después.
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    variant: Mapped["ProductVariant | None"] = relationship(back_populates="order_items")  # noqa: F821
