"""
Ciclo de vida de la suscripción — vencimiento, gracia y recordatorios.
13 de septiembre de 2026.

La decisión de producto que estuvo pendiente mucho tiempo (P1-1), ahora
tomada por el dueño: cuando el plan vence, el cliente tiene 5 días de
gracia. Durante esos 5 días se le manda un recordatorio a los 5, 3 y 1 día
antes de la pausa. Si al terminar la gracia no pagó, se PAUSAN sus
publicaciones reales en Mercado Libre (no solo un bloqueo en Nexo).

A QUIÉN SE LE APLICA (importante, es una decisión de seguridad de negocio):
solo a suscripciones `trialing` (prueba que venció) o `past_due` (un cobro
que falló). NUNCA a una `active`: una suscripción mensual paga se mantiene
al día por el webhook de Mercado Pago, y como el manejo del cobro recurrente
mes-a-mes todavía no está armado (ver app/api/routes/pagos.py, webhook
subscription_authorized_payment sin procesar), `current_period_end` de una
`active` puede quedar viejo — pausar por esa fecha sería pausar a alguien
que SÍ está pagando. Por eso `active` queda fuera: el disparador correcto
para una paga es el webhook marcándola `past_due`, y recién ahí entra acá.

Todo este módulo son funciones PURAS sobre una fecha — sin red, sin base,
sin efectos. Quién manda el mail y quién llama a Mercado Libre para pausar
vive afuera (ver app/api/routes/suscripcion.py::correr_ciclo_de_vida), que
es lo único que se prueba con adaptadores mockeados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Días de gracia después del vencimiento antes de pausar las publicaciones.
DIAS_GRACIA = 5

# Recordatorios: cuántos días ANTES de la pausa se avisa. "5, 3, mañana".
# El de 1 día es el "mañana se pausan tus publicaciones".
HITOS_RECORDATORIO = (5, 3, 1)

# Estados de la suscripción sobre los que ESTE ciclo actúa. `active` queda
# afuera a propósito (ver docstring del módulo); `canceled` tiene su propio
# flujo (el cliente canceló a mano) y no se toca desde acá.
ESTADOS_SUJETOS_A_VENCIMIENTO = ("trialing", "past_due")

# Estados efectivos que devuelve estado_efectivo().
VIGENTE = "vigente"
EN_GRACIA = "en_gracia"
VENCIDA = "vencida"


@dataclass(frozen=True)
class DatosVigencia:
    """Lo mínimo que el ciclo necesita de una suscripción — así las funciones
    no dependen del modelo ORM y se prueban con datos sueltos."""

    status: str
    current_period_end: date
    # El último hito (5/3/1) que ya se avisó, para no repetir el mismo
    # recordatorio si el proceso diario corre más de una vez. None = ninguno.
    ultimo_hito_recordatorio: int | None = None


def fecha_de_pausa(vig: DatosVigencia) -> date:
    """El día en que se pausan las publicaciones: el vencimiento del plan
    más los días de gracia."""
    return vig.current_period_end + timedelta(days=DIAS_GRACIA)


def estado_efectivo(vig: DatosVigencia, hoy: date) -> str:
    """Estado real hoy, mirando la fecha — no el `status` guardado, que puede
    estar viejo si nadie corrió el ciclo todavía.

    - `active`/`canceled`/cualquier otro no sujeto a vencimiento -> VIGENTE
      (este módulo no los toca).
    - dentro del período pagado -> VIGENTE.
    - vencido pero dentro de los 5 días de gracia -> EN_GRACIA.
    - pasada la gracia -> VENCIDA (corresponde pausar)."""
    if vig.status not in ESTADOS_SUJETOS_A_VENCIMIENTO:
        return VIGENTE
    if hoy <= vig.current_period_end:
        return VIGENTE
    if hoy < fecha_de_pausa(vig):
        return EN_GRACIA
    return VENCIDA


def dias_hasta_la_pausa(vig: DatosVigencia, hoy: date) -> int:
    """Cuántos días faltan para la pausa. Puede ser negativo (ya pasó)."""
    return (fecha_de_pausa(vig) - hoy).days


def recordatorio_pendiente(vig: DatosVigencia, hoy: date) -> int | None:
    """Qué hito de recordatorio (5, 3 o 1) toca mandar HOY, o None.

    Idempotente y tolerante a días salteados: si el proceso diario no corrió
    un par de días y se pasó del hito de 5, manda el hito más urgente que ya
    se alcanzó y todavía no se avisó — nunca uno viejo ("te quedan 5 días"
    cuando en realidad quedan 2 sería mentira). Nunca repite un hito ya
    enviado (`ultimo_hito_recordatorio`).

    Los recordatorios corren desde el día del vencimiento (inclusive) hasta
    el día ANTES de la pausa: el primero ("te quedan 5 días") cae el mismo
    día que vence el plan, cuando empiezan los 5 días de gracia."""
    if vig.status not in ESTADOS_SUJETOS_A_VENCIMIENTO:
        return None
    if not (vig.current_period_end <= hoy < fecha_de_pausa(vig)):
        return None
    d = dias_hasta_la_pausa(vig, hoy)
    ya_enviado = vig.ultimo_hito_recordatorio if vig.ultimo_hito_recordatorio is not None else 9999
    # El hito más urgente (valor más chico) que ya se alcanzó (d <= hito) y
    # que es más nuevo que el último enviado (hito < ya_enviado).
    alcanzados = [h for h in HITOS_RECORDATORIO if d <= h and h < ya_enviado]
    return min(alcanzados) if alcanzados else None


def debe_pausar(vig: DatosVigencia, hoy: date) -> bool:
    return estado_efectivo(vig, hoy) == VENCIDA
