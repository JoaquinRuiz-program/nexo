"""
Pruebas de app/domain/token_crypto.py — en particular, que sin una clave
configurada no hay un valor por defecto inseguro, falla claro.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.domain.token_crypto import TokenEncryptionNotConfigured, decrypt_token, encrypt_token


@pytest.fixture()
def key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_cifra_y_descifra_el_mismo_valor(key):
    original = "APP_USR-1234567890-real-access-token"
    cifrado = encrypt_token(original, key)

    assert cifrado != original
    assert decrypt_token(cifrado, key) == original


def test_sin_clave_configurada_falla_claro_en_vez_de_usar_una_por_defecto():
    with pytest.raises(TokenEncryptionNotConfigured):
        encrypt_token("algun-token", key="")


def test_no_se_puede_cifrar_un_valor_vacio(key):
    with pytest.raises(ValueError):
        encrypt_token("", key)


def test_descifrar_con_la_clave_equivocada_falla_claro(key):
    otra_clave = Fernet.generate_key().decode("utf-8")
    cifrado = encrypt_token("un-token", key)

    with pytest.raises(TokenEncryptionNotConfigured):
        decrypt_token(cifrado, otra_clave)
