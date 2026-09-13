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

from app.api.deps import (
    clear_session_cookie,
    get_current_session,
    get_current_user,
    set_session_cookie,
    store_en_vista_de_admin,
)
from app.config import get_settings
from app.db.models import AuthSession, Store, StoreSettings, User
from app.db.session import get_db
from app.domain.plans import crear_suscripcion_inicial
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


def _sesion_publica(user: User, store: Store | None, sesion: AuthSession | None = None) -> dict:
    # 6 de septiembre de 2026 — "ver como empresa": si esta sesión de un
    # admin de Nexo tiene un contexto de empresa activo (ver
    # app/api/routes/admin.py::entrar_a_ver_empresa), se lo decimos siempre
    # al frontend, que mientras dure muestra un aviso persistente. Nunca
    # silencioso. `sesion` es None en registro/login (una sesión recién
    # creada nunca está viendo otra empresa) — solo /me lo pasa de verdad.
    modo_soporte = None
    if sesion is not None and sesion.viewing_store_id is not None and user.is_nexo_admin:
        modo_soporte = {
            "adminEmail": user.email,
            "empresaId": store.id if store is not None else None,
            "empresaNombre": store.name if store is not None else None,
        }
    return {
        "usuario": {"id": user.id, "email": user.email, "nombre": user.full_name},
        # None solo para un administrador de Nexo sin tienda propia (ver
        # is_nexo_admin) — todo usuario cliente siempre tiene una empresa.
        "empresa": {"id": store.id, "nombre": store.name} if store is not None else None,
        "esNexoAdmin": user.is_nexo_admin,
        "modoSoporte": modo_soporte,
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
    # Toda empresa nueva arranca con una suscripción trial al plan básico —
    # nunca queda sin plan asignado (ver app/domain/plans.py).
    crear_suscripcion_inicial(db, tienda, ahora=ahora)
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
    # 30 de agosto de 2026 — panel admin de Nexo: `User.status` ya existe
    # con el valor "suspended" desde antes, pero nada lo aplicaba. Ahora sí
    # bloquea el login — es lo que le da sentido real al estado
    # "Suspendido" que puede fijar un administrador de Nexo.
    if usuario.status == "suspended":
        raise HTTPException(status_code=403, detail="Esta cuenta está suspendida. Contactá a soporte.")

    tienda = db.query(Store).filter_by(owner_user_id=usuario.id).order_by(Store.id).first()
    if tienda is None and not usuario.is_nexo_admin:
        # Dato corrupto (no debería poder pasar: registro siempre crea una
        # tienda) — nunca se inventa una acá. Un administrador de Nexo SÍ
        # puede no tener tienda propia (no es un cliente).
        raise HTTPException(status_code=500, detail="Tu cuenta no tiene ninguna empresa asociada todavía.")

    _crear_sesion(db, response, usuario, body.remember_me)
    return _sesion_publica(usuario, tienda)


@router.post("/logout")
def logout(response: Response, sesion: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)) -> dict:
    sesion.revoked_at = datetime.now()
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str

    @field_validator("password_nueva")
    @classmethod
    def _valida_password(cls, v: str) -> str:
        if len(v or "") < 8:
            raise ValueError(_PASSWORD_MUY_CORTA)
        return v


@router.post("/cambiar-password")
def cambiar_password(
    body: CambiarPasswordRequest,
    db: Session = Depends(get_db),
    usuario: User = Depends(get_current_user),
    sesion: AuthSession = Depends(get_current_session),
) -> dict:
    """13 de septiembre de 2026 — antes el botón "Cambiar contraseña" de
    Configuración abría un cartel que decía que no estaba disponible: no
    existía ninguna forma de cambiarla, ni desde la aplicación ni
    recuperándola. Esto cubre el caso de alguien que SÍ recuerda su
    contraseña actual; recuperarla sin recordarla necesita envío de email y
    sigue pendiente.

    Pide la contraseña actual a propósito: sin eso, cualquiera con acceso
    físico a una sesión abierta podría dejar afuera al dueño de la cuenta.

    Al cambiarla se revocan TODAS las demás sesiones de ese usuario (la que
    está usando ahora se mantiene, para no obligarlo a entrar de nuevo justo
    después de cambiarla). Es lo que se espera de un cambio de contraseña:
    si alguien más había quedado dentro, deja de estarlo."""
    if not verify_password(body.password_actual, usuario.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta.")
    if body.password_actual == body.password_nueva:
        raise HTTPException(status_code=400, detail="La contraseña nueva tiene que ser distinta de la actual.")

    ahora = datetime.now()
    usuario.password_hash = hash_password(body.password_nueva)
    usuario.updated_at = ahora
    otras = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == usuario.id, AuthSession.id != sesion.id, AuthSession.revoked_at.is_(None))
        .all()
    )
    for s in otras:
        s.revoked_at = ahora
    db.commit()
    return {"ok": True, "sesionesCerradas": len(otras)}


@router.get("/me")
def me(usuario: User = Depends(get_current_user), sesion: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)) -> dict:
    # No usa get_current_store: un administrador de Nexo (is_nexo_admin)
    # puede no tener ninguna tienda propia, y /me es lo primero que llama
    # el frontend al hidratar sesión (tiene que funcionar para los dos
    # tipos de usuario, nunca 500 para un admin válido sin empresa).
    #
    # 6 de septiembre de 2026 — si el admin está viendo una empresa, la
    # empresa que reporta /me es ESA (la misma que van a usar los endpoints
    # de negocio, ver deps.py::get_current_store): que las dos cosas
    # coincidan es lo que hace que el frontend pinte la empresa correcta
    # después de un refresh, sin guardar nada en el navegador.
    en_vista = store_en_vista_de_admin(sesion, db)
    if en_vista is not None:
        tienda = en_vista
    else:
        tienda = db.get(Store, sesion.active_store_id) if sesion.active_store_id is not None else None
    return _sesion_publica(usuario, tienda, sesion)
