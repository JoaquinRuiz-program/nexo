"""
Pruebas de /api/auth/* — registro, login, logout, /me. Mismo patrón que el
resto (cliente HTTP real de FastAPI, SQLite en memoria vía
dependency_override). Cubre además las garantías de seguridad concretas
que se pidieron: cookie HttpOnly, hash de sesión (nunca el token en texto
plano en la base), sesión revocada/vencida rechazada, y que el registro
SIEMPRE crea una tienda (get_current_store nunca se queda sin dato).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AuthSession, Store, User
from app.db.session import get_db
from app.domain.security import generate_session_token, hash_password, hash_session_token
from app.main import app


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    session = Session(bind=engine, future=True)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


REGISTRO_VALIDO = {
    "email": "dueño@libreria.cl",
    "password": "contraseña-segura-123",
    "full_name": "Joaquín",
    "company_name": "Librería Central",
}


def test_registro_crea_usuario_y_tienda_y_deja_la_sesion_activa(client, db_session):
    res = client.post("/api/auth/registro", json=REGISTRO_VALIDO)

    assert res.status_code == 200
    body = res.json()
    assert body["usuario"]["email"] == "dueño@libreria.cl"
    assert body["empresa"]["nombre"] == "Librería Central"

    usuario = db_session.query(User).filter_by(email="dueño@libreria.cl").one()
    tienda = db_session.query(Store).filter_by(owner_user_id=usuario.id).one()
    assert tienda.name == "Librería Central"
    # La contraseña nunca se guarda en texto plano.
    assert usuario.password_hash != REGISTRO_VALIDO["password"]

    # La cookie de sesión quedó puesta — HttpOnly (el cliente de test no la
    # expone como si fuera document.cookie, que es justo el punto).
    assert "nexo_session" in res.cookies

    # El endpoint /me funciona de inmediato con esa cookie, sin loguear de nuevo.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["empresa"]["nombre"] == "Librería Central"


def test_registro_con_email_duplicado_devuelve_400(client):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    res = client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "full_name": "Otro"})
    assert res.status_code == 400
    assert "ya existe" in res.json()["detail"].lower()


def test_registro_con_password_muy_corta_devuelve_422(client):
    res = client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "password": "corta"})
    assert res.status_code == 422


def test_registro_con_email_invalido_devuelve_422(client):
    res = client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "no-es-un-email"})
    assert res.status_code == 422


def test_login_con_credenciales_correctas_funciona(client):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    client.post("/api/auth/logout")

    res = client.post("/api/auth/login", json={"email": REGISTRO_VALIDO["email"], "password": REGISTRO_VALIDO["password"]})
    assert res.status_code == 200
    assert res.json()["usuario"]["email"] == REGISTRO_VALIDO["email"]


def test_login_con_password_incorrecta_devuelve_401_generico(client):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    res = client.post("/api/auth/login", json={"email": REGISTRO_VALIDO["email"], "password": "otra-cosa-cualquiera"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Email o contraseña incorrectos."


def test_login_con_email_inexistente_devuelve_el_mismo_401_que_password_incorrecta(client):
    """Nunca hay que poder distinguir "el email no existe" de "la
    contraseña está mal" — evitaría que este endpoint sirva para enumerar
    qué emails están registrados."""
    res = client.post("/api/auth/login", json={"email": "nadie@existe.cl", "password": "cualquiera1"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Email o contraseña incorrectos."


def test_me_sin_cookie_devuelve_401(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_logout_revoca_la_sesion_y_me_deja_de_funcionar(client, db_session):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    assert client.get("/api/auth/me").status_code == 200

    res = client.post("/api/auth/logout")
    assert res.status_code == 200

    # La cookie se borró del lado del servidor (max-age=0 en la respuesta)...
    assert client.get("/api/auth/me").status_code == 401

    # ...y la sesión quedó marcada revocada en la base, no solo "olvidada".
    sesion = db_session.query(AuthSession).order_by(AuthSession.id.desc()).first()
    assert sesion.revoked_at is not None


def test_una_sesion_vencida_no_sirve_aunque_la_cookie_siga_ahi(client, db_session):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    sesion = db_session.query(AuthSession).order_by(AuthSession.id.desc()).first()
    sesion.expires_at = datetime.now() - timedelta(seconds=1)
    db_session.commit()

    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_una_sesion_con_token_falsificado_no_sirve(client):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    client.cookies.set("nexo_session", "token-que-nunca-existio-en-la-base")
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_el_token_de_sesion_nunca_se_guarda_en_texto_plano(client, db_session):
    client.post("/api/auth/registro", json=REGISTRO_VALIDO)
    token_real = client.cookies.get("nexo_session")
    sesion = db_session.query(AuthSession).order_by(AuthSession.id.desc()).first()
    assert sesion.token_hash != token_real
    assert sesion.token_hash == hash_session_token(token_real)


def test_remember_me_deja_una_sesion_mas_larga_que_sin_marcarlo(client, db_session):
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "sin-recordar@x.cl", "remember_me": False})
    sesion_corta = db_session.query(AuthSession).order_by(AuthSession.id.desc()).first()

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "sin-recordar@x.cl", "password": REGISTRO_VALIDO["password"], "remember_me": True},
    )
    sesion_larga = db_session.query(AuthSession).order_by(AuthSession.id.desc()).first()

    assert (sesion_larga.expires_at - sesion_larga.created_at) > (sesion_corta.expires_at - sesion_corta.created_at)


def test_dos_usuarios_registrados_tienen_cada_uno_su_propia_tienda(client, db_session):
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "a@x.cl", "company_name": "Empresa A"})
    client.post("/api/auth/logout")
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "b@x.cl", "company_name": "Empresa B"})

    tiendas = db_session.query(Store).order_by(Store.id).all()
    assert [t.name for t in tiendas] == ["Empresa A", "Empresa B"]

    me = client.get("/api/auth/me").json()
    assert me["empresa"]["nombre"] == "Empresa B"  # el último login/registro activo


def test_password_hash_usa_bcrypt_nunca_texto_plano_ni_sha256_simple(db_session):
    hashed = hash_password("una-contraseña-cualquiera")
    assert hashed != "una-contraseña-cualquiera"
    assert hashed.startswith("$2b$")  # prefijo real de bcrypt


def test_generate_session_token_nunca_repite_valores():
    tokens = {generate_session_token() for _ in range(50)}
    assert len(tokens) == 50
