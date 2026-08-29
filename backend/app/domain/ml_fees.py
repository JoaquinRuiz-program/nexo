"""
Comisión REAL de Mercado Libre por producto — nunca un % fijo asumido (ver
app/db/models/channel_costs.py). El dueño lo pidió explícitamente el 29 de
agosto de 2026: "la comisión de Mercado Libre varía por producto" — depende
de tres cosas: la categoría del producto, el precio, y el tipo de
publicación (Clásica y Premium tienen comisiones bien distintas). Se
consulta a la API real de Mercado Libre (GET /listing_prices, ver
app/adapters/mercadolibre.py) — nunca se estima ni se inventa.

De los tipos de publicación que devuelve /listing_prices, esta primera
versión solo interpreta "gold_special" (Clásica) y "gold_pro" (Premium) —
son los dos tipos pagos reales que Mercado Libre le ofrece elegir al
vendedor al publicar manualmente. Los demás tipos que a veces aparecen en
la respuesta (Oro/Plata/Bronce/Oro Premium) devolvieron comisión $0 en las
pruebas reales hechas ese mismo día contra la API — no son opciones que el
dueño elegiría, así que se ignoran acá para no mostrarle una comisión "de
$0" que no representa una alternativa real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# clave interna usada en todo Nexo -> listing_type_id real de Mercado Libre
LISTING_TYPE_IDS: dict[str, str] = {"classic": "gold_special", "premium": "gold_pro"}


@dataclass(frozen=True)
class ListingFee:
    listing_type_name: str
    percentage_fee: float
    fixed_fee: float
    sale_fee_amount: float


def parse_listing_fees(raw: list[dict]) -> dict[str, ListingFee]:
    """Del array crudo que devuelve GET /listing_prices, se queda solo con
    Clásica y Premium (ver docstring del módulo). Devuelve
    {"classic": ListingFee(...), "premium": ListingFee(...)} — puede faltar
    alguna clave si Mercado Libre no ofrece ese tipo de publicación para la
    categoría consultada (nunca se rellena con un valor inventado)."""
    por_listing_type_id = {item.get("listing_type_id"): item for item in raw}
    resultado: dict[str, ListingFee] = {}
    for clave, listing_type_id in LISTING_TYPE_IDS.items():
        item = por_listing_type_id.get(listing_type_id)
        if item is None:
            continue
        detalle = item.get("sale_fee_details") or {}
        resultado[clave] = ListingFee(
            listing_type_name=item.get("listing_type_name") or clave,
            percentage_fee=float(detalle.get("percentage_fee") or 0),
            fixed_fee=float(detalle.get("fixed_fee") or 0),
            sale_fee_amount=float(item.get("sale_fee_amount") or 0),
        )
    return resultado


def elegir_comision_principal(comisiones: dict[str, ListingFee], preferencia: Optional[str]) -> Optional[ListingFee]:
    """Cuál de las comisiones reales (classic/premium) mostrar como "la"
    comisión de Mercado Libre de este producto, según la preferencia del
    canal (ChannelCostSettings.listing_type_pref). Sin preferencia
    configurada (None = "comparar ambas", el default), no hay una
    "principal" — se devuelve None a propósito, para que quien llama
    siga mostrando ambas sin elegir una por el dueño."""
    if preferencia not in LISTING_TYPE_IDS:
        return None
    return comisiones.get(preferencia)
