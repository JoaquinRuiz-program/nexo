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


def resolver_listing_type(raw_fees: list[dict], opcion: str) -> Optional[dict]:
    """29 de agosto de 2026, commit 4/N (publicación real): busca dentro del
    array CRUDO de GET /listing_prices el item cuyo `listing_type_name` real
    coincide (sin distinguir mayúsculas) con "clásica"/"premium" — a
    propósito, NO usa LISTING_TYPE_IDS acá. El dueño pidió explícitamente
    que el `listing_type_id` que se manda en POST /items se resuelva en
    vivo por nombre en el momento de publicar, no confiando ciegamente en
    la constante de arriba (pensada solo para mostrar comisiones
    informativas, no para construir el payload real). Devuelve el dict
    crudo completo (trae listing_type_id, currency_id, sale_fee_amount,
    etc. reales) o None si esa opción no está disponible para la
    categoría/cuenta consultada."""
    nombre_buscado = {"classic": "clásica", "premium": "premium"}.get(opcion)
    if nombre_buscado is None:
        return None
    for item in raw_fees:
        nombre = (item.get("listing_type_name") or "").strip().lower()
        if nombre == nombre_buscado:
            return item
    return None


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


TIPO_PUBLICACION_LABEL = {"classic": "Clásica", "premium": "Premium"}


@dataclass(frozen=True)
class RecomendacionTipoPublicacion:
    tipo: str  # "classic" | "premium"
    razon: str


def _neto_pct(precio: float, costo: float, fee: ListingFee, shipping: float, other: float) -> Optional[float]:
    """Margen neto como % del precio, con la comisión EXACTA de este tipo de
    publicación. None si el precio es 0 (no se puede sacar %)."""
    if not precio:
        return None
    neto = precio - costo - (fee.percentage_fee / 100.0 * precio + fee.fixed_fee) - shipping - other
    return neto / precio * 100.0


def recomendar_tipo_publicacion(
    precio: Optional[float],
    costo: Optional[float],
    comisiones: dict[str, ListingFee],
    *,
    shipping_cost: float = 0.0,
    other_fixed_cost: float = 0.0,
    target_margin_pct: Optional[float] = None,
) -> Optional[RecomendacionTipoPublicacion]:
    """Elige AUTOMÁTICAMENTE Clásica vs Premium para ESTE producto, con la
    comisión real y exacta de cada tipo (14 de septiembre de 2026, pedido del
    dueño: "que el sistema te diga cuál te recomienda según el margen, con la
    comisión exacta por producto" — reemplaza el listing_type_pref manual).

    Regla: Clásica por defecto — menor comisión, más utilidad, y es lo que
    Mercado Libre mismo sugiere para empezar. Se sube a Premium SOLO cuando el
    producto aguanta su comisión más alta sin bajar del margen objetivo del
    canal (target_margin_pct): ahí se gana la mayor visibilidad y las 12
    cuotas sin resignar la rentabilidad buscada. Sin target configurado, o si
    Premium no llega al objetivo, queda Clásica. Devuelve None si faltan datos
    (sin precio/costo, o sin ninguna comisión real cacheada todavía)."""
    if precio is None or costo is None or not comisiones:
        return None

    classic = comisiones.get("classic")
    premium = comisiones.get("premium")

    # Si solo hay una de las dos, esa es la recomendación (no hay elección).
    if classic is None and premium is None:
        return None
    if premium is None:
        return RecomendacionTipoPublicacion("classic", "Es el único tipo de publicación disponible para esta categoría.")
    if classic is None:
        return RecomendacionTipoPublicacion("premium", "Es el único tipo de publicación disponible para esta categoría.")

    neto_premium_pct = _neto_pct(precio, costo, premium, shipping_cost, other_fixed_cost)
    neto_classic_pct = _neto_pct(precio, costo, classic, shipping_cost, other_fixed_cost)

    if (
        target_margin_pct is not None
        and neto_premium_pct is not None
        and neto_premium_pct >= target_margin_pct
    ):
        return RecomendacionTipoPublicacion(
            "premium",
            f"El margen aguanta la comisión de Premium y aún deja {neto_premium_pct:.0f}% "
            f"(sobre tu objetivo de {target_margin_pct:.0f}%): más visibilidad y 12 cuotas sin resignar rentabilidad.",
        )

    razon = "Menor comisión que Premium, así te queda más utilidad; es lo que Mercado Libre recomienda para empezar."
    if neto_classic_pct is not None and neto_premium_pct is not None:
        razon = (
            f"Clásica te deja {neto_classic_pct:.0f}% de margen vs {neto_premium_pct:.0f}% en Premium — "
            "más utilidad, y es lo que Mercado Libre recomienda para empezar."
        )
    return RecomendacionTipoPublicacion("classic", razon)
