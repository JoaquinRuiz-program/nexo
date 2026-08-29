"""
Mapea un pedido real de la API de Mercado Libre (`GET /orders/search` o
`GET /orders/{id}`) a los campos que Order/OrderItem necesitan — función
pura (sin red, sin DB), igual que analysis.py y profitability.py.

Regla explícita del dueño (24 de agosto de 2026): NO se guarda ningún dato
personal del comprador. El payload real de Mercado Libre trae un objeto
"buyer" completo (id, nickname, first_name, etc.) — esta función nunca lo
toca ni lo copia a ningún campo. Lo único que se extrae es lo necesario
para identificar la operación y conciliarla con el catálogo: ID del pedido,
fecha, ítems (SKU/cantidad/precio), estado, y el monto de comisión REAL que
Mercado Libre ya cobró (viene en cada ítem como "sale_fee" — no es un
porcentaje estimado, es el cargo real de esa venta puntual).

`unit_price` de cada ítem es el precio al que se vendió en Mercado Libre,
tal como lo reporta el pedido — no se recalcula ni se reemplaza por el
precio actual del catálogo (mismo criterio ya aplicado en OrderItem).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Estados de Mercado Libre -> nuestro vocabulario interno de Order.status.
# Todo lo que no sea "cancelled" entra como "recibido": el resto del ciclo
# (picking/packing/etiquetado/despacho) lo avanza el dueño a mano dentro de
# la librería, Mercado Libre no lo sabe ni lo reporta.
_ML_STATUS_TO_INTERNAL = {
    "cancelled": "cancelado",
}
DEFAULT_STATUS = "recibido"


def map_order_status(ml_status: str) -> str:
    return _ML_STATUS_TO_INTERNAL.get(ml_status, DEFAULT_STATUS)


def map_ml_order(raw_order: dict[str, Any]) -> dict[str, Any]:
    """Convierte el JSON crudo de un pedido de Mercado Libre en los campos
    que necesita Order + su lista de OrderItem. No toca `raw_order["buyer"]`
    ni ningún otro dato personal, aunque venga en el payload real."""
    items = raw_order.get("order_items") or []

    comision_total = sum(
        float(item.get("sale_fee") or 0) for item in items if item.get("sale_fee") is not None
    )
    tiene_comision = any(item.get("sale_fee") is not None for item in items)

    return {
        "external_order_id": str(raw_order["id"]),
        "order_date": _parse_date(raw_order.get("date_created")),
        "status": map_order_status(raw_order.get("status", "")),
        "total_amount": float(raw_order.get("total_amount", 0)),
        # None si Mercado Libre no informó comisión para ningún ítem — no
        # se inventa un 0 que parecería "sin comisión" cuando en realidad
        # es "no sabemos".
        "commission_amount": round(comision_total, 2) if tiene_comision else None,
        "items": [_map_order_item(item) for item in items],
    }


def _map_order_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    item = raw_item.get("item") or {}
    # Mercado Libre expone el SKU del vendedor como "seller_sku" cuando está
    # cargado, o dentro de seller_custom_field en cuentas más viejas — se
    # prueban ambos, sin inventar un SKU si ninguno vino.
    sku = item.get("seller_sku") or item.get("seller_custom_field")
    return {
        "external_item_id": item.get("id"),
        "sku": sku,
        "titulo": item.get("title"),
        "quantity": int(raw_item.get("quantity", 1)),
        "unit_price": float(raw_item.get("unit_price", 0)),
        "sale_fee": float(raw_item["sale_fee"]) if raw_item.get("sale_fee") is not None else None,
    }


def _parse_date(raw_date: str | None) -> datetime:
    if not raw_date:
        raise ValueError("El pedido de Mercado Libre no trae date_created.")
    # Mercado Libre devuelve ISO 8601 con offset, ej. "2026-08-24T10:00:00.000-04:00"
    return datetime.fromisoformat(raw_date)
