"""
Texto de los recordatorios de vencimiento + un adaptador de envío enchufable.
13 de septiembre de 2026.

Mismo patrón que domain/ai_content.py: acá se arma QUÉ dice el mail; QUIÉN lo
manda es una pieza reemplazable. Hoy la única implementación registra el
envío en el log del servidor (no hay servicio de correo conectado todavía —
ver DEPLOY.md: hace falta un Resend/SendGrid con un remitente noreply). El
día que se conecte ese servicio, se implementa `EnviadorDeEmail.enviar` y
nada más cambia: el ciclo de vida (app/api/routes/suscripcion.py) ya llama
a esta interfaz sin saber si el mail sale de verdad o va al log.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("nexo.email")

# Cuántos días faltan para la pausa -> asunto y encabezado del mail.
_TITULOS = {
    5: "Tu plan de Nexo venció — te quedan 5 días",
    3: "Tu plan de Nexo venció — te quedan 3 días",
    1: "Mañana se pausan tus publicaciones de Mercado Libre",
}


def armar_recordatorio(*, nombre_empresa: str, hito: int, nombre_plan: str) -> tuple[str, str]:
    """Devuelve (asunto, cuerpo) del recordatorio para un hito (5, 3 o 1).

    Nunca inventa un monto ni una fecha exacta de cobro: el cliente paga en
    el checkout de Mercado Pago, así que el mail lo manda ahí y no promete
    cifras que este módulo no conoce."""
    titulo = _TITULOS.get(hito, f"Tu plan de Nexo vence pronto ({hito} días)")
    if hito == 1:
        aviso = (
            "Mañana, si no renovás, vamos a pausar tus publicaciones en "
            "Mercado Libre. Se reactivan solas en cuanto pagues."
        )
    else:
        aviso = (
            f"Te quedan {hito} días para renovar tu plan {nombre_plan}. "
            "Pasado ese plazo, tus publicaciones de Mercado Libre se pausan "
            "hasta que pagues (se reactivan solas al pagar)."
        )
    cuerpo = (
        f"Hola, {nombre_empresa}.\n\n"
        f"{aviso}\n\n"
        "Podés renovar desde la sección \"Mi plan\" en Nexo.\n\n"
        "Si ya pagaste, ignorá este mensaje.\n\n"
        "— El equipo de Nexo"
    )
    return titulo, cuerpo


class EnviadorDeEmail(Protocol):
    def enviar(self, *, para: str, asunto: str, cuerpo: str) -> None: ...


class EnviadorPorLog:
    """Implementación por defecto mientras no hay servicio de correo real:
    deja el mail en el log del servidor. Nunca lanza — que falte el correo
    no puede tumbar el proceso diario del ciclo de vida."""

    def enviar(self, *, para: str, asunto: str, cuerpo: str) -> None:
        logger.info("EMAIL (sin servicio real) -> %s | %s", para, asunto)


# Instancia por defecto que usa el resto del backend hasta conectar un
# servicio real. Se cambia en un solo lugar el día del deploy.
enviador_actual: EnviadorDeEmail = EnviadorPorLog()
