"""
Costos de vender por cada canal (tienda física, Mercado Libre, y los que se
agreguen después) — comisión, envío y otros costos fijos, TODOS
configurables, nunca un porcentaje fijo en el código.

Decisión explícita del dueño (22 de agosto de 2026): no asumir un 13% (ni
ningún otro número) como la comisión real de Mercado Libre — varía por
cuenta y categoría, y usar un valor inventado daría una falsa sensación de
precisión al calcular rentabilidad. Por eso esta tabla empieza vacía: sin
una fila para "mercadolibre", el margen neto de ese canal no se calcula
(ver app/domain/profitability.py) — se muestra como "sin configurar", nunca
como un número construido con un supuesto.

La tienda física no tiene fila acá: no cobra comisión ni envío sobre sus
propias ventas, así que su margen es siempre el margen bruto (venta − costo).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ChannelCostSettings(Base):
    __tablename__ = "channel_cost_settings"
    __table_args__ = (UniqueConstraint("store_id", "channel", name="uq_channel_cost_store_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    # "mercadolibre" hoy; texto libre para no tener que migrar el esquema
    # cuando se agregue otro canal de venta online.
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    commission_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    shipping_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    other_fixed_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship(back_populates="channel_cost_settings")  # noqa: F821
