"""
Cifrado simétrico de los tokens OAuth de Mercado Libre — se guardan
cifrados en la base de datos, nunca en texto plano (misma filosofía que
`app/domain/security.py` con las contraseñas, pero acá sí hace falta poder
recuperar el valor real: un access token hay que enviarlo tal cual en cada
llamada a la API de Mercado Libre, así que un hash de un solo sentido no
sirve — se cifra, no se hashea).

La clave (`TOKEN_ENCRYPTION_KEY`) vive solo en `.env`, nunca en el código ni
en Git. Sin ella configurada, cifrar/descifrar falla con un error claro en
vez de usar una clave por defecto insegura — eso sería peor que no cifrar
nada, porque daría una falsa sensación de seguridad.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionNotConfigured(Exception):
    """No hay TOKEN_ENCRYPTION_KEY en .env — ver .env.example para generarla."""


def _build_fernet(key: str) -> Fernet:
    if not key:
        raise TokenEncryptionNotConfigured(
            "Falta TOKEN_ENCRYPTION_KEY en backend/.env. Generar una con: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as err:
        raise TokenEncryptionNotConfigured(
            "TOKEN_ENCRYPTION_KEY en backend/.env no es una clave Fernet válida."
        ) from err


def encrypt_token(plain_value: str, key: str) -> str:
    if not plain_value:
        raise ValueError("No se puede cifrar un valor vacío.")
    fernet = _build_fernet(key)
    return fernet.encrypt(plain_value.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_value: str, key: str) -> str:
    fernet = _build_fernet(key)
    try:
        return fernet.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
    except InvalidToken as err:
        raise TokenEncryptionNotConfigured(
            "No se pudo descifrar el token — TOKEN_ENCRYPTION_KEY cambió o es incorrecta."
        ) from err
