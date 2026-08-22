"""
Hash de contraseñas — bcrypt directo (sin passlib, cuya integración con
bcrypt 4.x viene dando problemas conocidos en el ecosistema). Nunca se
guarda ni se puede reconstruir la contraseña original: `hash_password`
genera un hash de un solo sentido; `verify_password` compara sin revertirlo.
"""

from __future__ import annotations

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
