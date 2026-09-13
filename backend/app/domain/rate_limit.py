"""
Límite de intentos fallidos — 13 de septiembre de 2026.

Hasta hoy `/api/auth/login` aceptaba intentos ilimitados: alguien podía
probar contraseñas a máquina indefinidamente. Mientras Nexo corría solo en
la máquina del dueño daba igual; expuesto a internet, los bots encuentran
una pantalla de login en horas.

Dos cubetas a propósito, porque son dos ataques distintos:

- por EMAIL: alguien insiste contra una cuenta puntual ("probemos mil
  contraseñas de joaco@...");
- por IP: alguien rocía una contraseña común contra muchas cuentas
  distintas ("probemos 'verano2026' en todos los emails que tengamos"),
  que la cubeta por email no detendría porque cada email falla una vez.

Solo cuentan los intentos FALLIDOS, y un acierto limpia el contador: quien
se equivoca dos veces y después entra bien no arrastra nada.

Limitación conocida, misma que `_pending_states` en
app/api/routes/mercadolibre.py: esto vive en memoria del proceso. Con un
solo worker (que es lo que exige DEPLOY.md hoy) funciona; el día que haya
varias réplicas hay que moverlo a algo compartido (Redis o una tabla) o
cada réplica contará por su cuenta. Se prefiere esto antes que una
dependencia nueva: es poco código y no agrega nada que mantener.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Ventana en la que se acumulan los fallos y cuánto dura el bloqueo una vez
# alcanzado el tope. Quince minutos es suficiente para frenar un ataque
# automatizado sin dejar afuera media hora a alguien que se equivocó.
VENTANA_S = 15 * 60

# Por email: 5 fallos. Alguien que de verdad no recuerda su contraseña
# prueba tres o cuatro veces, no diez.
MAX_FALLOS_POR_EMAIL = 5

# Por IP: más alto a propósito. Una oficina entera puede salir por una sola
# IP y equivocarse legítimamente varias veces el mismo día.
MAX_FALLOS_POR_IP = 20


@dataclass
class _Cubeta:
    fallos: int = 0
    primera_vez: float = field(default_factory=time.monotonic)


_por_clave: dict[str, _Cubeta] = {}


def _cubeta(clave: str, ahora: float) -> _Cubeta:
    c = _por_clave.get(clave)
    if c is None or (ahora - c.primera_vez) > VENTANA_S:
        c = _Cubeta(primera_vez=ahora)
        _por_clave[clave] = c
    return c


def _limpiar_vencidas(ahora: float) -> None:
    """Evita que el diccionario crezca sin techo con un ataque de muchas
    IPs distintas: cada llamada tira lo que ya venció."""
    vencidas = [k for k, c in _por_clave.items() if (ahora - c.primera_vez) > VENTANA_S]
    for k in vencidas:
        _por_clave.pop(k, None)


def esta_bloqueado(*, email: str, ip: str) -> bool:
    """True si este email o esta IP ya agotaron sus intentos en la ventana."""
    ahora = time.monotonic()
    _limpiar_vencidas(ahora)
    por_email = _cubeta(f"email:{(email or '').strip().lower()}", ahora)
    por_ip = _cubeta(f"ip:{ip or 'desconocida'}", ahora)
    return por_email.fallos >= MAX_FALLOS_POR_EMAIL or por_ip.fallos >= MAX_FALLOS_POR_IP


def registrar_fallo(*, email: str, ip: str) -> None:
    ahora = time.monotonic()
    _cubeta(f"email:{(email or '').strip().lower()}", ahora).fallos += 1
    _cubeta(f"ip:{ip or 'desconocida'}", ahora).fallos += 1


def registrar_exito(*, email: str, ip: str) -> None:
    """Un login correcto limpia las dos cubetas: el que se equivocó un par
    de veces y después entró bien no queda arrastrando un contador."""
    _por_clave.pop(f"email:{(email or '').strip().lower()}", None)
    _por_clave.pop(f"ip:{ip or 'desconocida'}", None)


def reiniciar() -> None:
    """Solo para los tests — cada prueba arranca sin contadores previos."""
    _por_clave.clear()


def ip_del_request(request) -> str:  # noqa: ANN001 - fastapi.Request, sin importarlo acá
    """La IP real del cliente. Detrás de un proxy (Render, Cloudflare) la
    conexión viene del proxy, no del cliente: la verdadera está en
    `X-Forwarded-For`, cuyo PRIMER valor es el cliente original.

    Se confía en esa cabecera porque en producción Nexo siempre corre
    detrás de un proxy que la reescribe. Si algún día se expusiera el
    backend directo a internet, cualquiera podría falsearla y saltarse la
    cubeta por IP — la cubeta por email seguiría funcionando igual."""
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"
