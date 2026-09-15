"""
Pruebas end-to-end de /api/google-sheets/* — cliente HTTP real de FastAPI,
SQLite en memoria vía dependency_override, y la API de Google (OAuth +
Sheets) mockeada con respx (nunca se llama a la red real ni se usan
credenciales reales). Mismo patrón que tests/test_mercadolibre_endpoints.py.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import MarketplaceAccount, Product, ProductVariant, Store, StoreSettings, User
from app.db.session import get_db
from app.domain.security import hash_password
from app.domain.token_crypto import decrypt_token, encrypt_token
from app.main import app
from tests.auth_helpers import autenticar

NOW = datetime(2026, 9, 5, 12, 0, 0)
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

CONFIGURED_SETTINGS = Settings(
    google_client_id="test-google-client-id",
    google_client_secret="test-google-client-secret",
    google_redirect_uri="http://localhost:8000/api/google-sheets/callback",
    token_encryption_key=TEST_ENCRYPTION_KEY,
)
# Vacío A PROPÓSITO, sin importar qué haya en el backend/.env real del
# desarrollador — mismo criterio que test_mercadolibre_endpoints.py.
UNCONFIGURED_SETTINGS = Settings(
    google_client_id="",
    google_client_secret="",
    google_redirect_uri="",
    token_encryption_key="",
)

SPREADSHEET_ID = "1AbC-Spreadsheet-De-Prueba"


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


def _crear_tienda(db_session, *, nombre="Tienda de prueba", email="tienda@ejemplo.cl"):
    usuario = User(email=email, password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name=nombre, created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name=nombre, store_name=nombre))
    db_session.commit()
    return usuario, tienda


@pytest.fixture()
def a_store(client, db_session):
    usuario, tienda = _crear_tienda(db_session)
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    return tienda


def _state_de(authorization_url):
    return parse_qs(urlparse(authorization_url).query)["state"][0]


def _redirect_params(response):
    location = response.headers["location"]
    return parse_qs(urlparse(location).query)


def _mock_token_exchange(*, access_token="access-real", refresh_token="refresh-real", expires_in=3600):
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": access_token, "refresh_token": refresh_token, "expires_in": expires_in, "token_type": "Bearer", "scope": "https://www.googleapis.com/auth/spreadsheets.readonly"},
        )
    )


def _mock_metadata(spreadsheet_id, *, titulo="Catálogo Tienda", hojas=("Hoja1",)):
    respx.get(url__regex=rf"https://sheets\.googleapis\.com/v4/spreadsheets/{spreadsheet_id}\?.*").mock(
        return_value=httpx.Response(
            200,
            json={"properties": {"title": titulo}, "sheets": [{"properties": {"title": h, "sheetId": i}} for i, h in enumerate(hojas)]},
        )
    )


def _mock_values(spreadsheet_id, hoja, values):
    respx.get(url__regex=rf"https://sheets\.googleapis\.com/v4/spreadsheets/{spreadsheet_id}/values/{hoja}\?.*").mock(
        return_value=httpx.Response(200, json={"values": values})
    )


# ------------------------------------------------------------------
# Conexión OAuth
# ------------------------------------------------------------------


def test_estado_sin_conexion_ni_credenciales(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: UNCONFIGURED_SETTINGS)
    body = client.get("/api/google-sheets/estado").json()
    assert body["conectado"] is False
    assert body["credencialesConfiguradas"] is False


def test_conectar_sin_credenciales_no_le_filtra_la_configuracion_al_cliente(client, a_store, monkeypatch):
    """Mismo criterio que mercadolibre.py y pagos.py (13 de septiembre de
    2026): el detalle operativo va al log del servidor, nunca al cliente."""
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: UNCONFIGURED_SETTINGS)
    res = client.get("/api/google-sheets/conectar")
    assert res.status_code == 400
    detalle = res.json()["detail"]
    assert "Google Sheets todavía no está habilitada" in detalle
    for secreto in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY", ".env"):
        assert secreto not in detalle


def test_conectar_con_credenciales_devuelve_la_url_de_autorizacion_real(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/google-sheets/conectar")
    assert res.status_code == 200
    url = res.json()["authorizationUrl"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-google-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url
    scope = parse_qs(urlparse(url).query)["scope"][0]
    # El único scope — nunca uno de Google Drive (ver adapters/google_sheets.py).
    assert scope == "https://www.googleapis.com/auth/spreadsheets.readonly"


def test_endpoints_requieren_sesion(client):
    assert client.get("/api/google-sheets/estado").status_code == 401
    assert client.get("/api/google-sheets/conectar").status_code == 401
    assert client.post("/api/google-sheets/desconectar").status_code == 401


def test_callback_con_state_invalido_redirige_al_frontend_con_error(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/google-sheets/callback", params={"code": "x", "state": "no-existe"}, follow_redirects=False)
    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["gs"] == ["error"]
    assert params["razon"] == ["estado_invalido"]
    assert res.headers["location"].startswith(CONFIGURED_SETTINGS.frontend_base_url)


def test_callback_con_error_de_autorizacion_redirige_sin_romper(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    state = _state_de(client.get("/api/google-sheets/conectar").json()["authorizationUrl"])
    res = client.get(
        "/api/google-sheets/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["gs"] == ["error"]
    assert params["razon"] == ["rechazado"]


@respx.mock
def test_conectar_y_callback_guardan_los_tokens_cifrados(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_token_exchange(access_token="ACCESS-real", refresh_token="REFRESH-real")

    authorization_url = client.get("/api/google-sheets/conectar").json()["authorizationUrl"]
    state = _state_de(authorization_url)

    res = client.get("/api/google-sheets/callback", params={"code": "codigo-real", "state": state}, follow_redirects=False)

    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["gs"] == ["conectado"]
    assert "ACCESS-real" not in res.headers["location"]
    assert "token" not in res.headers["location"]

    cuenta = db_session.query(MarketplaceAccount).filter_by(store_id=a_store.id, marketplace="google_sheets").one()
    assert cuenta.status == "connected"
    assert cuenta.access_token_encrypted != "ACCESS-real"
    assert decrypt_token(cuenta.access_token_encrypted, TEST_ENCRYPTION_KEY) == "ACCESS-real"
    assert decrypt_token(cuenta.refresh_token_encrypted, TEST_ENCRYPTION_KEY) == "REFRESH-real"


@respx.mock
def test_callback_sin_refresh_token_no_guarda_una_conexion_rota(client, db_session, a_store, monkeypatch):
    """Si Google no manda refresh_token (no debería pasar con
    access_type=offline+prompt=consent, pero si pasara), la conexión no
    puede renovarse sola en ~1 hora — nunca se guarda a medias."""
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "solo-access", "expires_in": 3600, "token_type": "Bearer"})
    )
    state = _state_de(client.get("/api/google-sheets/conectar").json()["authorizationUrl"])

    res = client.get("/api/google-sheets/callback", params={"code": "codigo-real", "state": state}, follow_redirects=False)

    assert _redirect_params(res)["razon"] == ["sin_refresh_token"]
    assert db_session.query(MarketplaceAccount).filter_by(store_id=a_store.id, marketplace="google_sheets").first() is None


@respx.mock
def test_callback_con_code_invalido_redirige_con_error(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    state = _state_de(client.get("/api/google-sheets/conectar").json()["authorizationUrl"])
    res = client.get("/api/google-sheets/callback", params={"code": "vencido", "state": state}, follow_redirects=False)
    assert _redirect_params(res)["razon"] == ["conexion_fallida"]


def test_desconectar_sin_conexion_previa_no_falla(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/google-sheets/desconectar")
    assert res.status_code == 200
    assert res.json()["conectado"] is False


@pytest.fixture()
def cuenta_conectada(db_session, a_store):
    cuenta = MarketplaceAccount(
        store=a_store,
        marketplace="google_sheets",
        status="connected",
        access_token_encrypted=encrypt_token("token-valido", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-valido", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2027, 1, 1),
        connected_at=NOW,
        last_checked_at=NOW,
    )
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


@pytest.fixture()
def cuenta_vinculada(db_session, cuenta_conectada):
    """Ya conectada Y con una spreadsheet+hoja elegidas — el estado en el
    que hace falta estar para poder analizar/confirmar una importación."""
    cuenta_conectada.external_account_id = SPREADSHEET_ID
    cuenta_conectada.external_account_nickname = "Catálogo Tienda"
    cuenta_conectada.external_account_site_id = "Hoja1"
    db_session.commit()
    return cuenta_conectada


def test_desconectar_limpia_la_conexion_y_la_hoja_vinculada(client, db_session, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/google-sheets/desconectar")
    assert res.status_code == 200
    body = res.json()
    assert body["conectado"] is False
    assert body["spreadsheetId"] is None

    cuenta = db_session.get(MarketplaceAccount, cuenta_vinculada.id)
    assert cuenta.status == "not_connected"
    assert cuenta.access_token_encrypted is None
    assert cuenta.external_account_id is None
    assert cuenta.external_account_site_id is None


# ------------------------------------------------------------------
# Vincular una hoja de cálculo
# ------------------------------------------------------------------


@respx.mock
def test_vincular_hoja_sin_conexion_devuelve_400(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/google-sheets/hoja", json={"url": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"})
    assert res.status_code == 400
    assert "no está conectado" in res.json()["detail"]


@respx.mock
def test_vincular_hoja_con_una_sola_pestana_la_preselecciona(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_metadata(SPREADSHEET_ID, titulo="Catálogo Tienda", hojas=("Hoja1",))

    res = client.post("/api/google-sheets/hoja", json={"url": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid=0"})

    assert res.status_code == 200
    body = res.json()
    assert body["spreadsheetId"] == SPREADSHEET_ID
    assert body["titulo"] == "Catálogo Tienda"
    assert body["hojas"] == ["Hoja1"]
    assert body["hojaSeleccionada"] == "Hoja1"

    cuenta = db_session.get(MarketplaceAccount, cuenta_conectada.id)
    assert cuenta.external_account_id == SPREADSHEET_ID
    assert cuenta.external_account_nickname == "Catálogo Tienda"
    assert cuenta.external_account_site_id == "Hoja1"


@respx.mock
def test_vincular_hoja_con_varias_pestanas_no_preselecciona_ninguna(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_metadata(SPREADSHEET_ID, hojas=("Enero", "Febrero"))

    res = client.post("/api/google-sheets/hoja", json={"url": SPREADSHEET_ID})

    assert res.status_code == 200
    body = res.json()
    assert body["hojas"] == ["Enero", "Febrero"]
    assert body["hojaSeleccionada"] is None


@respx.mock
def test_vincular_hoja_inexistente_da_mensaje_entendible(client, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=r"https://sheets\.googleapis\.com/v4/spreadsheets/no-existe\?.*").mock(
        return_value=httpx.Response(404, json={"error": {"code": 404, "message": "Requested entity was not found."}})
    )

    res = client.post("/api/google-sheets/hoja", json={"url": "no-existe"})

    assert res.status_code == 400
    assert "no encontramos" in res.json()["detail"].lower()
    # Nunca el JSON técnico crudo de Google en la respuesta.
    assert "Requested entity" not in res.json()["detail"]


# ------------------------------------------------------------------
# Analizar e importar filas — reutiliza detect_columns/build_rows
# (mismo comportamiento exacto que /api/catalogo/importar/*)
# ------------------------------------------------------------------

FILAS_LIBRERIA = [
    ["SKU", "Nombre", "Marca", "Categoría", "Precio", "Costo", "Stock", "Descripción", "Imagen"],
    ["LIB-001", "Cuaderno universitario", "Torre", "Cuadernos", 3990, 2000, 25, "Cuaderno 100 hojas", "http://cdn.test/cuaderno.png"],
    ["LIB-002", "Lápiz grafito HB", "Faber", "Papelería", 690, 300, 120, "", ""],
]

FILAS_CON_ERRORES = [
    ["SKU", "Nombre", "Precio"],
    ["", "", "no-es-un-numero"],  # sin nombre, precio inválido -> bloqueante (error)
    ["LIB-010", "Goma de borrar", 500],  # válida
]


@respx.mock
def test_analizar_sin_hoja_vinculada_devuelve_400(client, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/google-sheets/importar/analizar", json={})
    assert res.status_code == 400
    assert "vincul" in res.json()["detail"].lower()


@respx.mock
def test_analizar_hoja_detecta_columnas_y_valida_filas(client, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_values(SPREADSHEET_ID, "Hoja1", FILAS_LIBRERIA)

    res = client.post("/api/google-sheets/importar/analizar", json={})

    assert res.status_code == 200
    body = res.json()
    assert body["hojaUsada"] == "Hoja1"
    assert body["spreadsheetTitulo"] == "Catálogo Tienda"
    assert body["mapeoPropuesto"]["sku"] == "SKU"
    assert body["mapeoPropuesto"]["nombre"] == "Nombre"
    assert body["mapeoPropuesto"]["precio"] == "Precio"
    assert body["resumen"]["totalFilas"] == 2
    # LIB-001 trae TODOS los campos -> válido. LIB-002 no trae descripción ni
    # imagen, pero sí costo, precio y stock -> también válido: desde el
    # 15/09/2026 la falta de imagen es un aviso informativo, no deja la fila en
    # revisión (ver PROBLEMAS_INFORMATIVOS en app/domain/catalog_import.py).
    assert body["resumen"]["validos"] == 2
    assert body["resumen"]["revision"] == 0


@respx.mock
def test_analizar_hoja_con_filas_invalidas_las_marca_sin_bloquear_las_demas(client, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_values(SPREADSHEET_ID, "Hoja1", FILAS_CON_ERRORES)

    res = client.post("/api/google-sheets/importar/analizar", json={})

    assert res.status_code == 200
    body = res.json()
    filas_por_estado = {f["estado"] for f in body["filas"]}
    assert "error" in filas_por_estado  # fila sin nombre / precio inválido
    fila_valida = next(f for f in body["filas"] if f["sku"] == "LIB-010")
    # No es "error" (nombre y precio están bien) — queda en "revisión" por
    # los campos opcionales que esa hoja no trae (categoría, descripción,
    # imagen, costo), igual que un Excel/CSV con las mismas columnas.
    assert fila_valida["estado"] == "revision"


@respx.mock
def test_analizar_hoja_inexistente_en_esa_spreadsheet_da_mensaje_entendible(client, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=rf"https://sheets\.googleapis\.com/v4/spreadsheets/{SPREADSHEET_ID}/values/HojaQueNoExiste\?.*").mock(
        return_value=httpx.Response(400, json={"error": {"message": "Unable to parse range"}})
    )

    res = client.post("/api/google-sheets/importar/analizar", json={"hoja": "HojaQueNoExiste"})

    assert res.status_code == 400
    assert "no existe" in res.json()["detail"].lower()


@respx.mock
def test_confirmar_crea_productos_reales_desde_google_sheets(client, db_session, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_values(SPREADSHEET_ID, "Hoja1", FILAS_LIBRERIA)

    mapeo = {
        "sku": "SKU", "nombre": "Nombre", "marca": "Marca", "categoria": "Categoría",
        "precio": "Precio", "costo": "Costo", "stock": "Stock", "descripcion": "Descripción",
        "imagen_url": "Imagen", "codigo_barras": None,
    }
    res = client.post("/api/google-sheets/importar/confirmar", json={"mapeo": mapeo})

    assert res.status_code == 200
    body = res.json()
    assert body["creados"] == 2
    assert body["omitidos"] == 0

    productos = db_session.query(Product).filter_by(store_id=a_store.id).all()
    assert len(productos) == 2
    assert {p.source for p in productos} == {"google_sheets"}
    variante = db_session.query(ProductVariant).filter_by(store_id=a_store.id, variant_sku="LIB-001").one()
    assert variante.price == 3990
    assert variante.cost_price == 2000


@respx.mock
def test_empresa_nueva_sin_productos_importa_su_primer_catalogo(client, db_session, a_store, cuenta_vinculada, monkeypatch):
    """Caso explícito del pedido: una empresa recién creada, sin ningún
    producto todavía, importa desde Google Sheets sin fricción."""
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    assert db_session.query(Product).filter_by(store_id=a_store.id).count() == 0
    _mock_values(SPREADSHEET_ID, "Hoja1", FILAS_LIBRERIA)

    analisis = client.post("/api/google-sheets/importar/analizar", json={}).json()
    res = client.post(
        "/api/google-sheets/importar/confirmar",
        json={"mapeo": analisis["mapeoPropuesto"]},
    )

    assert res.status_code == 200
    assert res.json()["creados"] == 2
    assert db_session.query(Product).filter_by(store_id=a_store.id).count() == 2


@respx.mock
def test_reimportar_el_mismo_sku_actualiza_en_vez_de_duplicar(client, db_session, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    _mock_values(SPREADSHEET_ID, "Hoja1", FILAS_LIBRERIA)
    mapeo = {"sku": "SKU", "nombre": "Nombre", "marca": "Marca", "categoria": "Categoría", "precio": "Precio", "costo": "Costo", "stock": "Stock", "descripcion": "Descripción", "imagen_url": "Imagen", "codigo_barras": None}
    client.post("/api/google-sheets/importar/confirmar", json={"mapeo": mapeo})

    # "Volver a sincronizar": no hace falta volver a mandar `hoja` — usa la
    # última vinculada (cuenta.external_account_site_id).
    res = client.post("/api/google-sheets/importar/confirmar", json={"mapeo": mapeo})

    assert res.status_code == 200
    assert res.json()["creados"] == 0
    assert res.json()["actualizados"] == 2
    assert db_session.query(Product).filter_by(store_id=a_store.id).count() == 2


# ------------------------------------------------------------------
# Aislamiento multiempresa
# ------------------------------------------------------------------


@respx.mock
def test_empresa_b_no_ve_ni_puede_usar_la_conexion_de_empresa_a(client, db_session, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)

    usuario_b, tienda_b = _crear_tienda(db_session, nombre="Empresa B", email="b@empresas.cl")
    autenticar(client, db_session, usuario_b, tienda_b, ahora=NOW)  # el client ahora es la sesión de B

    estado_b = client.get("/api/google-sheets/estado").json()
    assert estado_b["conectado"] is False
    assert estado_b["spreadsheetId"] is None

    # B ni siquiera puede analizar (no tiene conexión propia) — nunca hereda
    # la de A por accidente.
    res = client.post("/api/google-sheets/importar/analizar", json={})
    assert res.status_code == 400

    # La cuenta real de A en la base sigue intacta y separada por store_id.
    de_a = db_session.query(MarketplaceAccount).filter_by(store_id=a_store.id, marketplace="google_sheets").one()
    assert de_a.external_account_id == SPREADSHEET_ID
    de_b = db_session.query(MarketplaceAccount).filter_by(store_id=tienda_b.id, marketplace="google_sheets").first()
    assert de_b is None


@respx.mock
def test_desconectar_empresa_a_no_afecta_la_conexion_de_empresa_b(client, db_session, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)

    usuario_b, tienda_b = _crear_tienda(db_session, nombre="Empresa B", email="b2@empresas.cl")
    cuenta_b = MarketplaceAccount(
        store=tienda_b, marketplace="google_sheets", status="connected",
        external_account_id="OTRA-SPREADSHEET", external_account_nickname="Catálogo de B",
        access_token_encrypted=encrypt_token("token-de-b", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-de-b", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2027, 1, 1), connected_at=NOW, last_checked_at=NOW,
    )
    db_session.add(cuenta_b)
    db_session.commit()

    res = client.post("/api/google-sheets/desconectar")
    assert res.status_code == 200
    assert res.json()["conectado"] is False

    de_b = db_session.get(MarketplaceAccount, cuenta_b.id)
    assert de_b.status == "connected"
    assert de_b.external_account_id == "OTRA-SPREADSHEET"
    assert decrypt_token(de_b.access_token_encrypted, TEST_ENCRYPTION_KEY) == "token-de-b"


def test_la_cuenta_de_google_sheets_esta_scopeada_por_tienda_no_es_global(db_session):
    _usuario_a, tienda_a = _crear_tienda(db_session, nombre="Tienda A", email="a3@empresas.cl")
    _usuario_b, tienda_b = _crear_tienda(db_session, nombre="Tienda B", email="b3@empresas.cl")

    cuenta_a = MarketplaceAccount(store=tienda_a, marketplace="google_sheets", status="connected", external_account_id="SS-A")
    cuenta_b = MarketplaceAccount(store=tienda_b, marketplace="google_sheets", status="not_connected")
    db_session.add_all([cuenta_a, cuenta_b])
    db_session.commit()

    de_a = db_session.query(MarketplaceAccount).filter_by(store_id=tienda_a.id, marketplace="google_sheets").one()
    de_b = db_session.query(MarketplaceAccount).filter_by(store_id=tienda_b.id, marketplace="google_sheets").one()
    assert de_a.external_account_id == "SS-A"
    assert de_b.status == "not_connected"


def test_estado_nunca_expone_tokens_ni_client_secret(client, a_store, cuenta_vinculada, monkeypatch):
    monkeypatch.setattr("app.api.routes.google_sheets.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/google-sheets/estado")
    assert res.status_code == 200
    cuerpo_crudo = res.text
    assert "token-valido" not in cuerpo_crudo
    assert "refresh-valido" not in cuerpo_crudo
    assert CONFIGURED_SETTINGS.google_client_secret not in cuerpo_crudo
    assert "access_token" not in res.json()
    assert "refresh_token" not in res.json()
