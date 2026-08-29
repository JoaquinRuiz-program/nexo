"""
Hash de contraseñas — bcrypt directo (sin passlib, cuya integración con
bcrypt 4.x viene dando problemas conocidos en el ecosistema). Nunca se
guarda ni se puede reconstruir la contraseña original: `hash_password`
genera un hash de un solo sentido; `verify_password` compara sin revertirlo.

29 de agosto de 2026 — se agrega el mismo criterio para el token de sesión
(`AuthSession.token_hash`, ver app/api/deps.py): acá SÍ se usa SHA-256, no
bcrypt. No es una inconsistencia — son problemas distintos: una contraseña
la elige una persona (baja entropía, hay que hashear lento para que
probar millones de contraseñas sea caro) mientras que un token de sesión
ya es 256 bits aleatorios generados acá mismo (alta entropía) — hashearlo
lento no suma seguridad real, solo hace más lenta cada request autenticada.
Mismo motivo por el que Django/Rails usan SHA-256 (no bcrypt) para
identificadores de sesión opacos.
"""

from __future__ import annotations

import hashlib
import secrets

import bcrypt


def hash_password(plain_password: str) -> str:
    if not plain_password:
        raise ValueError("La contraseña no puede estar vacía.")
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_session_token() -> str:
    """El valor real que se manda como cookie al navegador — nunca se
    guarda tal cual en la base (ver hash_session_token)."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Lo que sí se guarda en AuthSession.token_hash — si alguna vez se
    filtrara la base de datos, ningún token de sesión real queda usable
    (mismo criterio que ya se aplicaba a password_hash)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
