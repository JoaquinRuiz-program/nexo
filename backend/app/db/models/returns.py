"""
Devoluciones reales de Mercado Libre (14 de septiembre de 2026), sincronizadas
desde los reclamos del vendedor (GET /post-purchase/v1/claims/search) y el
detalle de su devolución (GET /post-purchase/v2/claims/{id}/returns).

Mismo criterio que `orders`: NINGÚN dato del comprador (ni nombre, ni
dirección, ni el user_id del reclamante) — solo los estados que el dueño
necesita para saber qué pasó con la venta y con la plata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderReturn(Base):
    __tablename__ = "order_returns"
    __table_args__ = (UniqueConstraint("store_id", "external_claim_id", name="uq_order_return_store_claim"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    # Venta de Nexo a la que corresponde, si ya fue importada.
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    external_claim_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # resource_id del reclamo (el pedido de Mercado Libre).
    external_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    claim_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Estado de la devolución: opened, shipped, delivered, closed, ... (None si
    # el reclamo todavía no tiene devolución asociada).
    return_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # retained | refunded | available
    money_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    claim_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    return_closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
