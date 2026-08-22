"""
Ledger de stock — historial de movimientos, nunca un número sobrescrito
(decisión ya tomada en `arquitectura-fase0-decisiones.md`). `stock_quantity`
en `ProductVariant` sigue existiendo como el valor actual (para lecturas
rápidas), pero cada cambio queda además registrado acá, de forma que
siempre se puede reconstruir "cómo llegamos a este número".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), nullable=False)
    change_quantity: Mapped[int] = mapped_column(Integer, nullable=False)  # signed: +N o -N
    resulting_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # sync_woocommerce | sync_mercadolibre | manual_adjustment | order_placed | order_canceled
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # ej. "order" | "sync_job"
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    variant: Mapped["ProductVariant"] = relationship(back_populates="stock_movements")  # noqa: F821
