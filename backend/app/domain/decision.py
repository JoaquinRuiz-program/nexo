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

Regla definitiva (14 de septiembre de 2026, decisión del dueño). "¿Conviene?"
se evalúa SIEMPRE con el precio REAL del producto (Excel/publicación), nunca
con el precio recomendado, y con la MISMA clasificación que Oportunidades
(domain/catalog_selection.py::classify_product, sin exigir stock):

1. Ganancia neta = precio real − costo − comisión − envío − otros costos.
2. Ganancia < 0 -> "no_conviene" (no rentable).
3. Ganancia >= 0: conviene si el margen % alcanza el margen mínimo O la
   ganancia neta alcanza la ganancia neta mínima $; si no cumple ninguna ->
   "no_conviene" (margen bajo).
4. Faltan datos para calcular la ganancia (costo, precio, costos del canal)
   -> "revisar", nunca se inventa una decisión.

El margen objetivo NO participa: solo calcula el precio recomendado. Si es
imposible de alcanzar, se informa en `aviso_margen_objetivo` sin cambiar la
decisión. La competencia tampoco decide: es información.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.domain.competencia import AnalisisCompetencia
from app.domain.pricing import RecomendacionPrecio

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
    # Al precio REAL del producto — los números con los que se decidió.
    precio_actual: Optional[float] = None
    ganancia_actual: Optional[float] = None
    margen_actual_pct: Optional[float] = None
    aviso_margen_objetivo: Optional[str] = None

    def __post_init__(self) -> None:
        if self.faltantes is None:
            object.__setattr__(self, "faltantes", [])


AVISO_MARGEN_OBJETIVO_IMPOSIBLE = "No es posible alcanzar tu margen objetivo con estas condiciones."


def evaluar_decision(
    clasificacion: dict,
    recomendacion: RecomendacionPrecio,
    analisis_competencia: Optional[AnalisisCompetencia] = None,
    *,
    precio_actual: Optional[float] = None,
    ganancia_actual: Optional[float] = None,
    margen_actual_pct: Optional[float] = None,
    hay_piso_configurado: bool = False,
) -> DecisionNegocio:
    """`clasificacion` es el resultado de classify_product sobre la fila de
    rentabilidad al precio REAL (lo que decide). `recomendacion` (pricing.py)
    solo aporta el precio recomendado y el aviso de margen objetivo.
    `hay_piso_configurado`: hay margen mínimo o ganancia neta mínima."""

    base = {
        "precio_recomendado": recomendacion.precio_recomendado,
        "precio_minimo_rentable": recomendacion.precio_minimo_rentable,
        "ganancia_estimada": recomendacion.ganancia_estimada,
        "margen_estimado_pct": recomendacion.margen_estimado_pct,
        "hay_competencia": bool(analisis_competencia and analisis_competencia.hay_competencia),
        # Lo que falta para el precio recomendado (p.ej. margen objetivo) —
        # informativo, nunca cambia la decisión.
        "faltantes": list(recomendacion.faltantes),
        "precio_actual": precio_actual,
        "ganancia_actual": ganancia_actual,
        "margen_actual_pct": margen_actual_pct,
        "aviso_margen_objetivo": AVISO_MARGEN_OBJETIVO_IMPOSIBLE if recomendacion.alcanza_margen_objetivo is False else None,
    }

    tipo = clasificacion.get("clasificacion")
    if tipo in ("no_rentable", "margen_bajo"):
        return DecisionNegocio(decision=NO_CONVIENE, razon=clasificacion.get("razon") or "No alcanza la rentabilidad mínima configurada.", **base)
    if tipo != "rentable":
        return DecisionNegocio(decision=REVISAR, razon=clasificacion.get("razon") or "Faltan datos para calcular la ganancia.", **base)

    if precio_actual is not None and ganancia_actual is not None:
        razon = f"Con tu precio actual ({_clp(precio_actual)}) la ganancia neta es {_clp(ganancia_actual)}"
        if margen_actual_pct is not None:
            razon += f" ({margen_actual_pct:.1f}%)"
    else:
        razon = "Con tu precio actual la venta deja ganancia"
    if hay_piso_configurado:
        razon += " y cumple el margen mínimo o la ganancia neta mínima configurados."
    else:
        razon += " y no deja pérdida (no hay margen mínimo ni ganancia neta mínima configurados)."
    return DecisionNegocio(decision=CONVIENE, razon=razon, **base)
