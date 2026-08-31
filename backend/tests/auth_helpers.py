"""
Helper compartido para autenticar el `client` de test contra un `User` ya
creado — evita duplicar en cada archivo de tests la creación manual de una
AuthSession + cookie (29 de agosto de 2026, migración de los routers de
negocio a auth real). No usa /api/auth/login (sería más lento y acopla los
tests de negocio a los de auth) — arma la sesión directo en la base, igual
de real que si hubiera pasado por el endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE_NAME
from app.db.models import AuthSession, Store, User
from app.domain.security import generate_session_token, hash_session_token


def autenticar(client: TestClient, db_session: Session, usuario: User, store: Store | None, *, ahora: datetime) -> None:
    """`ahora` es la fecha "de mentira" que usan los demás datos del test
    (`NOW` de cada archivo, ej. 2026-08-22) — se usa tal cual para
    `created_at`, como el resto de las filas de ese test. `expires_at` NO
    puede usar esa misma fecha: `get_current_session` (app/api/deps.py) la
    compara contra el reloj REAL del sistema (`datetime.now()`), y un `NOW`
    de test histórico ya pasado haría que la sesión naciera vencida.

    `store=None` — 30 de agosto de 2026, panel admin de Nexo: un
    administrador de la plataforma no tiene una empresa propia; su sesión
    se autentica igual, con `active_store_id=None`."""
    token = generate_session_token()
    db_session.add(
        AuthSession(
            user=usuario,
            token_hash=hash_session_token(token),
            active_store_id=store.id if store is not None else None,
            created_at=ahora,
            expires_at=datetime.now() + timedelta(hours=24),
        )
    )
    db_session.commit()
    client.cookies.set(SESSION_COOKIE_NAME, token)
