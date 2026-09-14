"""
Costo de envío REAL de Mercado Libre por publicación — funciones puras (sin
red, sin DB). 14 de septiembre de 2026.

Pedido del dueño: nunca obligar a cargar peso/medidas ni estimar por tramos.
El costo sale de la API oficial de Mercado Libre para una publicación que ya
existe (verificado en developers.mercadolibre.com.ar/en_us/management-of-shippin-fees,
última actualización 30/12/2025, vale para MLC):

- GET /items/{id} trae `shipping` (mode, logistic_type, free_shipping, tags).
- GET /users/{user_id}/shipping_options/free?item_id={id} devuelve
  `coverage.all_country.list_cost` = "shipping fee offered to the seller"
  (con el descuento por reputación ya aplicado) y `currency_id`. Acepta
  `item_id` en lugar de dimensiones (la doc pide ítem activo, pero la API
  real también responde para uno cerrado). Es propio de Mercado Envíos (mode "me2"): en otros modos el
  vendedor fija su envío y Mercado Libre no informa un costo.

Cualquier caso en que Mercado Libre no entregue un número válido termina en
costo None + motivo legible — nunca en un valor inventado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MOTIVO_NO_PUBLICADO = "El producto todavía no está publicado en Mercado Libre."
MOTIVO_NO_CONSULTADO = "Todavía no se consultó el costo de envío en Mercado Libre."
MOTIVO_SIN_MERCADO_ENVIOS = "La publicación no usa Mercado Envíos: Mercado Libre no informa un costo de envío para el vendedor."
MOTIVO_SIN_COSTO_VALIDO = "Mercado Libre no entregó un costo de envío válido para esta publicación."
MOTIVO_ITEM_INEXISTENTE = "La publicación ya no existe en Mercado Libre."
MOTIVO_SIN_ACCESO = "Mercado Libre no permitió consultar esta publicación."


@dataclass(frozen=True)
class CostoEnvioML:
    costo: float | None
    moneda: str | None = None
    modo: str | None = None
    logistica: str | None = None
    envio_gratis: bool | None = None
    motivo_no_disponible: str | None = None


def _shipping(item: dict[str, Any] | None) -> dict[str, Any]:
    shipping = (item or {}).get("shipping")
    return shipping if isinstance(shipping, dict) else {}


def no_disponible(motivo: str, item: dict[str, Any] | None = None) -> CostoEnvioML:
    """Sin costo, pero conservando los datos de `shipping` que sí vinieron."""
    shipping = _shipping(item)
    envio_gratis = shipping.get("free_shipping")
    return CostoEnvioML(
        costo=None,
        modo=shipping.get("mode"),
        logistica=shipping.get("logistic_type"),
        envio_gratis=envio_gratis if isinstance(envio_gratis, bool) else None,
        motivo_no_disponible=motivo,
    )


def motivo_sin_consulta_de_costo(item: dict[str, Any]) -> str | None:
    """Por qué NO tiene sentido pedirle el costo a Mercado Libre para este
    ítem (None = sí se puede consultar). No se filtra por estado: aunque la
    doc dice "active", la API real (verificado el 14/09/2026 con un ítem
    `closed`) igual devuelve un list_cost válido — si no lo devuelve, la
    respuesta cae en "No disponible" como cualquier otra."""
    if _shipping(item).get("mode") != "me2":
        return MOTIVO_SIN_MERCADO_ENVIOS
    return None


def interpretar_costo_envio(item: dict[str, Any], respuesta: Any) -> CostoEnvioML:
    """Lee `coverage.all_country` de /shipping_options/free. Solo acepta un
    número >= 0 en la misma moneda del ítem."""
    cobertura = respuesta.get("coverage") if isinstance(respuesta, dict) else None
    cobertura = cobertura.get("all_country") if isinstance(cobertura, dict) else None
    if not isinstance(cobertura, dict):
        return no_disponible(MOTIVO_SIN_COSTO_VALIDO, item)

    list_cost = cobertura.get("list_cost")
    moneda = cobertura.get("currency_id")
    moneda_item = item.get("currency_id")
    costo_valido = (
        isinstance(list_cost, (int, float))
        and not isinstance(list_cost, bool)
        and math.isfinite(list_cost)
        and list_cost >= 0
    )
    if not costo_valido or not moneda or (moneda_item and moneda != moneda_item):
        return no_disponible(MOTIVO_SIN_COSTO_VALIDO, item)

    base = no_disponible("", item)
    return CostoEnvioML(
        costo=round(float(list_cost), 2),
        moneda=moneda,
        modo=base.modo,
        logistica=base.logistica,
        envio_gratis=base.envio_gratis,
        motivo_no_disponible=None,
    )
