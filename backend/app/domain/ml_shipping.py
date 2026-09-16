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
MOTIVO_PUBLICACION_CERRADA = "La publicación de este producto está cerrada en Mercado Libre."
MOTIVO_NO_CONSULTADO = "Todavía no se consultó el costo de envío en Mercado Libre."
MOTIVO_SIN_MERCADO_ENVIOS = "La publicación no usa Mercado Envíos: Mercado Libre no informa un costo de envío para el vendedor."
MOTIVO_SIN_COSTO_VALIDO = "Mercado Libre no entregó un costo de envío válido para esta publicación."
MOTIVO_ITEM_INEXISTENTE = "La publicación ya no existe en Mercado Libre."
MOTIVO_SIN_ACCESO = "Mercado Libre no permitió consultar esta publicación."

# --- Estimación antes de publicar (16 de septiembre de 2026) ---------------
# GET /categories/{id}/shipping_preferences da las medidas por defecto de la
# categoría, y GET /users/{id}/shipping_options/free?dimensions=...&item_price=...
# el costo que le cobrarían al vendedor con esas medidas (ambos verificados en
# vivo contra MLC). Es una estimación: las medidas son las típicas de la
# categoría, no las del producto — el costo REAL de una publicación existente
# siempre gana sobre esto.
MOTIVO_CATEGORIA_SIN_MERCADO_ENVIOS = "Esta categoría no usa Mercado Envíos: el envío lo define el vendedor."
MOTIVO_SIN_MEDIDAS_DE_CATEGORIA = "Mercado Libre no informa medidas por defecto para esta categoría."
MOTIVO_SIN_ESTIMACION = "Mercado Libre no entregó un costo de envío para estas medidas y este precio."
MOTIVO_ENVIO_NO_OBLIGATORIO = "A este precio el envío gratis no es obligatorio: lo paga el comprador."
MOTIVO_BAJO_EL_MINIMO_DEL_DUENO = "Bajo el precio desde el que pagas el envío (Configuración): a este precio lo paga el comprador."
MOTIVO_SIN_CATEGORIA = "Todavía no se detectó la categoría de Mercado Libre de este producto."
MOTIVO_ESTIMACION_NO_CONSULTADA = "Todavía no se consultó el costo de envío estimado en Mercado Libre."
MOTIVO_ESTIMACION_VENCIDA = "El costo de envío estimado quedó vencido y todavía no se pudo actualizar en Mercado Libre."

# Cada cuánto vence una estimación ya guardada: las tarifas de envío de
# Mercado Libre cambian de vez en cuando. Vencida deja de usarse para calcular
# rentabilidad (pasa a ser dato faltante) hasta que se vuelva a consultar —
# vive acá porque lo necesitan tanto quien la refresca (services/ml_comisiones)
# como quien la lee (routes/rentabilidad).
DIAS_VIGENCIA_ESTIMACION_ENVIO = 30


@dataclass(frozen=True)
class EstimacionEnvioML:
    """Costo estimado + si a ese precio Mercado Libre obliga al envío gratis
    (recién ahí lo paga el vendedor)."""

    costo: float | None
    obligatorio: bool | None = None
    motivo_no_disponible: str | None = None


def medidas_por_defecto(preferencias: dict[str, Any] | None) -> str | None:
    """"altoxanchoxlargo,peso" con las medidas por defecto de la categoría, en
    el formato que pide /shipping_options/free. None si faltan datos."""
    dimensiones = (preferencias or {}).get("dimensions")
    if not isinstance(dimensiones, dict):
        return None
    valores = []
    for clave in ("height", "width", "length", "weight"):
        valor = dimensiones.get(clave)
        if not isinstance(valor, (int, float)) or isinstance(valor, bool) or not math.isfinite(valor) or valor <= 0:
            return None
        valores.append(int(round(valor)))
    return f"{valores[0]}x{valores[1]}x{valores[2]},{valores[3]}"


def categoria_usa_mercado_envios(preferencias: dict[str, Any] | None) -> bool:
    """True si la categoría admite Mercado Envíos ("me2"); si no, el vendedor
    define su propio envío y Mercado Libre no le cobra nada por esto."""
    logistica = (preferencias or {}).get("logistics")
    if not isinstance(logistica, list):
        return False
    return any(isinstance(l, dict) and l.get("mode") == "me2" for l in logistica)


def interpretar_estimacion_envio(respuesta: Any) -> EstimacionEnvioML:
    """Lee `coverage.all_country` de /shipping_options/free pedido con medidas.
    `discount.type == "mandatory"` = a ese precio el envío gratis es obligatorio
    en ese sitio, así que el costo corre por cuenta del vendedor."""
    cobertura = respuesta.get("coverage") if isinstance(respuesta, dict) else None
    cobertura = cobertura.get("all_country") if isinstance(cobertura, dict) else None
    if not isinstance(cobertura, dict):
        return EstimacionEnvioML(costo=None, motivo_no_disponible=MOTIVO_SIN_ESTIMACION)

    list_cost = cobertura.get("list_cost")
    if not isinstance(list_cost, (int, float)) or isinstance(list_cost, bool) or not math.isfinite(list_cost) or list_cost < 0:
        return EstimacionEnvioML(costo=None, motivo_no_disponible=MOTIVO_SIN_ESTIMACION)

    descuento = cobertura.get("discount")
    obligatorio = isinstance(descuento, dict) and descuento.get("type") == "mandatory"
    return EstimacionEnvioML(costo=round(float(list_cost), 2), obligatorio=obligatorio)


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
