"""
Registro, login, logout y "quién soy" — autenticación real (29 de agosto
de 2026), reemplaza la demo 100% client-side de frontend/js/auth.js
(`lc_session` en el navegador, sin backend detrás).

Registro crea SIEMPRE junto con el usuario: una `Store` (la empresa) y su
`StoreSettings` — nunca queda un usuario sin empresa, porque
`get_current_store` (ver app/api/deps.py) asume que toda sesión tiene una.

Nunca se revela si un email existe o no por separado del password: un
login fallido (email inexistente O password incorrecto) siempre devuelve
el mismo 401 con el mismo mensaje — evita que alguien use este endpoint
para enumerar qué emails están registrados.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import clear_session_cookie, get_current_session, get_current_store, get_current_user, set_session_cookie
from app.config import get_settings
from app.db.models import AuthSession, Store, StoreSettings, User
from app.db.session import get_db
from app.domain.security import generate_session_token, hash_password, hash_session_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_INVALIDO = "Ingresá un email válido."
_PASSWORD_MUY_CORTA = "La contraseña tiene que tener al menos 8 caracteres."
_CREDENCIALES_INVALIDAS = "Email o contraseña incorrectos."


def _email_normalizado(email: str) -> str:
    email = (email or "").strip().lower()
    if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError(_EMAIL_INVALIDO)
    return email


class RegistroRequest(BaseModel):
    email: str
    password: str
    full_name: str
    company_name: str
    store_name: str | None = None
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def _valida_email(cls, v: str) -> str:
        return _email_normalizado(v)

    @field_validator("password")
    @classmethod
    def _valida_password(cls, v: str) -> str:
        if len(v or "") < 8:
            raise ValueError(_PASSWORD_MUY_CORTA)
        return v

    @field_validator("full_name", "company_name")
    @classmethod
    def _no_vacio(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Este campo no puede estar vacío.")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False


def _sesion_publica(user: User, store: Store) -> dict:
    return {
        "usuario": {"id": user.id, "email": user.email, "nombre": user.full_name},
        "empresa": {"id": store.id, "nombre": store.name},
    }


def _crear_sesion(db: Session, response: Response, user: User, remember_me: bool) -> None:
    settings = get_settings()
    ahora = datetime.now()
    horas = settings.session_ttl_hours_recordarme if remember_me else settings.session_ttl_hours
    expira = ahora + timedelta(hours=horas)

    # active_store_id = la primera (única, hoy) tienda del usuario — ver
    # docstring de AuthSession.active_store_id.
    tienda = db.query(Store).filter_by(owner_user_id=user.id).order_by(Store.id).first()

    token = generate_session_token()
    sesion = AuthSession(
        user=user,
        token_hash=hash_session_token(token),
        active_store_id=tienda.id if tienda else None,
        created_at=ahora,
        expires_at=expira,
    )
    db.add(sesion)
    db.commit()
    set_session_cookie(response, token, expires_at=expira, settings=settings)


@router.post("/registro")
def registro(body: RegistroRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    existente = db.query(User).filter_by(email=body.email).first()
    if existente is not None:
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese email.")

    ahora = datetime.now()
    usuario = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        created_at=ahora,
        updated_at=ahora,
    )
    db.add(usuario)
    db.flush()  # necesita usuario.id para la tienda

    tienda = Store(owner=usuario, name=body.company_name, created_at=ahora)
    db.add(tienda)
    db.flush()
    db.add(
        StoreSettings(
            store=tienda,
            company_name=body.company_name,
            store_name=body.store_name or body.company_name,
        )
    )
    db.commit()

    _crear_sesion(db, response, usuario, body.remember_me)
    return _sesion_publica(usuario, tienda)


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    email = (body.email or "").strip().lower()
    usuario = db.query(User).filter_by(email=email).first()
    # Mismo mensaje y mismo código de estado tanto si el email no existe
    # como si la contraseña está mal — ver docstring del módulo.
    if usuario is None or not verify_password(body.password, usuario.password_hash):
        raise HTTPException(status_code=401, detail=_CREDENCIALES_INVALIDAS)

    tienda = db.query(Store).filter_by(owner_user_id=usuario.id).order_by(Store.id).first()
    if tienda is None:
        # Dato corrupto (no debería poder pasar: registro siempre crea una
        # tienda) — nunca se inventa una acá.
        raise HTTPException(status_code=500, detail="Tu cuenta no tiene ninguna empresa asociada todavía.")

    _crear_sesion(db, response, usuario, body.remember_me)
    return _sesion_publica(usuario, tienda)


@router.post("/logout")
def logout(response: Response, sesion: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)) -> dict:
    sesion.revoked_at = datetime.now()
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(usuario: User = Depends(get_current_user), tienda: Store = Depends(get_current_store)) -> dict:
    return _sesion_publica(usuario, tienda)
