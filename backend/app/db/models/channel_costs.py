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
    # Solo aplica al canal "mercadolibre": qué tipo de publicación usa este
    # cliente para decidir CUÁL comisión real mostrar como la principal
    # (classic | premium) — la comisión real varía bastante entre una y
    # otra (29 de agosto de 2026: "depende por cliente", no hay un default
    # universal correcto). NULL = todavía no eligió: se muestran las dos
    # comisiones reales una al lado de la otra, sin asumir ninguna.
    listing_type_pref: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 30 de agosto de 2026 — FASE 5 (precio recomendado): margen objetivo y
    # mínimo aceptable, configurables POR CANAL (mismo criterio que
    # commission_pct: NULL = "no configurado todavía", nunca un número
    # inventado como default — ver domain/pricing.py, que devuelve
    # "datos_insuficientes" si esto falta en vez de asumir, p.ej., 25%).
    target_margin_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    min_margin_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 14 de septiembre de 2026 — ganancia neta mínima por unidad ($). Un
    # producto conviene si alcanza min_margin_pct O esta ganancia (un
    # notebook puede dejar mucha plata con poco %). NULL = no configurada.
    min_profit_clp: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 15 de septiembre de 2026 — precio de venta desde el cual el vendedor paga
    # el envío (bajo ese precio lo paga el comprador). NULL = el envío manual se
    # descuenta en todos los productos. Nunca aplica al envío real de ML.
    shipping_min_price_clp: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship(back_populates="channel_cost_settings")  # noqa: F821


# 14 de septiembre de 2026 — decisión del dueño: mínimos razonables por
# defecto para "¿Conviene?" en Mercado Libre, modificables en Configuración.
MARGEN_MINIMO_PCT_POR_DEFECTO = 15.0
GANANCIA_MINIMA_CLP_POR_DEFECTO = 3000.0


def umbrales_minimos(config: ChannelCostSettings | None) -> tuple[float | None, float | None]:
    """(margen mínimo %, ganancia neta mínima $) efectivos del canal Mercado
    Libre. Sin fila (la empresa nunca guardó su configuración) rigen los
    valores por defecto; con fila, lo que guardó el usuario — un campo que
    dejó vacío (NULL) es un mínimo que decidió no exigir (la migración
    f6b8d0a2c4e5 completó con los defaults las filas que ya existían)."""
    if config is None:
        return MARGEN_MINIMO_PCT_POR_DEFECTO, GANANCIA_MINIMA_CLP_POR_DEFECTO
    return (
        float(config.min_margin_pct) if config.min_margin_pct is not None else None,
        float(config.min_profit_clp) if config.min_profit_clp is not None else None,
    )
