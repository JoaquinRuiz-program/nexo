"""
Pruebas end-to-end de /api/mercadolibre/* — cliente HTTP real de FastAPI,
SQLite en memoria vía dependency_override, y la API de Mercado Libre
mockeada con respx (nunca se llama a la red real ni se usan credenciales
reales).
"""

from __future__ import annotations

from datetime import datetime

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
UNCONFIGURED_SETTINGS = Settings()


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
def a_store(db_session):
    usuario = User(email="tienda@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Tienda de prueba", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda"))
    db_session.commit()
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


def test_conectar_sin_credenciales_devuelve_400_con_el_detalle_de_lo_que_falta(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: UNCONFIGURED_SETTINGS)
    res = client.get("/api/mercadolibre/conectar")
    assert res.status_code == 400
    detalle = res.json()["detail"]
    assert "MERCADOLIBRE_CLIENT_ID" in detalle
    assert "MERCADOLIBRE_CLIENT_SECRET" in detalle
    assert "MERCADOLIBRE_REDIRECT_URI" in detalle
    assert "TOKEN_ENCRYPTION_KEY" in detalle


def test_conectar_con_credenciales_devuelve_la_url_de_autorizacion_real(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/mercadolibre/conectar")
    assert res.status_code == 200
    url = res.json()["authorizationUrl"]
    assert url.startswith("https://auth.mercadolibre.cl/authorization?")
    assert "client_id=test-client-id" in url
    assert "state=" in url


def test_callback_con_state_invalido_se_rechaza(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.get("/api/mercadolibre/callback", params={"code": "x", "state": "no-existe"})
    assert res.status_code == 400


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

    state = client.get("/api/mercadolibre/conectar").json()["authorizationUrl"].split("state=")[1]
    res = client.get("/api/mercadolibre/callback", params={"code": "codigo-real", "state": state})

    assert res.status_code == 200
    body = res.json()
    assert body["conectado"] is True
    assert body["cuentaExternaId"] == "555"
    # La respuesta HTTP nunca expone el token, cifrado o no.
    assert "APP_USR-real" not in res.text
    assert "token" not in body

    cuenta = db_session.query(MarketplaceAccount).filter_by(store_id=a_store.id, marketplace="mercadolibre").one()
    assert cuenta.access_token_encrypted != "APP_USR-real"  # nunca texto plano
    assert decrypt_token(cuenta.access_token_encrypted, TEST_ENCRYPTION_KEY) == "APP_USR-real"
    assert decrypt_token(cuenta.refresh_token_encrypted, TEST_ENCRYPTION_KEY) == "TG-real"


def test_importar_ventas_sin_conexion_devuelve_400(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/mercadolibre/importar-ventas")
    assert res.status_code == 400
    assert "no está conectado" in res.json()["detail"]


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
