"""
Stock reservado para Mercado Libre — funciones puras (sin red, sin DB).

Decisión explícita del dueño (24 de agosto de 2026): el sistema NO debe
convertirse en un control de inventario físico completo. El dueño sigue
llevando el stock de la tienda presencial "al ojo", a propósito — agregar
movimientos, ajustes y transferencias complicaría el sistema sin que él lo
haya pedido. Lo único que el sistema controla es un tope manual: cuántas
unidades decide reservar para vender por Mercado Libre, sin relación con el
stock físico real.

None vs. 0 — misma distinción que cost_price (nunca se confunde "sin dato"
con "cero"):
- None: el producto no se está ofreciendo por Mercado Libre todavía (nadie
  configuró un tope).
- 0: se ofrecía, y el dueño lo bajó a 0 (a mano, o porque se agotaron las
  unidades reservadas) — deja de venderse por ML sin tocar nada del stock
  físico de la tienda.

Fuera de alcance a propósito (no construido acá): sincronización con
WooCommerce, inventario físico, y el disparador real de "se vendió por
Mercado Libre" (no existe todavía ninguna conexión real con Mercado Libre
— ver domain/profitability.py y el resto del roadmap). `apply_sale` es la
regla que ese disparador va a usar el día que exista; hoy solo está
probada, no conectada a nada.
"""

from __future__ import annotations


class MarketplaceStockError(Exception):
    """Se intentó vender más unidades de las que hay reservadas para
    Mercado Libre, o el producto no se está ofreciendo por ese canal."""


def is_available_for_sale(marketplace_stock: int | None, quantity: int = 1) -> bool:
    """False si el producto no se ofrece por ML (None) o si no alcanza el
    stock reservado para la cantidad pedida."""
    if marketplace_stock is None:
        return False
    return marketplace_stock >= quantity


def apply_sale(marketplace_stock: int | None, quantity: int) -> int:
    """Descuenta una venta del stock reservado para Mercado Libre. Nunca
    baja de 0 ni se aplica si no había suficiente reservado."""
    if quantity <= 0:
        raise ValueError("La cantidad vendida debe ser mayor a 0.")
    if not is_available_for_sale(marketplace_stock, quantity):
        raise MarketplaceStockError(
            f"No hay stock reservado suficiente para Mercado Libre "
            f"(disponible: {marketplace_stock}, solicitado: {quantity})."
        )
    return marketplace_stock - quantity


def set_manual_stock(new_value: int | None) -> int | None:
    """Valida el valor que el dueño ingresa a mano (5 -> 10 -> 0 -> None).
    Nunca negativo — poner 0 es "pausar en ML", no lo mismo que un número
    inválido."""
    if new_value is not None and new_value < 0:
        raise ValueError("El stock para Mercado Libre no puede ser negativo.")
    return new_value
