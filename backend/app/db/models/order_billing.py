"""
Conciliación de comisiones con la facturación real de Mercado Libre (14 de
septiembre de 2026). Una fila por venta importada con lo que Mercado Libre
FACTURÓ de verdad (GET /billing/integration/group/ML/order/details, doc
oficial "Billing Reports by Orders and Packs") y la comisión que Nexo había
calculado para esa venta. Sin datos del comprador (la respuesta trae
payer_nickname y provincia: nunca se guardan).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderBilling(Base):
    __tablename__ = "order_billing"
    __table_args__ = (UniqueConstraint("store_id", "order_id", name="uq_order_billing_store_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    # False = Mercado Libre todavía no facturó cargos para esta venta.
    has_charges: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Cargos facturados (detail_type CHARGE): CV = cargo por venta, CXD = Mercado Envíos.
    billed_sale_fee: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    billed_shipping: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    billed_other: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # items_info.item_type de la facturación (gold_special | gold_pro).
    listing_type_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Comisión que calcula Nexo (MercadoLibreCategoryFee al precio vendido);
    # None si no hay categoría o comisión cacheada para ese precio.
    estimated_sale_fee: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
