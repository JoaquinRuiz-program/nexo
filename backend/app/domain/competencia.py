"""Análisis de competencia (30 de agosto de 2026, FASE 4 del roadmap
comercial) — función pura, sin red ni DB.

Interpreta la respuesta CRUDA de `GET /products/{product_id}` (ver
MercadoLibreAdapter.get_catalog_product) — `buy_box_winner` y
`buy_box_winner_price_range`, confirmados oficialmente en
developers.mercadolibre.cl/es_cl/competencia-en-catalogo. Cubre el "Caso 2"
de la investigación oficial: un producto que el dueño TODAVÍA NO publicó
— es el caso que Nexo puede usar hoy mismo, antes de tener publicaciones
reales (a diferencia de `/suggestions/items/{id}/details` y
`price_to_win`, que exigen que el vendedor ya sea dueño de un ítem
publicado — quedan documentados como próximo paso, no implementados
todavía).

Regla de siempre: nunca se inventa un competidor, un precio o una métrica
que la respuesta real de Mercado Libre no trajo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class AnalisisCompetencia:
    hay_competencia: bool
    precio_ganador: Optional[float] = None
    moneda_ganador: Optional[str] = None
    condicion_ganador: Optional[str] = None
    envio_gratis_ganador: Optional[bool] = None
    logistica_ganador: Optional[str] = None
    reputacion_ganador: Optional[str] = None
    rango_precio_minimo: Optional[float] = None
    rango_precio_maximo: Optional[float] = None
    # "por_debajo" | "en_rango" | "por_encima" | None — solo si se pasó un
    # precio propio Y hay rango real para compararlo.
    posicion_precio_propio: Optional[str] = None


def analizar_competencia(producto_catalogo: dict[str, Any], precio_propio: Optional[float] = None) -> AnalisisCompetencia:
    """`producto_catalogo`: respuesta CRUDA de GET /products/{id}.
    `precio_propio`: el precio real de Nexo para esta variante (nunca se
    inventa acá — lo pasa quien llama, ya leído de la base)."""
    ganador = producto_catalogo.get("buy_box_winner") or {}
    rango = producto_catalogo.get("buy_box_winner_price_range") or {}

    if not ganador:
        return AnalisisCompetencia(hay_competencia=False)

    shipping = ganador.get("shipping") or {}
    seller = ganador.get("seller") or {}
    rango_min = (rango.get("min") or {}).get("price")
    rango_max = (rango.get("max") or {}).get("price")

    posicion: Optional[str] = None
    if precio_propio is not None and rango_min is not None and rango_max is not None:
        if precio_propio < rango_min:
            posicion = "por_debajo"
        elif precio_propio > rango_max:
            posicion = "por_encima"
        else:
            posicion = "en_rango"

    return AnalisisCompetencia(
        hay_competencia=True,
        precio_ganador=ganador.get("price"),
        moneda_ganador=ganador.get("currency_id"),
        condicion_ganador=ganador.get("condition"),
        envio_gratis_ganador=shipping.get("free_shipping"),
        logistica_ganador=shipping.get("logistic_type"),
        reputacion_ganador=seller.get("reputation_level_id"),
        rango_precio_minimo=rango_min,
        rango_precio_maximo=rango_max,
        posicion_precio_propio=posicion,
    )
