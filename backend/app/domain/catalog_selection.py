"""
Motor de selección: "¿qué productos conviene publicar en Mercado Libre?"
(24 de agosto de 2026, pedido central del pivote a plataforma universal).

Funciones puras — trabajan sobre las filas que ya arma
app/api/routes/rentabilidad.py::build_profitability_rows, nunca recalculan
un margen por su cuenta (eso es trabajo exclusivo de domain/profitability.py).

Ningún umbral vive hardcodeado acá: "rentable" es lo que el usuario decida
que es rentable (SelectionCriteria), nunca una definición fija del sistema.
Si el sistema no tiene el dato para evaluar un producto (sin costo, canal
sin configurar), la clasificación es "sin_datos" — nunca se fuerza una
respuesta rentable/no rentable con información que no existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SelectionCriteria:
    # "margen superior a $X" / "margen superior a X%" — quien llama decide
    # cuál (o ambos) aplican; ninguno es la definición "correcta" de rentable.
    min_margin_clp: Optional[float] = None
    min_margin_pct: Optional[float] = None
    # 13 de septiembre de 2026 — el stock YA NO decide si algo es rentable.
    # "Rentable o no" se juzga SOLO por el margen monetario (pedido del
    # dueño). El stock es una cosa aparte, que se completa/pregunta en la
    # revisión, nunca oculta si el producto deja plata. Por eso el default
    # es False; el gate de publicar (que sí necesita stock real para vender)
    # lo chequea por su cuenta, con un mensaje propio.
    require_marketplace_stock: bool = False
    # "tienda" (margen bruto) o "mercadolibre" (margen neto del canal).
    channel: str = "tienda"


def classify_product(row: dict, criteria: SelectionCriteria) -> dict:
    """Devuelve {"clasificacion": ..., "razon": ...}. Clasificaciones
    posibles: rentable | margen_bajo | no_rentable | sin_stock | sin_datos."""

    if not row.get("tieneCosto"):
        return {"clasificacion": "sin_datos", "razon": "Todavía no se cargó el costo de compra de este producto."}

    if criteria.channel == "mercadolibre":
        if not row.get("mercadoLibreConfigurado"):
            return {
                "clasificacion": "sin_datos",
                "razon": "Los costos del canal Mercado Libre (comisión/envío) todavía no están configurados.",
            }
        margen_clp = row.get("margenMercadoLibreClp")
        margen_pct = row.get("margenMercadoLibrePct")
    else:
        margen_clp = row.get("margenTiendaClp")
        margen_pct = row.get("margenTiendaPct")

    # "tieneCosto" solo confirma que hay costo — el margen también necesita
    # el precio de venta. Un producto con costo pero sin precio (o
    # viceversa) llega hasta acá con margen_clp=None: sin esto, caería en
    # "rentable" por descarte, sin haberse podido calcular nada de verdad.
    if margen_clp is None:
        return {
            "clasificacion": "sin_datos",
            "razon": "Falta el precio de venta o el costo de compra — no se puede calcular el margen.",
        }

    if criteria.require_marketplace_stock and not row.get("marketplaceStock"):
        return {
            "clasificacion": "sin_stock",
            "razon": "No hay unidades reservadas para Mercado Libre todavía (marketplaceStock).",
        }

    if margen_clp is not None and margen_clp < 0:
        return {
            "clasificacion": "no_rentable",
            "razon": f"La utilidad estimada sería negativa (${margen_clp:,.0f}) después de costos.".replace(",", "."),
        }

    if criteria.min_margin_clp is not None and margen_clp is not None and margen_clp < criteria.min_margin_clp:
        return {
            "clasificacion": "margen_bajo",
            "razon": (
                f"La utilidad estimada (${margen_clp:,.0f}) está por debajo del mínimo pedido "
                f"(${criteria.min_margin_clp:,.0f})."
            ).replace(",", "."),
        }

    if criteria.min_margin_pct is not None and margen_pct is not None and margen_pct < criteria.min_margin_pct:
        return {
            "clasificacion": "margen_bajo",
            "razon": f"El margen estimado ({margen_pct:.1f}%) está por debajo del mínimo pedido ({criteria.min_margin_pct:.1f}%).",
        }

    return {"clasificacion": "rentable", "razon": None}


def select(rows: list[dict], criteria: SelectionCriteria, *, top_n: Optional[int] = None) -> list[dict]:
    """Clasifica cada fila y, si se pide un top_n, deja solo a los N
    productos rentables con mayor margen — el resto de los "rentables" pasa
    a "no_seleccionado" (siguen siendo rentables, solo no entraron al cupo)."""
    clasificadas = [{**row, **classify_product(row, criteria)} for row in rows]

    if top_n is not None:
        margen_key = "margenMercadoLibreClp" if criteria.channel == "mercadolibre" else "margenTiendaClp"
        rentables = sorted(
            (r for r in clasificadas if r["clasificacion"] == "rentable"),
            key=lambda r: r.get(margen_key) or 0,
            reverse=True,
        )
        top_ids = {r["id"] for r in rentables[:top_n]}
        for r in clasificadas:
            if r["clasificacion"] == "rentable" and r["id"] not in top_ids:
                r["clasificacion"] = "no_seleccionado"
                r["razon"] = f"Es rentable, pero quedó fuera del top {top_n} por margen."

    return clasificadas


def summarize_selection(rows: list[dict]) -> dict[str, int]:
    return {
        "total": len(rows),
        "rentables": sum(1 for r in rows if r["clasificacion"] == "rentable"),
        "margenBajo": sum(1 for r in rows if r["clasificacion"] == "margen_bajo"),
        "noRentables": sum(1 for r in rows if r["clasificacion"] == "no_rentable"),
        "sinStock": sum(1 for r in rows if r["clasificacion"] == "sin_stock"),
        "sinDatos": sum(1 for r in rows if r["clasificacion"] == "sin_datos"),
        "noSeleccionados": sum(1 for r in rows if r["clasificacion"] == "no_seleccionado"),
    }
