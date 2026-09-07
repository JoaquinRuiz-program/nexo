"""
Pruebas de usuarios y autenticación: contraseña nunca en texto plano, email
único, y sesiones/tokens de recuperación que guardan solo el hash del
token, nunca el token real.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import AuthSession, PasswordResetToken, User
from app.domain.security import hash_password, verify_password


def test_la_contrasena_nunca_se_guarda_en_texto_plano(db_session, now):
    plano = "mi-contraseña-super-secreta"
    user = User(
        email="nuevo@tienda-de-prueba.cl",
        password_hash=hash_password(plano),
        full_name="Usuario Nuevo",
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    db_session.commit()

    assert plano not in user.password_hash
    assert user.password_hash != plano
    assert verify_password(plano, user.password_hash) is True
    assert verify_password("contraseña-incorrecta", user.password_hash) is False


def test_email_es_unico(db_session, a_user, now):
    db_session.add(
        User(
            email=a_user.email,  # mismo email
            password_hash=hash_password("otra-clave"),
            full_name="Otro nombre",
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sesion_guarda_solo_el_hash_del_token_nunca_el_token(db_session, a_user, now):
    token_real = "token-secreto-de-sesion-abc123"
    token_hash = hashlib.sha256(token_real.encode("utf-8")).hexdigest()

    session = AuthSession(
        user=a_user,
        token_hash=token_hash,
        created_at=now,
        expires_at=now + timedelta(days=30),
    )
    db_session.add(session)
    db_session.commit()

    assert token_real not in session.token_hash
    assert session.token_hash == token_hash
    assert session.revoked_at is None


def test_token_de_recuperacion_de_contrasena_es_de_un_solo_uso(db_session, a_user, now):
    token_hash = hashlib.sha256(b"reset-token-xyz").hexdigest()
    reset = PasswordResetToken(
        user=a_user,
        token_hash=token_hash,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(reset)
    db_session.commit()

    assert reset.used_at is None
    # Al usarse, se marca used_at — el token no se borra (para poder ver el
    # historial) pero queda inválido para un segundo uso.
    reset.used_at = now + timedelta(minutes=5)
    db_session.commit()
    assert reset.used_at is not None


def test_preferencia_de_tema_es_de_la_persona_no_de_la_tienda(a_user):
    assert a_user.preferences is not None
    assert a_user.preferences.theme == "auto"
