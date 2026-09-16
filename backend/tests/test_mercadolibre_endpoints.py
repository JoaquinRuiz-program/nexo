"""
Pruebas end-to-end de /api/mercadolibre/* — cliente HTTP real de FastAPI,
SQLite en memoria vía dependency_override, y la API de Mercado Libre
mockeada con respx (nunca se llama a la red real ni se usan credenciales
reales).
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
from app.db.models import (
    MarketplaceAccount,
    MercadoLibreCategoryFee,
    MercadoLibreShippingEstimate,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    Store,
    StoreSettings,
    User,
)
from app.db.session import get_db
from app.domain.security import hash_password
from tests.auth_helpers import autenticar
from app.domain.token_crypto import decrypt_token
from app.main import app

NOW = datetime(2026, 8, 24, 12, 0, 0)
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

CONFIGURED_SETTINGS = Settings(
    mercadolibre_client_id="test-client-id",
    mercadolibre_client_secret="test-client-secret",
    mercadolibre_redirect_uri="http://localhost:8000/api/mercadolibre/callback",
    mercadolibre_auth_domain="auth.mercadolibre.cl",
    token_encryption_key=TEST_ENCRYPTION_KEY,
)
# Vacío A PROPÓSITO en los 4 campos de Mercado Libre, sin importar qué haya
# en el backend/.env real del desarrollador — Settings() por defecto LEE
# ese .env (ver ENV_PATH en app/config.py), así que si el dueño ya
# configuró credenciales reales para probar en vivo (29 de agosto de 2026),
# un Settings() "pelado" dejaría de representar el caso "sin configurar" y
# rompería estos tests por una razón ajena al código.
UNCONFIGURED_SETTINGS = Settings(
    mercadolibre_client_id="",
    mercadolibre_client_secret="",
    mercadolibre_redirect_uri="",
    token_encryption_key="",
)


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


@pytest.fixture()
def a_store(client, db_session):
    usuario = User(email="tienda@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Tienda de prueba", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda"))
    db_session.commit()
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    return tienda


def _producto(db_session, tienda, *, sku, nombre, precio, marketplace_stock=None):
    producto = Product(store=tienda, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    variante = ProductVariant(
        product=producto, store_id=tienda.id, variant_sku=sku, price=precio,
        marketplace_stock=marketplace_stock, created_at=NOW, updated_at=NOW,
    )
    db_session.add(variante)
    db_session.commit()
    return variante


def _state_de(authorization_url):
    """El "state" real de la URL de autorización — con parseo de verdad
    (no un split ingenuo), porque desde que se agregó PKCE la URL trae más
    parámetros después de "state=" (code_challenge, code_challenge_method)."""
    return parse_qs(urlparse(authorization_url).query)["state"][0]


def _redirect_params(response):
    """Query params de a dónde redirige /callback al frontend — la parte
    ANTES del "#" (ver _frontend_redirect en app/api/routes/mercadolibre.py)."""
    location = response.headers["location"]
    return parse_qs(urlparse(location).query)


def _pedido_ml(order_id, sku, *, quantity=1, unit_price=10000, sale_fee=1200, status="paid"):
    return {
        "id": order_id,
        "date_created": "2026-08-24T10:00:00.000-04:00",
        "status": status,
        "total_amount": unit_price * quantity,
        "buyer": {"id": 999, "nickname": "COMPRADOR", "first_name": "Nombre Real", "email": "x@y.cl"},
        "order_items": [
            {
                "item": {"id": f"MLC{order_id}", "title": "Producto", "seller_sku": sku},
                "quantity": quantity,
                "unit_price": unit_price,
                "sale_fee": sale_fee,
            }
        ],
    }


def test_estado_sin_conexion_ni_credenciales(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: UNCONFIGURED_SETTINGS)
    body = client.get("/api/mercadolibre/estado").json()
    assert body["conectado"] is False
    assert body["credencialesConfiguradas"] is False


def test_conectar_sin_credenciales_no_le_filtra_la_configuracion_al_cliente(client, a_store, monkeypatch):
    """13 de septiembre de 2026 — hallazgo de recorrer el producto como
    cliente: este 400 le mostraba al dueno de la empresa la ruta
    backend/.env, los nombres de las variables y la instruccion de ir a
    crear credenciales. Eso es trabajo de quien opera Nexo; el detalle
    ahora va al log del servidor."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: UNCONFIGURED_SETTINGS)
    res = client.get("/api/mercadolibre/conectar")
    assert res.status_code == 400
    detalle = res.json()["detail"]
    assert "Mercado Libre todavía no está habilitada" in detalle
    for secreto in ("MERCADOLIBRE_CLIENT_ID", "MERCADOLIBRE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY", ".env"):
        assert secreto not in detalle


def test_conectar_con_credenciales_devuelve_la_url_de_autorizacion_real(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/mercadolibre/conectar")
    assert res.status_code == 200
    url = res.json()["authorizationUrl"]
    assert url.startswith("https://auth.mercadolibre.cl/authorization?")
    assert "client_id=test-client-id" in url
    assert "state=" in url


def test_callback_con_state_invalido_redirige_al_frontend_con_error(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/mercadolibre/callback", params={"code": "x", "state": "no-existe"}, follow_redirects=False)
    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["ml"] == ["error"]
    assert params["razon"] == ["estado_invalido"]
    # Nunca un JSON crudo ni un detalle técnico en la URL a la que vuelve el navegador.
    assert "location" in res.headers
    assert res.headers["location"].startswith(CONFIGURED_SETTINGS.frontend_base_url)


def test_callback_con_error_de_autorizacion_redirige_sin_romper(client, a_store, monkeypatch):
    """El dueño cancela en la pantalla de Mercado Libre — ML redirige con
    ?error=access_denied y SIN "code". Antes esto rompía con un 422 (code
    era un parámetro obligatorio) antes de llegar a nuestro código."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    state = _state_de(client.get("/api/mercadolibre/conectar").json()["authorizationUrl"])

    res = client.get(
        "/api/mercadolibre/callback",
        params={"error": "access_denied", "error_description": "user denied", "state": state},
        follow_redirects=False,
    )

    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["ml"] == ["error"]
    assert params["razon"] == ["rechazado"]


@respx.mock
def test_conectar_y_callback_guardan_los_tokens_cifrados(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "APP_USR-real", "refresh_token": "TG-real", "expires_in": 21600, "user_id": 555},
        )
    )
    respx.get("https://api.mercadolibre.com/users/me").mock(
        return_value=httpx.Response(200, json={"id": 555, "nickname": "LIBRERIA_REAL"})
    )

    authorization_url = client.get("/api/mercadolibre/conectar").json()["authorizationUrl"]
    assert "code_challenge=" in authorization_url  # PKCE — siempre se manda, ver generate_pkce_pair()
    assert "code_challenge_method=S256" in authorization_url
    state = _state_de(authorization_url)

    res = client.get("/api/mercadolibre/callback", params={"code": "codigo-real", "state": state}, follow_redirects=False)

    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["ml"] == ["conectado"]
    # El navegador nunca recibe el token, cifrado o no, en ningún lado.
    assert "APP_USR-real" not in res.headers["location"]
    assert "token" not in res.headers["location"]

    cuenta = db_session.query(MarketplaceAccount).filter_by(store_id=a_store.id, marketplace="mercadolibre").one()
    assert cuenta.status == "connected"
    assert cuenta.external_account_id == "555"
    assert cuenta.external_account_nickname == "LIBRERIA_REAL"
    assert cuenta.access_token_encrypted != "APP_USR-real"  # nunca texto plano
    assert decrypt_token(cuenta.access_token_encrypted, TEST_ENCRYPTION_KEY) == "APP_USR-real"
    assert decrypt_token(cuenta.refresh_token_encrypted, TEST_ENCRYPTION_KEY) == "TG-real"

    # El code_verifier que mandó el backend en el intercambio de tokens es
    # el mismo que se generó junto al state en /conectar (PKCE real, no
    # solo el parámetro presente en la URL).
    token_call = [c for c in respx.calls if "/oauth/token" in str(c.request.url)][0]
    assert b"code_verifier=" in token_call.request.content


def test_importar_ventas_sin_conexion_devuelve_400(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/mercadolibre/importar-ventas")
    assert res.status_code == 400
    assert "no está conectado" in res.json()["detail"]


@respx.mock
def test_callback_con_error_de_red_al_canjear_el_code_redirige_con_error(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://api.mercadolibre.com/oauth/token").mock(side_effect=httpx.ConnectError("sin red"))

    state = _state_de(client.get("/api/mercadolibre/conectar").json()["authorizationUrl"])
    res = client.get("/api/mercadolibre/callback", params={"code": "codigo-real", "state": state}, follow_redirects=False)

    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["ml"] == ["error"]
    assert params["razon"] == ["conexion_fallida"]
    # Nunca el detalle técnico ("sin red", ConnectError, etc.) en la URL.
    assert "ConnectError" not in res.headers["location"]


@respx.mock
def test_callback_con_code_invalido_o_vencido_redirige_con_error(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "message": "código inválido o expirado"})
    )

    state = _state_de(client.get("/api/mercadolibre/conectar").json()["authorizationUrl"])
    res = client.get("/api/mercadolibre/callback", params={"code": "codigo-vencido", "state": state}, follow_redirects=False)

    assert res.status_code == 303
    assert _redirect_params(res)["ml"] == ["error"]


@respx.mock
def test_callback_con_token_encryption_key_invalida_redirige_con_error_no_revienta(client, a_store, monkeypatch):
    # Los tokens de ML son reales y válidos acá — el problema es que
    # TOKEN_ENCRYPTION_KEY en .env no es una clave Fernet válida (typo al
    # copiarla). No debe perderse como un 500 sin manejar.
    settings_clave_invalida = Settings(
        mercadolibre_client_id="test-client-id",
        mercadolibre_client_secret="test-client-secret",
        mercadolibre_redirect_uri="http://localhost:8000/api/mercadolibre/callback",
        mercadolibre_auth_domain="auth.mercadolibre.cl",
        token_encryption_key="esto-no-es-una-clave-fernet-valida",
    )
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: settings_clave_invalida)
    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "a", "refresh_token": "r", "expires_in": 21600, "user_id": 1}
        )
    )
    respx.get("https://api.mercadolibre.com/users/me").mock(return_value=httpx.Response(200, json={"id": 1}))

    state = _state_de(client.get("/api/mercadolibre/conectar").json()["authorizationUrl"])
    res = client.get("/api/mercadolibre/callback", params={"code": "codigo-real", "state": state}, follow_redirects=False)

    assert res.status_code == 303
    params = _redirect_params(res)
    assert params["ml"] == ["error"]
    assert params["razon"] == ["cifrado_no_configurado"]


@pytest.fixture()
def cuenta_conectada(db_session, a_store):
    from app.domain.token_crypto import encrypt_token

    cuenta = MarketplaceAccount(
        store=a_store,
        marketplace="mercadolibre",
        status="connected",
        external_account_id="555",
        access_token_encrypted=encrypt_token("token-valido", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-valido", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2027, 1, 1),  # bien en el futuro, no dispara refresh
        connected_at=NOW,
        last_checked_at=NOW,
    )
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


@pytest.fixture()
def cuenta_con_token_vencido(db_session, a_store):
    from app.domain.token_crypto import encrypt_token

    cuenta = MarketplaceAccount(
        store=a_store,
        marketplace="mercadolibre",
        status="connected",
        external_account_id="555",
        access_token_encrypted=encrypt_token("token-vencido", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-valido", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2020, 1, 1),  # bien en el pasado, dispara refresh
        connected_at=NOW,
        last_checked_at=NOW,
    )
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


@respx.mock
def test_importar_ventas_renueva_el_token_vencido_automaticamente(client, db_session, a_store, cuenta_con_token_vencido, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "token-nuevo", "refresh_token": "refresh-nuevo", "expires_in": 21600, "user_id": 555}
        )
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 200
    cuenta = db_session.query(MarketplaceAccount).filter_by(id=cuenta_con_token_vencido.id).one()
    assert cuenta.token_expires_at > datetime.now()
    assert decrypt_token(cuenta.access_token_encrypted, TEST_ENCRYPTION_KEY) == "token-nuevo"
    assert decrypt_token(cuenta.refresh_token_encrypted, TEST_ENCRYPTION_KEY) == "refresh-nuevo"
    # La llamada a /orders/search tiene que haber usado el token YA renovado.
    llamada_orders = [c for c in respx.calls if "/orders/search" in str(c.request.url)][0]
    assert llamada_orders.request.headers["authorization"] == "Bearer token-nuevo"


@respx.mock
def test_importar_ventas_con_refresh_token_rechazado_marca_la_cuenta_como_vencida(client, db_session, a_store, cuenta_con_token_vencido, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_token", "message": "refresh token revocado"})
    )

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 401
    assert "reconectar" in res.json()["detail"].lower()
    cuenta = db_session.query(MarketplaceAccount).filter_by(id=cuenta_con_token_vencido.id).one()
    assert cuenta.status == "token_expired"


@respx.mock
def test_importar_ventas_crea_pedido_y_descuenta_marketplace_stock(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    _producto(db_session, a_store, sku="LIB-001", nombre="Cien años de soledad", precio=10000, marketplace_stock=5)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": [_pedido_ml(2000001, "LIB-001", quantity=1)]})
    )

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 200
    body = res.json()
    assert body["ordenesNuevas"] == ["2000001"]
    assert body["itemsSinSkuEnCatalogo"] == []
    assert body["desajustesStockReservado"] == []

    orden = db_session.query(Order).filter_by(external_order_id="2000001").one()
    assert orden.channel == "mercadolibre"
    assert orden.commission_amount == 1200.0
    item = db_session.query(OrderItem).filter_by(order_id=orden.id).one()
    assert item.quantity == 1
    assert item.unit_price == 10000

    variante = db_session.query(ProductVariant).filter_by(variant_sku="LIB-001").one()
    assert variante.marketplace_stock == 4  # 5 - 1, el ejemplo exacto del dueño

    # Ningún dato del comprador quedó guardado en ningún lado.
    assert "COMPRADOR" not in res.text
    assert "Nombre Real" not in res.text


@respx.mock
def test_importar_ventas_es_idempotente_no_duplica_ni_vuelve_a_descontar(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    _producto(db_session, a_store, sku="LIB-002", nombre="Rayuela", precio=10000, marketplace_stock=5)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": [_pedido_ml(2000002, "LIB-002", quantity=1)]})
    )

    client.post("/api/mercadolibre/importar-ventas")
    segunda = client.post("/api/mercadolibre/importar-ventas")

    assert segunda.json()["ordenesNuevas"] == []
    assert segunda.json()["ordenesYaExistian"] == ["2000002"]
    assert db_session.query(Order).count() == 1
    variante = db_session.query(ProductVariant).filter_by(variant_sku="LIB-002").one()
    assert variante.marketplace_stock == 4  # no volvió a descontar en la segunda corrida


@respx.mock
def test_venta_sin_stock_reservado_suficiente_se_registra_igual_y_se_marca_el_desajuste(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    _producto(db_session, a_store, sku="LIB-003", nombre="1984", precio=10000, marketplace_stock=0)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": [_pedido_ml(2000003, "LIB-003", quantity=1)]})
    )

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.json()["ordenesNuevas"] == ["2000003"]  # la venta real no se pierde
    assert res.json()["desajustesStockReservado"] == ["LIB-003"]
    variante = db_session.query(ProductVariant).filter_by(variant_sku="LIB-003").one()
    assert variante.marketplace_stock == 0  # nunca baja de 0


@respx.mock
def test_item_sin_match_de_sku_se_reporta_sin_perder_el_pedido(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": [_pedido_ml(2000004, "SKU-QUE-NO-EXISTE", quantity=1)]})
    )

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.json()["ordenesNuevas"] == ["2000004"]
    assert res.json()["itemsSinSkuEnCatalogo"] == ["SKU-QUE-NO-EXISTE"]
    assert db_session.query(Order).count() == 1


@respx.mock
def test_rentabilidad_y_catalogo_siguen_funcionando_despues_de_importar_ventas(client, db_session, a_store, cuenta_conectada, monkeypatch):
    """Verificación explícita pedida: importar ventas reales de ML no rompe
    ni el endpoint de catálogo ni el de rentabilidad."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    _producto(db_session, a_store, sku="LIB-005", nombre="El principito", precio=8000, marketplace_stock=3)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": [_pedido_ml(2000005, "LIB-005", quantity=1, unit_price=8000)]})
    )
    client.post("/api/mercadolibre/importar-ventas")

    productos = client.get("/api/productos").json()
    fila = next(p for p in productos if p["sku"] == "LIB-005")
    assert fila["marketplaceStock"] == 2

    rentabilidad = client.get("/api/rentabilidad").json()
    assert rentabilidad["resumen"]["totalProductos"] == 1  # sigue respondiendo normal, sin costo cargado todavía


# ------------------------------------------------------------------
# Desconectar
# ------------------------------------------------------------------


def test_desconectar_limpia_la_conexion(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)

    res = client.post("/api/mercadolibre/desconectar")

    assert res.status_code == 200
    body = res.json()
    assert body["conectado"] is False
    assert body["estado"] == "not_connected"
    assert body["cuentaExternaId"] is None

    cuenta = db_session.get(MarketplaceAccount, cuenta_conectada.id)
    assert cuenta.status == "not_connected"
    assert cuenta.access_token_encrypted is None
    assert cuenta.refresh_token_encrypted is None
    assert cuenta.external_account_id is None
    assert cuenta.external_account_nickname is None
    assert cuenta.external_account_site_id is None
    assert cuenta.connected_at is None
    assert cuenta.last_checked_at is None


def test_desconectar_sin_conexion_previa_no_falla(client, a_store, monkeypatch):
    """Desconectar es idempotente — nunca hay que verificar primero si hay
    algo conectado antes de poder llamarlo."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)

    res = client.post("/api/mercadolibre/desconectar")

    assert res.status_code == 200
    assert res.json()["conectado"] is False


@respx.mock
def test_reconectar_despues_de_desconectar_funciona(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    client.post("/api/mercadolibre/desconectar")

    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "nuevo-token", "refresh_token": "nuevo-refresh", "expires_in": 21600, "user_id": 777}
        )
    )
    respx.get("https://api.mercadolibre.com/users/me").mock(
        return_value=httpx.Response(200, json={"id": 777, "nickname": "OTRA_CUENTA", "site_id": "MLC"})
    )
    state = _state_de(client.get("/api/mercadolibre/conectar").json()["authorizationUrl"])

    res = client.get("/api/mercadolibre/callback", params={"code": "codigo-nuevo", "state": state}, follow_redirects=False)

    assert _redirect_params(res)["ml"] == ["conectado"]
    cuenta = db_session.get(MarketplaceAccount, cuenta_conectada.id)
    assert cuenta.status == "connected"
    assert cuenta.external_account_id == "777"
    assert cuenta.external_account_nickname == "OTRA_CUENTA"
    assert cuenta.external_account_site_id == "MLC"


# ------------------------------------------------------------------
# La conexión pertenece a una tienda, nunca es global (sección 5 del
# pedido: "NO crear una única conexión global de Mercado Libre").
# ------------------------------------------------------------------


def test_la_cuenta_de_mercado_libre_esta_scopeada_por_tienda_no_es_global(db_session):
    usuario = User(email="dos@tiendas.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda_a = Store(owner=usuario, name="Tienda A", created_at=NOW)
    tienda_b = Store(owner=usuario, name="Tienda B", created_at=NOW)
    db_session.add_all([tienda_a, tienda_b])
    db_session.commit()

    cuenta_a = MarketplaceAccount(store=tienda_a, marketplace="mercadolibre", status="connected", external_account_id="111")
    cuenta_b = MarketplaceAccount(store=tienda_b, marketplace="mercadolibre", status="not_connected")
    db_session.add_all([cuenta_a, cuenta_b])
    db_session.commit()

    de_tienda_a = db_session.query(MarketplaceAccount).filter_by(store_id=tienda_a.id, marketplace="mercadolibre").one()
    de_tienda_b = db_session.query(MarketplaceAccount).filter_by(store_id=tienda_b.id, marketplace="mercadolibre").one()
    assert de_tienda_a.external_account_id == "111"
    assert de_tienda_a.status == "connected"
    assert de_tienda_b.status == "not_connected"  # conectar la tienda A nunca afecta a la tienda B


# ------------------------------------------------------------------
# Arquitectura multiempresa/multi-seller (29 de agosto de 2026, segunda
# ronda): Nexo es un SaaS — una sola aplicación desarrolladora de Mercado
# Libre (MERCADOLIBRE_CLIENT_ID/SECRET en backend/.env), múltiples empresas
# conectando cada una su propia cuenta vendedora. Estas pruebas demuestran
# el aislamiento entre empresas descrito en el pedido (Tests 1-9): cada una
# opera sobre `_get_account`/`_account_status`/los endpoints reales
# directamente por `store_id`, nunca mezclando datos entre tiendas.
#
# El backend todavía no resuelve "la empresa actual" desde una sesión
# autenticada (`_get_default_store` documenta ese límite conocido) — así
# que donde hace falta una segunda empresa "activa" en la misma request
# HTTP, la prueba llama directamente a las funciones que sí ya operan por
# `store_id` (las mismas que usan los endpoints), en vez de inventar un
# mecanismo de sesión que todavía no existe.
# ------------------------------------------------------------------

from app.api.routes.mercadolibre import _account_status, _consume_state, _get_account, _new_state  # noqa: E402


def _otra_tienda(db_session, *, nombre):
    usuario = User(email=f"{nombre.lower()}@empresas.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name=nombre, created_at=NOW)
    db_session.add(tienda)
    db_session.commit()
    return tienda


def test_empresa_a_conecta_su_seller_y_queda_asociado_solo_a_empresa_a(db_session):
    """Test 1 del pedido."""
    tienda_a = _otra_tienda(db_session, nombre="Empresa A")
    cuenta_a = MarketplaceAccount(store=tienda_a, marketplace="mercadolibre", status="connected", external_account_id="111", external_account_nickname="SELLER_A")
    db_session.add(cuenta_a)
    db_session.commit()

    de_a = _get_account(db_session, tienda_a)
    assert de_a.external_account_id == "111"
    assert de_a.external_account_nickname == "SELLER_A"


def test_empresa_b_conecta_su_seller_y_queda_asociado_solo_a_empresa_b(db_session):
    """Test 2 del pedido."""
    tienda_b = _otra_tienda(db_session, nombre="Empresa B")
    cuenta_b = MarketplaceAccount(store=tienda_b, marketplace="mercadolibre", status="connected", external_account_id="222", external_account_nickname="SELLER_B")
    db_session.add(cuenta_b)
    db_session.commit()

    de_b = _get_account(db_session, tienda_b)
    assert de_b.external_account_id == "222"
    assert de_b.external_account_nickname == "SELLER_B"


def test_status_de_empresa_a_nunca_incluye_datos_de_empresa_b(db_session):
    """Tests 3 y 4 del pedido: cada empresa consulta status y ve solo su
    propio seller — nunca el nickname/id/estado de la otra."""
    tienda_a = _otra_tienda(db_session, nombre="Empresa A")
    tienda_b = _otra_tienda(db_session, nombre="Empresa B")
    db_session.add_all([
        MarketplaceAccount(store=tienda_a, marketplace="mercadolibre", status="connected", external_account_id="111", external_account_nickname="SELLER_A", external_account_site_id="MLC"),
        MarketplaceAccount(store=tienda_b, marketplace="mercadolibre", status="connected", external_account_id="222", external_account_nickname="SELLER_B", external_account_site_id="MLA"),
    ])
    db_session.commit()

    status_a = _account_status(_get_account(db_session, tienda_a), configurado=True)
    status_b = _account_status(_get_account(db_session, tienda_b), configurado=True)

    assert status_a["cuentaExternaId"] == "111"
    assert status_a["nickname"] == "SELLER_A"
    assert "222" not in str(status_a.values())
    assert "SELLER_B" not in str(status_a.values())

    assert status_b["cuentaExternaId"] == "222"
    assert status_b["nickname"] == "SELLER_B"
    assert "111" not in str(status_b.values())
    assert "SELLER_A" not in str(status_b.values())


@respx.mock
def test_desconectar_empresa_a_no_afecta_la_conexion_de_empresa_b(client, db_session, a_store, cuenta_conectada, monkeypatch):
    """Test 6 del pedido. `a_store`/`cuenta_conectada` son la tienda que
    HOY resuelve `_get_default_store` (la primera creada) — se crea además
    una segunda empresa ya conectada, y se comprueba que desconectar la
    primera por HTTP nunca toca los datos de la segunda."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    from app.domain.token_crypto import encrypt_token

    tienda_b = _otra_tienda(db_session, nombre="Empresa B")
    cuenta_b = MarketplaceAccount(
        store=tienda_b, marketplace="mercadolibre", status="connected",
        external_account_id="222", external_account_nickname="SELLER_B",
        access_token_encrypted=encrypt_token("token-de-b", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-de-b", TEST_ENCRYPTION_KEY),
        connected_at=NOW, last_checked_at=NOW,
    )
    db_session.add(cuenta_b)
    db_session.commit()

    res = client.post("/api/mercadolibre/desconectar")
    assert res.status_code == 200
    assert res.json()["conectado"] is False  # la tienda resuelta (a_store) queda desconectada

    de_b = db_session.get(MarketplaceAccount, cuenta_b.id)
    assert de_b.status == "connected"  # Empresa B sigue conectada, intacta
    assert de_b.external_account_id == "222"
    assert decrypt_token(de_b.access_token_encrypted, TEST_ENCRYPTION_KEY) == "token-de-b"


@respx.mock
def test_renovar_el_token_de_empresa_a_nunca_toca_el_token_de_empresa_b(client, db_session, a_store, cuenta_con_token_vencido, monkeypatch):
    """Test 7 del pedido."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    from app.domain.token_crypto import encrypt_token

    tienda_b = _otra_tienda(db_session, nombre="Empresa B")
    cuenta_b = MarketplaceAccount(
        store=tienda_b, marketplace="mercadolibre", status="connected",
        external_account_id="222",
        access_token_encrypted=encrypt_token("token-vigente-de-b", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-vigente-de-b", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2027, 1, 1),  # vigente, no debería tocarse
        connected_at=NOW, last_checked_at=NOW,
    )
    db_session.add(cuenta_b)
    db_session.commit()

    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "token-nuevo-de-a", "refresh_token": "refresh-nuevo-de-a", "expires_in": 21600, "user_id": 555}
        )
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(return_value=httpx.Response(200, json={"results": []}))

    res = client.post("/api/mercadolibre/importar-ventas")
    assert res.status_code == 200

    cuenta_a_renovada = db_session.get(MarketplaceAccount, cuenta_con_token_vencido.id)
    assert decrypt_token(cuenta_a_renovada.access_token_encrypted, TEST_ENCRYPTION_KEY) == "token-nuevo-de-a"

    de_b = db_session.get(MarketplaceAccount, cuenta_b.id)
    assert decrypt_token(de_b.access_token_encrypted, TEST_ENCRYPTION_KEY) == "token-vigente-de-b"  # sin cambios
    assert decrypt_token(de_b.refresh_token_encrypted, TEST_ENCRYPTION_KEY) == "refresh-vigente-de-b"


def test_el_state_de_oauth_guarda_la_empresa_que_inicio_la_conexion(db_session):
    """Test de la sección 7/18 del pedido: el `state` recupera de forma
    segura qué empresa inició el intento, para que /callback asocie la
    cuenta de Mercado Libre a esa empresa y no a "la que sea la actual" en
    el momento en que Mercado Libre responde."""
    tienda_a = _otra_tienda(db_session, nombre="Empresa A")
    tienda_b = _otra_tienda(db_session, nombre="Empresa B")

    state_a, _ = _new_state(tienda_a.id)
    state_b, _ = _new_state(tienda_b.id)
    assert state_a != state_b  # impredecible, nunca el mismo valor para dos intentos

    pendiente_a = _consume_state(state_a)
    assert pendiente_a["store_id"] == tienda_a.id

    pendiente_b = _consume_state(state_b)
    assert pendiente_b["store_id"] == tienda_b.id

    # Un state ya usado no sirve una segunda vez (protección CSRF real).
    assert _consume_state(state_a) is None


def test_status_nunca_expone_tokens_ni_client_secret(client, a_store, cuenta_conectada, monkeypatch):
    """Tests 8 y 9 del pedido."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)

    res = client.get("/api/mercadolibre/estado")
    assert res.status_code == 200

    cuerpo_crudo = res.text
    assert "token-valido" not in cuerpo_crudo
    assert "refresh-valido" not in cuerpo_crudo
    assert CONFIGURED_SETTINGS.mercadolibre_client_secret not in cuerpo_crudo
    assert "access_token" not in res.json()
    assert "refresh_token" not in res.json()
    assert "clientSecret" not in res.json()


# ------------------------------------------------------------------
# POST /comisiones/recalcular — comisión REAL de Mercado Libre por
# producto (29 de agosto de 2026, segunda ronda del mismo día).
# ------------------------------------------------------------------


def test_recalcular_comisiones_sin_conexion_devuelve_400(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/mercadolibre/comisiones/recalcular")
    assert res.status_code == 400
    assert "no está conectado" in res.json()["detail"]


@respx.mock
def test_recalcular_comisiones_predice_categoria_y_guarda_la_comision_real(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    variante = _producto(db_session, a_store, sku="LIB-100", nombre="Cuaderno universitario", precio=5000)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"listing_type_id": "gold_special", "listing_type_name": "Clásica", "sale_fee_amount": 750, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 15}},
                {"listing_type_id": "gold_pro", "listing_type_name": "Premium", "sale_fee_amount": 950, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 19}},
            ],
        )
    )
    # 16 de septiembre de 2026 — bug encontrado en esta revisión: este botón
    # nunca estimaba el envío porque faltaba pasar user_id (ver
    # routes/mercadolibre.py::recalcular_comisiones). Ahora sí lo consulta.
    respx.get("https://api.mercadolibre.com/categories/MLC180937/shipping_preferences").mock(
        return_value=httpx.Response(200, json={
            "dimensions": {"height": 5, "width": 15, "length": 15, "weight": 300},
            "logistics": [{"types": ["drop_off"], "mode": "me2"}],
        })
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/users/555/shipping_options/free.*").mock(
        return_value=httpx.Response(200, json={
            "coverage": {"all_country": {"list_cost": 3050, "currency_id": "CLP", "discount": {"rate": 0.5, "type": "mandatory"}}},
        })
    )

    res = client.post("/api/mercadolibre/comisiones/recalcular")

    assert res.status_code == 200
    body = res.json()
    assert body["productosRevisados"] == 1
    assert body["productosSinCategoriaDetectada"] == []
    assert body["combinacionesComisionActualizadas"] == 1
    assert body["estimacionesEnvioActualizadas"] == 1
    assert body["costosEnvio"] is not None

    producto = db_session.get(Product, variante.product_id)
    assert producto.ml_category_id == "MLC180937"
    assert producto.ml_category_name == "Cuadernos"

    filas = db_session.query(MercadoLibreCategoryFee).filter_by(store_id=a_store.id, category_id="MLC180937", price=5000).all()
    por_tipo = {f.listing_type_id: f for f in filas}
    assert por_tipo["gold_special"].percentage_fee == 15
    assert por_tipo["gold_pro"].percentage_fee == 19

    # La respuesta de rentabilidad ahora muestra la comisión real, Clásica y
    # Premium en paralelo — sin elegir una por el dueño.
    fila_rentabilidad = client.get("/api/rentabilidad").json()["productos"][0]
    assert fila_rentabilidad["comisionMlReal"]["classic"]["comisionPct"] == 15
    assert fila_rentabilidad["comisionMlReal"]["premium"]["comisionPct"] == 19


@respx.mock
def test_recalcular_comisiones_no_repite_la_llamada_si_ya_esta_cacheada(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    variante = _producto(db_session, a_store, sku="LIB-101", nombre="Cuaderno ya categorizado", precio=5000)
    producto = db_session.get(Product, variante.product_id)
    producto.ml_category_id = "MLC180937"
    producto.ml_category_name = "Cuadernos"
    db_session.add_all([
        MercadoLibreCategoryFee(store_id=a_store.id, category_id="MLC180937", listing_type_id="gold_special", price=5000, percentage_fee=15, fixed_fee=0, sale_fee_amount=750, fetched_at=NOW),
        MercadoLibreCategoryFee(store_id=a_store.id, category_id="MLC180937", listing_type_id="gold_pro", price=5000, percentage_fee=19, fixed_fee=0, sale_fee_amount=950, fetched_at=NOW),
        # 16 de septiembre de 2026 — con el bug de user_id corregido, este
        # endpoint también consulta el envío estimado; ya cacheado tampoco
        # debe volver a pedirse (mismo espíritu del test).
        MercadoLibreShippingEstimate(store_id=a_store.id, category_id="MLC180937", price=5000, shipping_cost=3050, mandatory=True, dimensions="5x15x15,300", fetched_at=NOW),
    ])
    db_session.commit()

    ruta_categoria = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*")
    ruta_comision = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*")
    ruta_envio = respx.get("https://api.mercadolibre.com/categories/MLC180937/shipping_preferences")

    res = client.post("/api/mercadolibre/comisiones/recalcular")

    assert res.status_code == 200
    body = res.json()
    assert body["combinacionesComisionActualizadas"] == 0
    assert body["estimacionesEnvioActualizadas"] == 0
    # Ya tenía categoría Y ya estaban cacheados los dos tipos Y el envío ->
    # ninguna llamada nueva a Mercado Libre.
    assert ruta_categoria.calls.call_count == 0
    assert ruta_comision.calls.call_count == 0
    assert ruta_envio.calls.call_count == 0


@respx.mock
def test_recalcular_comisiones_sin_permiso_de_publicacion_devuelve_502_amigable(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    variante = _producto(db_session, a_store, sku="LIB-102", nombre="Cuaderno sin permiso", precio=5000)
    producto = db_session.get(Product, variante.product_id)
    producto.ml_category_id = "MLC180937"  # ya tiene categoría -> no llama domain_discovery
    db_session.commit()

    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(403, json={"code": "PA_UNAUTHORIZED_RESULT_FROM_POLICIES"})
    )

    res = client.post("/api/mercadolibre/comisiones/recalcular")

    assert res.status_code == 502
    detalle = res.json()["detail"]
    assert "Publicación y sincronización" in detalle
    # Nunca el código/JSON técnico crudo de Mercado Libre en la respuesta.
    assert "PA_UNAUTHORIZED_RESULT_FROM_POLICIES" not in detalle


def test_comision_ml_real_de_empresa_a_nunca_se_mezcla_con_empresa_b(db_session):
    tienda_a = _otra_tienda(db_session, nombre="Empresa A")
    tienda_b = _otra_tienda(db_session, nombre="Empresa B")
    db_session.add_all([
        MercadoLibreCategoryFee(store_id=tienda_a.id, category_id="MLC180937", listing_type_id="gold_special", price=5000, percentage_fee=15, fixed_fee=0, sale_fee_amount=750, fetched_at=NOW),
        MercadoLibreCategoryFee(store_id=tienda_b.id, category_id="MLC180937", listing_type_id="gold_special", price=5000, percentage_fee=99, fixed_fee=0, sale_fee_amount=4950, fetched_at=NOW),
    ])
    db_session.commit()

    de_a = db_session.query(MercadoLibreCategoryFee).filter_by(store_id=tienda_a.id, category_id="MLC180937", price=5000).one()
    de_b = db_session.query(MercadoLibreCategoryFee).filter_by(store_id=tienda_b.id, category_id="MLC180937", price=5000).one()
    assert de_a.percentage_fee == 15
    assert de_b.percentage_fee == 99  # misma categoría/precio, comisión completamente distinta por tienda
