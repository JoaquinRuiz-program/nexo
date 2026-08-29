"""
Cálculo de rentabilidad — funciones puras (sin red, sin DB), igual que
analysis.py. Núcleo del pedido del dueño (22 de agosto de 2026): el sistema
debe poder decir qué productos convienen realmente, no solo cuáles se
venden más.

Reglas explícitas del dueño, todas aplicadas acá:
- Sin costo de compra cargado -> no se calcula NINGÚN margen (ni bruto ni
  neto). Nunca se muestra un 0 o un margen a medias que parezca un dato real.
- El margen neto de un canal (ej. Mercado Libre) requiere que ese canal
  tenga sus costos configurados (ChannelCostSettings). Si no están
  configurados, tampoco se inventa un número — se devuelve None y quien
  llama debe mostrarlo como "sin configurar", nunca como "$0" ni con un
  porcentaje por defecto tipo 13%.
- La tienda física no cobra comisión ni envío sobre sus propias ventas: su
  margen es siempre el margen bruto.
- Se reporta margen en pesos Y en porcentaje (sobre el precio de venta) —
  el dueño pidió explícitamente ambos, no solo pesos, porque dos productos
  con el mismo margen en pesos pueden tener rentabilidad muy distinta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ChannelCosts:
    """Costos configurados para vender por un canal. Todos opcionales:
    un costo no configurado no cuenta como cero, cuenta como "no sabemos"
    (ver net_margin)."""

    commission_pct: Optional[float] = None
    shipping_cost: Optional[float] = None
    other_fixed_cost: Optional[float] = None

    def is_configured(self) -> bool:
        return self.commission_pct is not None or self.shipping_cost is not None or self.other_fixed_cost is not None


def gross_margin(price: Optional[float], cost: Optional[float]) -> Optional[float]:
    """Margen bruto en pesos: venta - costo. None si falta cualquiera de
    los dos datos (nunca se asume un costo de $0)."""
    if price is None or cost is None:
        return None
    return round(price - cost, 2)


def gross_margin_pct(price: Optional[float], cost: Optional[float]) -> Optional[float]:
    """Margen bruto como % del precio de venta. None si falta algún dato,
    o si el precio es $0 (no se puede calcular % sobre nada)."""
    margin = gross_margin(price, cost)
    if margin is None or not price:
        return None
    return round((margin / price) * 100, 2)


def net_margin(price: Optional[float], cost: Optional[float], channel_costs: ChannelCosts) -> Optional[float]:
    """Margen neto de vender por un canal: margen bruto menos comisión,
    envío y otros costos fijos de ESE canal. None si falta precio/costo, o
    si el canal no tiene NINGÚN costo configurado todavía (no se asume una
    comisión de $0 ni de ningún otro valor)."""
    margin = gross_margin(price, cost)
    if margin is None or not channel_costs.is_configured():
        return None
    commission = (price * channel_costs.commission_pct / 100) if channel_costs.commission_pct else 0.0
    shipping = channel_costs.shipping_cost or 0.0
    other = channel_costs.other_fixed_cost or 0.0
    return round(margin - commission - shipping - other, 2)


def net_margin_pct(price: Optional[float], cost: Optional[float], channel_costs: ChannelCosts) -> Optional[float]:
    margin = net_margin(price, cost, channel_costs)
    if margin is None or not price:
        return None
    return round((margin / price) * 100, 2)
