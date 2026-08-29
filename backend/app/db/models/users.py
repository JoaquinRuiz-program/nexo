"""
Usuarios y todo lo relacionado a autenticación.

Decisiones clave (ver informe A-H entregado al dueño antes de este código):
- La contraseña NUNCA se guarda en texto plano — solo `password_hash`
  (bcrypt, ver app/domain/security.py). No existe ninguna columna ni forma
  de recuperar la contraseña original.
- Las sesiones (`AuthSession`) y los tokens de recuperación
  (`PasswordResetToken`) viven en tablas propias, separadas de `User` — y
  ahí tampoco se guarda el token real, solo su hash. Así, si alguna vez se
  filtrara la base de datos, ningún token ni contraseña queda usable.
- El tema (claro/oscuro/automático) es una preferencia de la PERSONA, no de
  la tienda — por eso vive en `UserPreferences`, separado de
  `StoreSettings` (que sí es por tienda).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # active | suspended | pending_verification
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    stores: Mapped[list["Store"]] = relationship(back_populates="owner")  # noqa: F821
    preferences: Mapped["UserPreferences | None"] = relationship(back_populates="user", uselist=False)
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(back_populates="user")


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    # light | dark | auto
    theme: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")

    user: Mapped["User"] = relationship(back_populates="preferences")


class AuthSession(Base):
    """
    Una sesión iniciada (equivalente real a lo que hoy `js/auth.js` simula
    en el navegador con `lc_session`). Se guarda solo el HASH del token de
    sesión, nunca el token en sí — igual que una contraseña (ver
    app/domain/security.py: hash_session_token, con SHA-256, no bcrypt).
    """

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # La "empresa activa" de ESTA sesión (29 de agosto de 2026 — ver
    # app/api/deps.py:get_current_store). Se fija al loguear, con la
    # primera/única tienda del usuario — hoy nadie tiene más de una, pero
    # que viva en la sesión (no en el usuario) es lo que deja preparado un
    # selector de "cambiar de empresa" más adelante sin volver a rehacer
    # esto: cambiar de tienda activa sería nada más que actualizar esta
    # columna de la sesión actual, no inventar un mecanismo nuevo.
    active_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")
    active_store: Mapped["Store | None"] = relationship()  # noqa: F821


class PasswordResetToken(Base):
    """Token de un solo uso para "¿Olvidaste tu contraseña?". Igual que
    AuthSession, se guarda solo el hash; se marca `used_at` al usarse para
    que no pueda reutilizarse."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")
