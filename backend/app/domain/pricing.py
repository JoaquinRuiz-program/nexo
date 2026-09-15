"""Precio recomendado (30 de agosto de 2026, FASE 5 del roadmap comercial)
— funciones puras, sin red ni DB. Reutiliza domain/profitability.py (nunca
duplica el cálculo de margen) y se integra con domain/competencia.py
(nunca implementa una segunda forma de consultar competidores).

Regla de siempre: nunca se inventa un costo, una comisión ni un margen. Si
falta el costo o el canal no tiene comisión/margen objetivo configurado,
se devuelve un estado DATOS_INSUFICIENTES explícito — nunca un precio
calculado con un supuesto.

Esto es una RECOMENDACIÓN, nunca un cambio automático — el dominio ni
siquiera sabe qué hacer con el resultado más allá de devolverlo; aplicar
un precio real a Mercado Libre es una acción completamente aparte que
Nexo v1 no ejecuta (ver PUBLICACION_MERCADOLIBRE.md)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from app.domain.competencia import AnalisisCompetencia
from app.domain.profitability import ChannelCosts, net_margin, net_margin_pct

ESTADO_RECOMENDACION = "recomendacion"
ESTADO_DATOS_INSUFICIENTES = "datos_insuficientes"


@dataclass(frozen=True)
class RecomendacionPrecio:
    estado: str  # ESTADO_RECOMENDACION | ESTADO_DATOS_INSUFICIENTES
    # Lista de qué falta, solo si estado == DATOS_INSUFICIENTES — nunca se
    # inventa el dato faltante, se lo pide.
    faltantes: list[str] = field(default_factory=list)

    precio_minimo_rentable: Optional[float] = None
    precio_recomendado: Optional[float] = None
    margen_estimado_clp: Optional[float] = None
    margen_estimado_pct: Optional[float] = None
    ganancia_estimada: Optional[float] = None  # = margen_estimado_clp, alias explícito del pedido del dueño

    # Del análisis de competencia (domain/competencia.py) — None si no se
    # pasó o Mercado Libre no encontró el producto en su catálogo. Nunca
    # bloquea el cálculo: "sin competencia, el sistema sigue funcionando".
    precio_mercado_ganador: Optional[float] = None
    posicion_frente_a_competencia: Optional[str] = None  # "por_debajo" | "en_rango" | "por_encima" | None

    # ¿El precio recomendado efectivamente llega al margen objetivo pedido?
    # False solo en el caso extremo donde comisión + margen objetivo
    # superan el 100% del precio (matemáticamente imposible) — ahí se
    # recomienda el mínimo rentable en su lugar, nunca un número inventado.
    alcanza_margen_objetivo: bool = True

    # Dato factual (no una decisión): ¿el margen estimado llega al mínimo
    # aceptable configurado? None si no hay margen mínimo configurado (no
    # se asume ninguno). Esto es un INSUMO para el motor "conviene
    # publicar" de FASE 6, no el motor en sí.
    alcanza_margen_minimo: Optional[bool] = None

    # Campo histórico — el motor "¿conviene vender?" (FASE 6, 30 de agosto
    # de 2026) se implementó en un módulo aparte (domain/decision.py,
    # DecisionNegocio) en vez de escribirse acá, para no mezclar el cálculo
    # de precio con la decisión de negocio (RecomendacionPrecio es frozen,
    # y son dos responsabilidades distintas). Siempre None — usar
    # domain/decision.py::evaluar_decision en su lugar.
    clasificacion: Optional[str] = None


def precio_vitrina(precio: float) -> float:
    """Redondea HACIA ARRIBA al precio terminado en 990 (15 de septiembre de
    2026, pedido del dueño): $84.134 -> $84.990. Hacia arriba para no quedar
    nunca bajo el margen objetivo."""
    return float(max(math.ceil((precio - 990) / 1000), 0) * 1000 + 990)


def recomendar_precio(
    *,
    costo: Optional[float],
    channel_costs: ChannelCosts,
    margen_objetivo_pct: Optional[float],
    margen_minimo_pct: Optional[float] = None,
    analisis_competencia: Optional[AnalisisCompetencia] = None,
    ganancia_minima_clp: Optional[float] = None,
) -> RecomendacionPrecio:
    """`channel_costs` y `margen_objetivo_pct` vienen de
    ChannelCostSettings (ver app/api/routes/configuracion.py) — nunca un
    valor por defecto fijo en este módulo. `analisis_competencia` viene de
    domain/competencia.py::analizar_competencia, ya calculado por quien
    llama (nunca se vuelve a consultar la API acá — esto es dominio puro)."""
    faltantes: list[str] = []
    # 15 de septiembre de 2026 — un producto sin costo registrado (o con costo
    # $0) SÍ se evalúa (ver rentabilidad.py::_fila), pero el precio para el
    # margen objetivo sale del costo: sin costo no hay precio que recomendar
    # (con costo $0 daba, p. ej., $8.990 para algo que se vende a $80.000) y se
    # mantiene el precio de venta del dueño. Nunca se inventa uno.
    if not costo:
        faltantes.append("costo de compra")
    if not channel_costs.is_configured():
        faltantes.append("comisión/costos del canal")
    if margen_objetivo_pct is None:
        faltantes.append("margen objetivo del canal")
    elif margen_objetivo_pct < 0:
        # Un margen objetivo negativo no es un escenario de negocio válido
        # (equivale a pedir vender a pérdida "a propósito") — se trata como
        # dato mal configurado, nunca se calcula un precio con eso.
        faltantes.append("margen objetivo del canal (no puede ser negativo)")
    if margen_minimo_pct is not None and margen_minimo_pct < 0:
        faltantes.append("margen mínimo del canal (no puede ser negativo)")
    if ganancia_minima_clp is not None and ganancia_minima_clp < 0:
        faltantes.append("ganancia neta mínima del canal (no puede ser negativa)")
    if faltantes:
        return RecomendacionPrecio(estado=ESTADO_DATOS_INSUFICIENTES, faltantes=faltantes)

    comision_pct = channel_costs.commission_pct or 0.0
    costos_fijos = costo + (channel_costs.shipping_cost or 0.0) + (channel_costs.other_fixed_cost or 0.0)

    # precio tal que margen neto = 0 (punto de equilibrio real, con la
    # comisión real del canal aplicada sobre ESE precio — nunca sobre el
    # costo, la comisión de Mercado Libre siempre es % del precio de venta).
    denominador_minimo = 1 - comision_pct / 100
    if denominador_minimo <= 0:
        # Comisión >= 100% del precio: no hay ningún precio finito que sea
        # rentable. Caso extremo, nunca inventado — se informa tal cual.
        return RecomendacionPrecio(
            estado=ESTADO_DATOS_INSUFICIENTES,
            faltantes=["la comisión configurada del canal es 100% o más — ningún precio sería rentable"],
        )
    precio_minimo_rentable = round(costos_fijos / denominador_minimo, 2)

    # precio tal que margen neto % == margen_objetivo_pct.
    denominador_objetivo = 1 - margen_objetivo_pct / 100 - comision_pct / 100
    if denominador_objetivo <= 0:
        # margen objetivo + comisión >= 100%: matemáticamente imposible
        # alcanzar ese margen con NINGÚN precio — se recomienda el mínimo
        # rentable y se marca que el objetivo no se alcanza, nunca se
        # fuerza un número que no cumple lo pedido.
        precio_recomendado = precio_minimo_rentable
        alcanza_margen_objetivo = False
    else:
        # El margen estimado se calcula abajo sobre este precio ya redondeado.
        precio_recomendado = precio_vitrina(costos_fijos / denominador_objetivo)
        alcanza_margen_objetivo = True

    margen_clp = net_margin(precio_recomendado, costo, channel_costs)
    margen_pct = net_margin_pct(precio_recomendado, costo, channel_costs)

    precio_mercado_ganador: Optional[float] = None
    posicion: Optional[str] = None
    if analisis_competencia is not None and analisis_competencia.hay_competencia:
        precio_mercado_ganador = analisis_competencia.precio_ganador
        rango_min = analisis_competencia.rango_precio_minimo
        rango_max = analisis_competencia.rango_precio_maximo
        if rango_min is not None and rango_max is not None:
            if precio_recomendado < rango_min:
                posicion = "por_debajo"
            elif precio_recomendado > rango_max:
                posicion = "por_encima"
            else:
                posicion = "en_rango"

    # 14 de septiembre de 2026 — el piso se cumple si alcanza el margen mínimo
    # (%) O la ganancia neta mínima ($); None solo si no hay ninguno configurado.
    alcanza_pct = None if margen_minimo_pct is None or margen_pct is None else margen_pct >= margen_minimo_pct
    alcanza_ganancia = None if ganancia_minima_clp is None or margen_clp is None else margen_clp >= ganancia_minima_clp
    alcanza_margen_minimo = None if alcanza_pct is None and alcanza_ganancia is None else bool(alcanza_pct) or bool(alcanza_ganancia)

    return RecomendacionPrecio(
        estado=ESTADO_RECOMENDACION,
        precio_minimo_rentable=precio_minimo_rentable,
        precio_recomendado=precio_recomendado,
        margen_estimado_clp=margen_clp,
        margen_estimado_pct=margen_pct,
        ganancia_estimada=margen_clp,
        precio_mercado_ganador=precio_mercado_ganador,
        posicion_frente_a_competencia=posicion,
        alcanza_margen_objetivo=alcanza_margen_objetivo,
        alcanza_margen_minimo=alcanza_margen_minimo,
    )
