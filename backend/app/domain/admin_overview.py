"""
Business Intelligence del panel de administrador de Nexo (14 de septiembre de
2026) — SOLO funciones PURAS: calcular el rango de fechas de un período y
agrupar una serie de (fecha, monto) en cubos por día/semana/mes. Sin red, sin
base de datos, sin efectos — igual que profitability.py o catalog_import.py.

Quien consulta la base y arma las métricas es app/api/routes/admin.py::overview
(bajo require_nexo_admin, global a toda la plataforma — nunca scopeado a una
sola empresa). Este módulo solo le da la aritmética de fechas, que es lo único
con lógica suficiente para valer la pena probar aislada.

Regla de oro del dashboard (pedido explícito): NUNCA se inventa un número. Si
no hay datos, el endpoint devuelve 0 o null y el frontend muestra "Sin datos
suficientes". Este módulo nunca rellena un cubo vacío con nada que no sea 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Los períodos que ofrece el filtro del dashboard. "todo" = sin límite inferior.
PERIODOS = ("hoy", "7d", "30d", "este_mes", "mes_anterior", "3m", "6m", "12m", "todo")

# Granularidad del eje temporal según el período — días para tramos cortos,
# semanas para intermedios, meses para largos. Así una serie nunca queda ni
# con un solo punto ni con cientos ilegibles.
GRAN_DIA = "dia"
GRAN_SEMANA = "semana"
GRAN_MES = "mes"


@dataclass(frozen=True)
class RangoPeriodo:
    """Ventana actual [desde, hasta] (ambos inclusive, por día) y la ventana
    INMEDIATAMENTE anterior del mismo largo, para el "vs período anterior".
    `desde`/`desde_prev` en None = sin límite (solo pasa con "todo", que no
    tiene comparación)."""

    desde: date | None
    hasta: date
    desde_prev: date | None
    hasta_prev: date | None
    granularidad: str


def _primer_dia_del_mes(d: date) -> date:
    return d.replace(day=1)


def _mes_anterior(d: date) -> date:
    """Primer día del mes anterior al de `d`."""
    primero = d.replace(day=1)
    return (primero - timedelta(days=1)).replace(day=1)


def _ultimo_dia_del_mes(d: date) -> date:
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


def rango_de_periodo(periodo: str, hoy: date) -> RangoPeriodo:
    """Traduce un período del filtro a fechas concretas. `hoy` se pasa (no se
    lee del reloj acá) para que sea pura y testeable."""
    if periodo == "hoy":
        return RangoPeriodo(hoy, hoy, hoy - timedelta(days=1), hoy - timedelta(days=1), GRAN_DIA)
    if periodo == "7d":
        desde = hoy - timedelta(days=6)
        return RangoPeriodo(desde, hoy, desde - timedelta(days=7), desde - timedelta(days=1), GRAN_DIA)
    if periodo == "30d":
        desde = hoy - timedelta(days=29)
        return RangoPeriodo(desde, hoy, desde - timedelta(days=30), desde - timedelta(days=1), GRAN_DIA)
    if periodo == "este_mes":
        desde = _primer_dia_del_mes(hoy)
        desde_prev = _mes_anterior(hoy)
        # La ventana previa termina el mismo "día del mes" que llevamos hoy,
        # acotado al último día real de ese mes (ej. 31 -> 28/feb).
        dia = min(hoy.day, _ultimo_dia_del_mes(desde_prev).day)
        return RangoPeriodo(desde, hoy, desde_prev, desde_prev.replace(day=dia), GRAN_DIA)
    if periodo == "mes_anterior":
        desde = _mes_anterior(hoy)
        hasta = _ultimo_dia_del_mes(desde)
        desde_prev = _mes_anterior(desde)
        return RangoPeriodo(desde, hasta, desde_prev, _ultimo_dia_del_mes(desde_prev), GRAN_DIA)
    if periodo == "3m":
        desde = hoy - timedelta(days=90)
        return RangoPeriodo(desde, hoy, desde - timedelta(days=91), desde - timedelta(days=1), GRAN_SEMANA)
    if periodo == "6m":
        desde = hoy - timedelta(days=182)
        return RangoPeriodo(desde, hoy, desde - timedelta(days=183), desde - timedelta(days=1), GRAN_SEMANA)
    if periodo == "12m":
        desde = hoy - timedelta(days=364)
        return RangoPeriodo(desde, hoy, desde - timedelta(days=365), desde - timedelta(days=1), GRAN_MES)
    if periodo == "todo":
        return RangoPeriodo(None, hoy, None, None, GRAN_MES)
    raise ValueError(f"Período no reconocido: {periodo!r}")


def _clave_cubo(d: date, granularidad: str) -> date:
    """La fecha REPRESENTATIVA del cubo al que cae `d`: el mismo día, el lunes
    de su semana, o el primer día de su mes."""
    if granularidad == GRAN_DIA:
        return d
    if granularidad == GRAN_SEMANA:
        return d - timedelta(days=d.weekday())  # lunes
    return d.replace(day=1)


def _siguiente_cubo(clave: date, granularidad: str) -> date:
    if granularidad == GRAN_DIA:
        return clave + timedelta(days=1)
    if granularidad == GRAN_SEMANA:
        return clave + timedelta(days=7)
    # mes siguiente
    return _ultimo_dia_del_mes(clave) + timedelta(days=1)


def serie_temporal(
    puntos: list[tuple[date, float]], desde: date | None, hasta: date, granularidad: str
) -> list[dict]:
    """Agrupa (fecha, monto) en cubos consecutivos de la granularidad dada,
    cubriendo TODO el rango [desde, hasta] — incluidos los cubos sin ventas,
    que quedan en 0 (nunca se saltea un hueco: una caída a 0 es un dato). Si
    `desde` es None (período "todo") arranca en la fecha del primer punto; sin
    puntos y sin `desde`, devuelve lista vacía."""
    inicio = desde
    if inicio is None:
        if not puntos:
            return []
        inicio = min(p[0] for p in puntos)

    acumulado: dict[date, float] = {}
    for fecha, monto in puntos:
        clave = _clave_cubo(fecha, granularidad)
        acumulado[clave] = acumulado.get(clave, 0.0) + monto

    cubos: list[dict] = []
    clave = _clave_cubo(inicio, granularidad)
    fin = _clave_cubo(hasta, granularidad)
    # Tope de seguridad: nunca más de 400 cubos aunque el rango sea enorme.
    for _ in range(400):
        if clave > fin:
            break
        cubos.append({"fecha": clave.isoformat(), "monto": round(acumulado.get(clave, 0.0), 2)})
        clave = _clave_cubo(_siguiente_cubo(clave, granularidad), granularidad)
    return cubos


def variacion_pct(actual: float, previo: float) -> float | None:
    """% de crecimiento de `actual` respecto de `previo`. None si no se puede
    calcular con sentido (no había base previa) — nunca se muestra "+100%"
    inventado sobre cero."""
    if previo <= 0:
        return None
    return round((actual - previo) / previo * 100.0, 1)


# ------------------------------------------------------------------
# Clientes que necesitan atención (14 de septiembre de 2026)
# ------------------------------------------------------------------

# Una prueba gratuita que vence dentro de estos días ya se avisa al admin.
DIAS_AVISO_VENCIMIENTO = 7
SEVERIDAD_ORDEN = {"alta": 0, "media": 1, "baja": 2}


def _plural_dias(n: int) -> str:
    return f"{n} día" if n == 1 else f"{n} días"


def motivos_de_atencion(
    *,
    sub_status: str | None,
    current_period_end: date | None,
    ml_status: str | None,
    cantidad_productos: int,
    tickets_sin_resolver: int,
    hoy: date,
) -> list[dict]:
    """Por qué una empresa cliente necesita que el admin la mire. Pura: recibe
    datos reales ya leídos y nunca inventa un motivo. Lista vacía = está bien.
    El vencimiento reusa subscription_lifecycle (misma regla de gracia que la
    pausa real de publicaciones)."""
    from app.domain.subscription_lifecycle import (
        EN_GRACIA, ESTADOS_SUJETOS_A_VENCIMIENTO, VENCIDA, DatosVigencia, dias_hasta_la_pausa, estado_efectivo,
    )

    motivos: list[dict] = []

    def agregar(codigo: str, severidad: str, texto: str) -> None:
        motivos.append({"codigo": codigo, "severidad": severidad, "texto": texto})

    if sub_status is None or current_period_end is None:
        agregar("sin_suscripcion", "alta", "Sin suscripción asignada")
    else:
        vig = DatosVigencia(status=sub_status, current_period_end=current_period_end)
        efectivo = estado_efectivo(vig, hoy)
        if efectivo == VENCIDA:
            agregar("plan_vencido", "alta", "Plan vencido: publicaciones pausadas")
        elif efectivo == EN_GRACIA:
            agregar("en_gracia", "alta", f"Plan vencido: se pausa en {_plural_dias(dias_hasta_la_pausa(vig, hoy))}")
        elif sub_status == "past_due":
            agregar("pago_pendiente", "alta", "Pago pendiente")
        elif sub_status == "canceled":
            agregar("suscripcion_cancelada", "media", "Suscripción cancelada")
        elif sub_status in ESTADOS_SUJETOS_A_VENCIMIENTO:
            dias = (current_period_end - hoy).days
            if dias <= DIAS_AVISO_VENCIMIENTO:
                agregar("por_vencer", "media", "Prueba gratuita vence hoy" if dias == 0 else f"Prueba gratuita vence en {_plural_dias(dias)}")

    if ml_status in ("token_expired", "error"):
        agregar("ml_desconectado", "alta", "Mercado Libre desconectado: necesita reconectar")
    elif ml_status != "connected":
        agregar("sin_mercadolibre", "baja", "Sin Mercado Libre conectado")

    if cantidad_productos == 0:
        agregar("sin_productos", "baja", "Sin productos cargados")

    if tickets_sin_resolver > 0:
        texto = "1 solicitud de soporte sin resolver" if tickets_sin_resolver == 1 else f"{tickets_sin_resolver} solicitudes de soporte sin resolver"
        agregar("soporte_sin_resolver", "media", texto)

    return motivos
