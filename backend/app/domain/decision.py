"""Motor de decisión "¿conviene vender esto?" (30 de agosto de 2026, FASE 6
del roadmap comercial) — función pura, sin red ni DB, sin FastAPI, sin
Mercado Libre. Se construye ENCIMA de domain/pricing.py: pricing.py calcula
el precio recomendado, este módulo interpreta ese resultado (más la
competencia) para dar una recomendación de negocio explicable.

Arquitectura: competencia.py -> pricing.py -> decision.py -> CONVIENE/REVISAR/NO CONVIENE

Regla de siempre: esto es SOLO análisis y lectura. Nunca publica, nunca
modifica precio ni stock, nunca pausa ni cambia nada en Mercado Libre ni en
la base de Nexo — únicamente interpreta datos ya calculados por pricing.py
y competencia.py.

Reglas de decisión, en orden de prioridad (la primera que aplica gana —
diseño de product-reviewer, 30/08/2026, revisado con los casos límite de
qa-engineer):

1. Sin datos suficientes para calcular un precio (`RecomendacionPrecio.estado
   == datos_insuficientes`) -> "revisar", nunca se inventa una decisión.
2. El margen objetivo es matemáticamente imposible de alcanzar
   (`alcanza_margen_objetivo is False`) -> "no_conviene": ya sabemos que el
   precio recomendado no llega a lo que el dueño pidió como objetivo.
3. Hay margen mínimo configurado y NO se alcanza (`alcanza_margen_minimo is
   False`) -> "no_conviene", sin excepción — esto tiene prioridad incluso si
   el margen objetivo sí se alcanzó (puede pasar si el mínimo configurado es
   mayor al objetivo, una configuración contradictoria que igual no debe
   dar luz verde).
4. Hay margen mínimo configurado pero no se pudo evaluar
   (`alcanza_margen_minimo is None` porque no hay margen mínimo configurado)
   combinado con que TAMPOCO hay dato de competencia -> "revisar": no hay
   suficiente información para decidir con confianza (ver PARTE 2 del
   pedido: "cuando no tengamos datos de competencia, el sistema NO debe
   asumir que el producto no conviene").
5. El precio recomendado queda por encima del rango de competencia
   (`posicion_frente_a_competencia == "por_encima"`) -> "revisar": es
   rentable, pero podría no venderse frente a la competencia real.
6. En cualquier otro caso donde el margen objetivo se alcanza y (no hay
   dato de competencia, o el precio queda en rango, o por debajo del rango)
   -> "conviene".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.domain.competencia import AnalisisCompetencia
from app.domain.pricing import ESTADO_DATOS_INSUFICIENTES, RecomendacionPrecio

CONVIENE = "conviene"
REVISAR = "revisar"
NO_CONVIENE = "no_conviene"


def _clp(monto: float) -> str:
    """Pesos chilenos: punto como separador de miles, sin decimales.

    13 de septiembre de 2026 — antes estos mensajes usaban `{:,.0f}`, que
    produce el formato ingles ("$25,806") y quedaba a la vista del cliente,
    inconsistente con el resto de la aplicacion ("$25.806")."""
    return f"${monto:,.0f}".replace(",", ".")



@dataclass(frozen=True)
class DecisionNegocio:
    decision: str  # CONVIENE | REVISAR | NO_CONVIENE
    razon: str  # explicación en texto plano, para mostrar directo al dueño
    # Copia de los datos que sustentan la decisión — así el llamador (API)
    # no tiene que volver a mirar RecomendacionPrecio/AnalisisCompetencia
    # para armar la respuesta. Nunca se recalcula nada acá.
    precio_recomendado: Optional[float] = None
    precio_minimo_rentable: Optional[float] = None
    ganancia_estimada: Optional[float] = None
    margen_estimado_pct: Optional[float] = None
    hay_competencia: bool = False
    faltantes: Optional[list] = None

    def __post_init__(self) -> None:
        if self.faltantes is None:
            object.__setattr__(self, "faltantes", [])


def evaluar_decision(
    recomendacion: RecomendacionPrecio,
    analisis_competencia: Optional[AnalisisCompetencia] = None,
) -> DecisionNegocio:
    """`recomendacion` viene de domain/pricing.py::recomendar_precio, ya
    calculada por quien llama. `analisis_competencia` es el objeto crudo de
    domain/competencia.py::analizar_competencia (no solo lo que
    RecomendacionPrecio guardó de ella) — se pasa aparte porque
    RecomendacionPrecio no distingue "nunca se consultó competencia" de
    "se consultó y no hay competidor" (hallazgo de qa-engineer), y esa
    distinción sí importa para el texto explicativo."""

    base = {
        "precio_recomendado": recomendacion.precio_recomendado,
        "precio_minimo_rentable": recomendacion.precio_minimo_rentable,
        "ganancia_estimada": recomendacion.ganancia_estimada,
        "margen_estimado_pct": recomendacion.margen_estimado_pct,
        "hay_competencia": bool(analisis_competencia and analisis_competencia.hay_competencia),
    }

    # 1. Sin datos suficientes -> revisar, nunca se inventa una decisión.
    if recomendacion.estado == ESTADO_DATOS_INSUFICIENTES:
        return DecisionNegocio(
            decision=REVISAR,
            razon="Faltan datos para calcular un precio: " + ", ".join(recomendacion.faltantes) + ".",
            faltantes=list(recomendacion.faltantes),
            **base,
        )

    # 2. Margen objetivo matemáticamente imposible.
    if not recomendacion.alcanza_margen_objetivo:
        return DecisionNegocio(
            decision=NO_CONVIENE,
            razon=(
                "El margen objetivo configurado no se puede alcanzar con ningún precio "
                "(la comisión del canal más el margen objetivo superan el 100% del precio). "
                f"El precio mínimo rentable es {_clp(recomendacion.precio_minimo_rentable)}."
            ),
            **base,
        )

    # 3. No alcanza el margen mínimo configurado — prioridad absoluta,
    #    incluso si el objetivo sí se alcanzó (mínimo > objetivo mal configurado).
    if recomendacion.alcanza_margen_minimo is False:
        return DecisionNegocio(
            decision=NO_CONVIENE,
            razon=(
                f"El margen estimado ({recomendacion.margen_estimado_pct:.1f}%) no alcanza el "
                "margen mínimo aceptable configurado para este canal."
            ),
            **base,
        )

    # 4. Sin margen mínimo configurado Y sin dato de competencia: no hay
    #    suficiente información para tener confianza en la decisión.
    sin_margen_minimo_configurado = recomendacion.alcanza_margen_minimo is None
    sin_dato_de_competencia = analisis_competencia is None or not analisis_competencia.hay_competencia
    if sin_margen_minimo_configurado and sin_dato_de_competencia:
        return DecisionNegocio(
            decision=REVISAR,
            razon=(
                "El precio recomendado alcanza el margen objetivo, pero no hay margen mínimo "
                "configurado ni datos de competencia para confirmar la decisión."
            ),
            **base,
        )

    # 5. Precio recomendado por encima del rango de competencia: rentable,
    #    pero podría no venderse.
    if recomendacion.posicion_frente_a_competencia == "por_encima":
        return DecisionNegocio(
            decision=REVISAR,
            razon=(
                f"El precio recomendado ({_clp(recomendacion.precio_recomendado)}) queda por encima "
                f"del rango de precios de la competencia (hasta {_clp(analisis_competencia.rango_precio_maximo)}). "
                "Es rentable, pero podría costar más venderlo."
            ),
            **base,
        )

    # 6. Rentable, y competencia favorable (o sin dato de competencia pero
    #    con margen mínimo ya confirmado en el paso 3/4) -> conviene.
    if sin_dato_de_competencia:
        razon = (
            f"El precio recomendado ({_clp(recomendacion.precio_recomendado)}) alcanza el margen "
            "objetivo y el margen mínimo configurado. No hay datos de competencia disponibles."
        )
    else:
        razon = (
            f"El precio recomendado ({_clp(recomendacion.precio_recomendado)}) alcanza el margen "
            "objetivo y es competitivo frente al mercado."
        )
    return DecisionNegocio(decision=CONVIENE, razon=razon, **base)
