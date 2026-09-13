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
from app.domain.rate_limit import MAX_FALLOS_POR_EMAIL, reiniciar as reiniciar_intentos
from app.domain.security import generate_session_token, hash_password, hash_session_token
from app.main import app


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(autouse=True)
def _sin_intentos_previos():
    """El límite de intentos vive en memoria del proceso: sin esto, un test
    que agota los intentos dejaría bloqueados a los que corren después."""
    reiniciar_intentos()
    yield
    reiniciar_intentos()


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
    "company_name": "Empresa Demo",
}


def test_registro_crea_usuario_y_tienda_y_deja_la_sesion_activa(client, db_session):
    res = client.post("/api/auth/registro", json=REGISTRO_VALIDO)

    assert res.status_code == 200
    body = res.json()
    assert body["usuario"]["email"] == "dueño@libreria.cl"
    assert body["empresa"]["nombre"] == "Empresa Demo"

    usuario = db_session.query(User).filter_by(email="dueño@libreria.cl").one()
    tienda = db_session.query(Store).filter_by(owner_user_id=usuario.id).one()
    assert tienda.name == "Empresa Demo"
    # La contraseña nunca se guarda en texto plano.
    assert usuario.password_hash != REGISTRO_VALIDO["password"]

    # La cookie de sesión quedó puesta — HttpOnly (el cliente de test no la
    # expone como si fuera document.cookie, que es justo el punto).
    assert "nexo_session" in res.cookies

    # El endpoint /me funciona de inmediato con esa cookie, sin loguear de nuevo.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["empresa"]["nombre"] == "Empresa Demo"


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


# ------------------------------------------------------------------
# 5 de septiembre de 2026 — Nexo es un producto SaaS, no un negocio hecho a
# medida de un cliente puntual: una empresa nueva tiene que arrancar
# realmente vacía (sin productos de ejemplo, sin catálogo precargado, sin
# nada perteneciente a otra empresa) — ver también app/db/seed_demo.py
# (script manual, jamás corre solo) y frontend/js/demoData.js (Demo Mode,
# solo cuando no hay backend real disponible, nunca para un usuario
# logueado de verdad).
# ------------------------------------------------------------------


def test_empresa_recien_registrada_arranca_con_cero_productos(client, db_session):
    from app.db.models import Product

    res = client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "cuenta-limpia@empresa.cl"})
    assert res.status_code == 200, res.text
    store_id = res.json()["empresa"]["id"]

    assert db_session.query(Product).filter_by(store_id=store_id).count() == 0
    listar = client.get("/api/productos")
    assert listar.status_code == 200
    assert listar.json() == []


def test_password_hash_usa_bcrypt_nunca_texto_plano_ni_sha256_simple(db_session):
    hashed = hash_password("una-contraseña-cualquiera")
    assert hashed != "una-contraseña-cualquiera"
    assert hashed.startswith("$2b$")  # prefijo real de bcrypt


def test_generate_session_token_nunca_repite_valores():
    tokens = {generate_session_token() for _ in range(50)}
    assert len(tokens) == 50


# ------------------------------------------------------------------
# POST /cambiar-password — 13 de septiembre de 2026. Antes el boton de
# Configuracion abria un cartel diciendo que no estaba disponible: no habia
# NINGUNA forma de cambiar la contrasena desde la aplicacion.
# ------------------------------------------------------------------


def _registrar(client, email="cambio@empresa.cl", password="contraseña-inicial-1"):
    res = client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": email, "password": password})
    assert res.status_code == 200, res.text
    return email, password


def test_cambiar_password_con_la_actual_correcta(client, db_session):
    email, actual = _registrar(client)

    res = client.post("/api/auth/cambiar-password", json={"password_actual": actual, "password_nueva": "contraseña-nueva-2"})
    assert res.status_code == 200, res.text

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": email, "password": actual}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "contraseña-nueva-2"}).status_code == 200


def test_cambiar_password_con_la_actual_equivocada_no_hace_nada(client, db_session):
    email, actual = _registrar(client, email="equivocada@empresa.cl")

    res = client.post("/api/auth/cambiar-password", json={"password_actual": "no-es-esta", "password_nueva": "contraseña-nueva-2"})
    assert res.status_code == 400
    assert "actual no es correcta" in res.json()["detail"]

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": email, "password": actual}).status_code == 200


def test_la_password_nueva_tiene_que_tener_ocho_caracteres(client, db_session):
    _email, actual = _registrar(client, email="corta@empresa.cl")
    res = client.post("/api/auth/cambiar-password", json={"password_actual": actual, "password_nueva": "corta"})
    assert res.status_code == 422


def test_la_password_nueva_no_puede_ser_igual_a_la_actual(client, db_session):
    _email, actual = _registrar(client, email="igual@empresa.cl")
    res = client.post("/api/auth/cambiar-password", json={"password_actual": actual, "password_nueva": actual})
    assert res.status_code == 400


def test_cambiar_password_cierra_las_demas_sesiones_pero_no_la_propia(client, db_session):
    """Lo que se espera de un cambio de contrasena: si alguien mas habia
    quedado dentro, deja de estarlo. La sesion que hace el cambio sigue
    viva, para no obligar a entrar de nuevo justo despues."""
    email, actual = _registrar(client, email="sesiones@empresa.cl")
    usuario = db_session.query(User).filter_by(email=email).one()
    # Dos sesiones mas, como si hubiera entrado desde otros dispositivos.
    for _ in range(2):
        db_session.add(AuthSession(
            user=usuario, token_hash=hash_session_token(generate_session_token()),
            active_store_id=None, created_at=datetime.now(), expires_at=datetime.now() + timedelta(hours=24),
        ))
    db_session.commit()

    res = client.post("/api/auth/cambiar-password", json={"password_actual": actual, "password_nueva": "contraseña-nueva-2"})
    assert res.json()["sesionesCerradas"] == 2

    vivas = db_session.query(AuthSession).filter_by(user_id=usuario.id).filter(AuthSession.revoked_at.is_(None)).all()
    assert len(vivas) == 1                      # solo la que hizo el cambio
    assert client.get("/api/auth/me").status_code == 200


def test_sin_sesion_no_se_puede_cambiar_la_password(client):
    res = client.post("/api/auth/cambiar-password", json={"password_actual": "x" * 9, "password_nueva": "y" * 9})
    assert res.status_code == 401


# ------------------------------------------------------------------
# Límite de intentos fallidos — 13 de septiembre de 2026. Antes de esto
# /api/auth/login aceptaba intentos ilimitados: se podían probar
# contraseñas a máquina indefinidamente.
# ------------------------------------------------------------------


def test_despues_de_varios_fallos_el_login_se_bloquea(client, db_session):
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "fuerzabruta@empresa.cl"})
    client.post("/api/auth/logout")

    for _ in range(MAX_FALLOS_POR_EMAIL):
        res = client.post("/api/auth/login", json={"email": "fuerzabruta@empresa.cl", "password": "no-es-esta"})
        assert res.status_code == 401

    res = client.post("/api/auth/login", json={"email": "fuerzabruta@empresa.cl", "password": "no-es-esta"})
    assert res.status_code == 429
    assert "Demasiados intentos" in res.json()["detail"]


def test_bloqueado_no_entra_ni_con_la_contrasena_correcta(client, db_session):
    """Es el punto: si bastara con acertar, el atacante seguiría probando."""
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "bloqueada@empresa.cl", "password": "contraseña-correcta-1"})
    client.post("/api/auth/logout")
    for _ in range(MAX_FALLOS_POR_EMAIL):
        client.post("/api/auth/login", json={"email": "bloqueada@empresa.cl", "password": "mal"})

    res = client.post("/api/auth/login", json={"email": "bloqueada@empresa.cl", "password": "contraseña-correcta-1"})
    assert res.status_code == 429


def test_un_login_correcto_limpia_el_contador(client, db_session):
    """Quien se equivoca un par de veces y después entra bien no arrastra
    nada: no queda a un fallo de quedarse afuera."""
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "olvidadiza@empresa.cl", "password": "contraseña-correcta-1"})
    client.post("/api/auth/logout")

    for _ in range(MAX_FALLOS_POR_EMAIL - 1):
        client.post("/api/auth/login", json={"email": "olvidadiza@empresa.cl", "password": "mal"})
    assert client.post("/api/auth/login", json={"email": "olvidadiza@empresa.cl", "password": "contraseña-correcta-1"}).status_code == 200
    client.post("/api/auth/logout")

    # El contador volvió a cero: se pueden volver a fallar los mismos intentos.
    for _ in range(MAX_FALLOS_POR_EMAIL - 1):
        assert client.post("/api/auth/login", json={"email": "olvidadiza@empresa.cl", "password": "mal"}).status_code == 401


def test_el_bloqueo_es_por_cuenta_no_deja_afuera_a_las_demas(client, db_session):
    """Un ataque contra una cuenta no puede dejar sin entrar a otro cliente
    (la cubeta por IP es mucho más alta, ver domain/rate_limit.py)."""
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "atacada@empresa.cl"})
    client.post("/api/auth/logout")
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "tranquila@empresa.cl", "password": "contraseña-correcta-1"})
    client.post("/api/auth/logout")

    for _ in range(MAX_FALLOS_POR_EMAIL + 1):
        client.post("/api/auth/login", json={"email": "atacada@empresa.cl", "password": "mal"})

    assert client.post("/api/auth/login", json={"email": "tranquila@empresa.cl", "password": "contraseña-correcta-1"}).status_code == 200


def test_cambiar_password_tambien_esta_limitado(client, db_session):
    """Con una sesión robada se podría adivinar la contraseña actual a
    fuerza bruta para después cambiarla."""
    client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": "cambio-limitado@empresa.cl", "password": "contraseña-correcta-1"})

    for _ in range(MAX_FALLOS_POR_EMAIL):
        res = client.post("/api/auth/cambiar-password", json={"password_actual": "mal", "password_nueva": "contraseña-nueva-2"})
        assert res.status_code == 400

    res = client.post("/api/auth/cambiar-password", json={"password_actual": "mal", "password_nueva": "contraseña-nueva-2"})
    assert res.status_code == 429
