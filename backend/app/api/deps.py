"""
Dependencias de FastAPI para autenticación real (29 de agosto de 2026).

Reemplaza el patrón `_get_default_store(db)` (duplicado en varios routers,
"la primera tienda que exista") por la tienda de la SESIÓN autenticada —
ver el informe entregado al dueño antes de este cambio. `get_current_store`
es, a partir de ahora, el ÚNICO lugar de todo el backend que decide "de qué
empresa es esta request" — ningún endpoint vuelve a confiar en un
`store_id`/`company_id` que mande el cliente.

Sesión = cookie HttpOnly (nunca localStorage, mismo criterio que los
tokens de Mercado Libre). El valor de la cookie es un token aleatorio de
alta entropía (`generate_session_token`); solo su hash SHA-256 se guarda en
`AuthSession.token_hash` — si la base se filtrara, ningún token de sesión
real queda usable.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import AuthSession, Store, User
from app.db.session import get_db
from app.domain.security import hash_session_token

SESSION_COOKIE_NAME = "nexo_session"

# Mensaje único para "no autenticado" y "sesión inválida/vencida" — nunca
# distinguirlos en la respuesta (no darle a un atacante pistas de si un
# token existió alguna vez).
_NO_AUTENTICADO = HTTPException(status_code=401, detail="Iniciá sesión para continuar.")


def set_session_cookie(response: Response, token: str, *, expires_at: datetime, settings: Settings) -> None:
    max_age_s = max(0, int((expires_at - datetime.now()).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age_s,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _get_valid_session(request: Request, db: Session) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise _NO_AUTENTICADO
    token_hash = hash_session_token(token)
    session = db.query(AuthSession).filter_by(token_hash=token_hash).first()
    if session is None:
        raise _NO_AUTENTICADO
    if session.revoked_at is not None:
        raise _NO_AUTENTICADO
    if session.expires_at <= datetime.now():
        raise _NO_AUTENTICADO
    return session


def get_current_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    return _get_valid_session(request, db)


def get_current_user(session: AuthSession = Depends(get_current_session)) -> User:
    return session.user


def store_en_vista_de_admin(session: AuthSession, db: Session) -> Store | None:
    """La empresa que este admin de Nexo está "viendo como" en ESTA sesión,
    o None si no está en ese modo (6 de septiembre de 2026).

    Dos condiciones, siempre las dos: la sesión tiene `viewing_store_id` Y
    el usuario de la sesión ES admin de Nexo AHORA (no cuando entró). Si a
    alguien se le revoca `is_nexo_admin` mientras mira una empresa, el
    contexto deja de aplicar en la siguiente request — nunca queda un
    acceso "heredado" a datos de un cliente. Un usuario común no puede
    fabricarlo: esta columna solo se escribe en
    app/api/routes/admin.py, detrás de require_nexo_admin, y jamás sale de
    nada que mande el cliente."""
    if session.viewing_store_id is None:
        return None
    if not session.user.is_nexo_admin:
        return None
    return db.get(Store, session.viewing_store_id)


def get_current_store(session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)) -> Store:
    """La empresa de ESTA sesión — ver AuthSession.active_store_id. Nunca
    "la primera tienda que exista" (así era antes, ver _get_default_store,
    ahora eliminado router por router).

    6 de septiembre de 2026 — "ver como empresa": si esta sesión (de un
    admin de Nexo) tiene un contexto de empresa activo, ESA es la empresa
    de la request. Sigue siendo el único punto de todo el backend que
    decide de qué empresa es cada request: ningún router de negocio se
    entera de que hay un admin del otro lado."""
    en_vista = store_en_vista_de_admin(session, db)
    if en_vista is not None:
        return en_vista
    if session.viewing_store_id is not None and session.user.is_nexo_admin:
        # El contexto apunta a una empresa que ya no existe (la borraron
        # mientras el admin la miraba): error real, nunca caer en silencio
        # a la tienda propia del admin, que sería mirar datos de otra
        # empresa sin darse cuenta.
        raise HTTPException(status_code=404, detail="La empresa que estabas viendo ya no existe.")
    if session.active_store_id is None:
        # No debería pasar nunca en la práctica: /api/auth/registro siempre
        # crea una tienda junto con el usuario. Si pasa (dato corrupto,
        # migración vieja), es un error real del servidor, no un 401 — el
        # usuario SÍ está autenticado, solo que su sesión no tiene a qué
        # empresa apunta.
        raise HTTPException(status_code=500, detail="Tu sesión no tiene una empresa activa asociada.")
    store = db.get(Store, session.active_store_id)
    if store is None:
        raise HTTPException(status_code=500, detail="La empresa de tu sesión ya no existe.")
    return store


def require_nexo_admin(user: User = Depends(get_current_user)) -> User:
    """Guard exclusivo del panel de administrador de Nexo (dueño de la
    plataforma) — 30 de agosto de 2026. Único lugar de todo el backend que
    lee `User.is_nexo_admin`; ningún router de negocio de cliente lo toca.
    Nunca reemplaza a `get_current_store` ni lo reutiliza — un admin de
    Nexo NO tiene una "empresa activa" en el sentido de un cliente, así
    que todo router bajo /api/admin/* depende de ESTO, nunca de
    get_current_store. Mismo criterio de "único punto de verdad" que ya
    usa get_current_store para el aislamiento por tienda."""
    if not user.is_nexo_admin:
        # 404, no 403: no confirmarle a un usuario común que /api/admin/*
        # existe en absoluto (mismo criterio que el resto del proyecto usa
        # para no revelar la existencia de recursos ajenos).
        raise HTTPException(status_code=404, detail="No encontrado.")
    return user


__all__ = [
    "SESSION_COOKIE_NAME",
    "set_session_cookie",
    "clear_session_cookie",
    "get_current_session",
    "get_current_user",
    "get_current_store",
    "store_en_vista_de_admin",
    "require_nexo_admin",
]
