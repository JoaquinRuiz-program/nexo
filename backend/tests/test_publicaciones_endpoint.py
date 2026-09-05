"""
Pruebas end-to-end de /api/publicaciones/* — el "borrador de publicación"
en modo simulación, contra datos reales en una base SQLite en memoria.
"""

from __future__ import annotations

import json
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

from app.db.base import Base
from app.db.models import (
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingVariant,
    MercadoLibreCategoryFee,
    Product,
    ProductImage,
    ProductVariant,
    Store,
    StoreSettings,
    User,
)
from app.db.session import get_db
from app.domain.security import hash_password
from app.domain.token_crypto import encrypt_token
from tests.auth_helpers import autenticar
from app.main import app
from app.config import Settings

NOW = datetime(2026, 8, 24, 12, 0, 0)

TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

CONFIGURED_SETTINGS = Settings(
    mercadolibre_client_id="test-client-id",
    mercadolibre_client_secret="test-client-secret",
    mercadolibre_redirect_uri="http://localhost:8000/api/mercadolibre/callback",
    mercadolibre_auth_domain="auth.mercadolibre.cl",
    token_encryption_key=TEST_ENCRYPTION_KEY,
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


def _producto(db_session, tienda, *, sku, nombre, marca, categoria, precio, costo, con_imagen=True):
    producto = Product(store=tienda, internal_sku=sku, name=nombre, brand=marca, category=categoria, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=tienda.id, variant_sku=sku, price=precio, cost_price=costo, created_at=NOW, updated_at=NOW))
    if con_imagen:
        db_session.add(ProductImage(product=producto, url="http://cdn.test/img.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()
    return producto.variants[0].id


def test_borrador_de_producto_rentable(client, db_session, a_store):
    variant_id = _producto(db_session, a_store, sku="A", nombre="Taladro percutor", marca="Bosch", categoria="Herramientas", precio=45990, costo=28000)

    res = client.get(f"/api/publicaciones/borrador/{variant_id}", params={"requiere_stock": "false"})

    assert res.status_code == 200
    body = res.json()
    assert body["estado"] == "listo_para_publicar"
    assert body["tituloPropuesto"] == "Bosch Taladro percutor"
    assert body["categoriaEsOficialDeMercadoLibre"] is False
    assert body["contenidoSimulado"] is True
    assert body["advertencias"] == []


def test_borrador_de_producto_no_rentable_explica_por_que(client, db_session, a_store):
    variant_id = _producto(db_session, a_store, sku="B", nombre="Cojín decorativo", marca=None, categoria="Hogar", precio=7500, costo=8000)

    res = client.get(f"/api/publicaciones/borrador/{variant_id}", params={"requiere_stock": "false"})

    body = res.json()
    assert body["estado"] == "no_recomendado"
    assert body["clasificacion"] == "no_rentable"
    assert any("negativa" in a for a in body["advertencias"])


def test_borrador_sin_imagen_advierte_pero_no_bloquea(client, db_session, a_store):
    variant_id = _producto(db_session, a_store, sku="C", nombre="Producto sin imagen", marca=None, categoria="X", precio=10000, costo=5000, con_imagen=False)

    body = client.get(f"/api/publicaciones/borrador/{variant_id}", params={"requiere_stock": "false"}).json()
    assert "Sin imagen cargada." in body["advertencias"]
    assert body["estado"] == "listo_para_publicar"


def test_borrador_de_producto_inexistente_da_404(client, a_store):
    res = client.get("/api/publicaciones/borrador/999999")
    assert res.status_code == 404


@pytest.fixture()
def cuenta_ml_conectada(db_session, a_store):
    cuenta = MarketplaceAccount(
        store=a_store, marketplace="mercadolibre", status="connected",
        external_account_id="555", external_account_nickname="VENDEDOR_TEST", external_account_site_id="MLC",
        # Token real (cifrado) — /confirmar lo necesita para las llamadas
        # autenticadas (get_listing_fees, create_item); /preparar y
        # /validar no lo tocan (solo pegan a endpoints públicos de ML).
        access_token_encrypted=encrypt_token("token-de-prueba", TEST_ENCRYPTION_KEY),
        refresh_token_encrypted=encrypt_token("refresh-de-prueba", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2027, 1, 1),
    )
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


def _producto_publicable(
    db_session, tienda, *, sku, nombre="Cuaderno universitario", marca="Torre", categoria="Papelería",
    precio=5000, costo=3000, marketplace_stock=5, barcode=None, con_imagen=True, gtin_confirmado_ausente=False,
):
    """Como _producto, pero además configurado para pasar el gate de
    rentabilidad real de /confirmar: canal "mercadolibre" con comisión
    cargada + stock reservado para ML (classify_product con
    require_marketplace_stock=True, channel="mercadolibre")."""
    if db_session.query(ChannelCostSettings).filter_by(store_id=tienda.id, channel="mercadolibre").first() is None:
        db_session.add(ChannelCostSettings(store=tienda, channel="mercadolibre", commission_pct=15.0, updated_at=NOW))
    producto = Product(store=tienda, internal_sku=sku, name=nombre, brand=marca, category=categoria, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(
        product=producto, store_id=tienda.id, variant_sku=sku, price=precio, cost_price=costo,
        marketplace_stock=marketplace_stock, barcode=barcode, gtin_confirmado_ausente=gtin_confirmado_ausente,
        created_at=NOW, updated_at=NOW,
    ))
    if con_imagen:
        db_session.add(ProductImage(product=producto, url="http://cdn.test/img.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()
    return producto.variants[0].id


# Misma comisión real capturada en vivo (ver ml_fees.py) — Clásica/Premium
# con currency_id, necesaria para que resolver_listing_type arme el
# payload real.
FEES_CUADERNOS = [
    {
        "listing_type_id": "gold_special", "listing_type_name": "Clásica", "currency_id": "CLP",
        "sale_fee_amount": 750, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 15},
    },
    {
        "listing_type_id": "gold_pro", "listing_type_name": "Premium", "currency_id": "CLP",
        "sale_fee_amount": 950, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 19},
    },
]

# GET /users/me — 30 de agosto de 2026, soporte User Products: /confirmar
# lo consulta fresco en cada llamada para saber si la cuenta ya tiene el
# tag "user_product_seller" (ver domain/ml_seller_capabilities.py).
USER_INFO_LEGACY = {"id": 555, "nickname": "VENDEDOR_TEST", "site_id": "MLC", "tags": ["normal"]}
USER_INFO_USER_PRODUCT_SELLER = {"id": 555, "nickname": "VENDEDOR_TEST", "site_id": "MLC", "tags": ["normal", "user_product_seller"]}


def _mock_users_me(user_info: dict = USER_INFO_LEGACY):
    return respx.get("https://api.mercadolibre.com/users/me").mock(return_value=httpx.Response(200, json=user_info))


# Subconjunto real de GET /categories/MLC180937/attributes — mismo fixture
# que tests/test_listing_validation.py (capturado en vivo el 29 de agosto
# de 2026), reusado acá para probar el endpoint de punta a punta.
ATRIBUTOS_CUADERNOS = [
    {"id": "BRAND", "name": "Marca", "tags": {"catalog_required": True, "required": True}, "value_type": "string"},
    {"id": "MODEL", "name": "Modelo", "tags": {"catalog_required": True}, "value_type": "string"},
    {"id": "GTIN", "name": "Código universal de producto", "tags": {"conditional_required": True}, "value_type": "string"},
    {
        "id": "ITEM_CONDITION", "name": "Condición del ítem", "tags": {"hidden": True}, "value_type": "list",
        "values": [{"id": "2230284", "name": "Nuevo"}, {"id": "2230581", "name": "Usado"}],
    },
    {
        "id": "COLOR", "name": "Color", "tags": {"required": True}, "value_type": "list",
        "values": [{"id": "52049", "name": "Azul"}, {"id": "62050", "name": "Rojo"}],
    },
    {
        "id": "EMPTY_GTIN_REASON", "name": "Motivo de GTIN vacío", "tags": {"hidden": True, "conditional_required": True}, "value_type": "list",
        "values": [
            {"id": "17055158", "name": "El producto es una pieza artesanal"},
            {"id": "17055159", "name": "El producto es un kit o un pack"},
            {"id": "17055160", "name": "El producto no tiene código registrado"},
            {"id": "17055161", "name": "Otra razón"},
        ],
    },
]


# ------------------------------------------------------------------
# POST /{variant_id}/mercadolibre/preparar — solo lectura, nunca llama a
# POST /items (29 de agosto de 2026, commit 3/N).
# ------------------------------------------------------------------


def test_preparar_sin_cuenta_ml_conectada_devuelve_400(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="P1", nombre="Cuaderno", marca="Torre", categoria="Papelería", precio=5000, costo=3000)

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")
    assert res.status_code == 400
    assert "Mercado Libre" in res.json()["detail"]


def test_preparar_sin_credenciales_de_la_app_devuelve_400(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    # Vacío A PROPÓSITO en los 4 campos — Settings() por defecto LEE el
    # .env real del desarrollador (ver ENV_PATH en app/config.py), y para
    # este proyecto ya tiene credenciales reales configuradas (verificado
    # en la ronda de OAuth) — un Settings() "pelado" dejaría de representar
    # el caso "sin configurar" (mismo criterio ya aplicado en
    # test_mercadolibre_endpoints.py:UNCONFIGURED_SETTINGS).
    sin_credenciales = Settings(
        mercadolibre_client_id="", mercadolibre_client_secret="", mercadolibre_redirect_uri="", token_encryption_key=""
    )
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: sin_credenciales)
    variant_id = _producto(db_session, a_store, sku="P2", nombre="Cuaderno", marca="Torre", categoria="Papelería", precio=5000, costo=3000)

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")
    assert res.status_code == 400
    assert "MERCADOLIBRE_CLIENT_ID" in res.json()["detail"]


def test_preparar_variante_sin_precio_devuelve_400_accionable(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    producto = Product(store=a_store, internal_sku="SIN-PRECIO", name="Producto sin precio", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="SIN-PRECIO", created_at=NOW, updated_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")
    assert res.status_code == 400
    assert "precio" in res.json()["detail"].lower()


def test_preparar_de_variante_inexistente_o_de_otra_tienda_da_404(client, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/publicaciones/999999/mercadolibre/preparar")
    assert res.status_code == 404


@respx.mock
def test_preparar_con_categoria_ya_predicha_no_llama_a_domain_discovery(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    producto = Product(
        store=a_store, internal_sku="YA-CAT", name="Cuaderno universitario", brand="Torre",
        ml_category_id="MLC180937", ml_category_name="Cuadernos", product_type="simple", created_at=NOW, updated_at=NOW,
    )
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="YA-CAT", price=5000, cost_price=3000, marketplace_stock=5, created_at=NOW, updated_at=NOW))
    db_session.add(ProductImage(product=producto, url="http://cdn.test/img.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id

    ruta_prediccion = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*")
    respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL))

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")

    assert res.status_code == 200
    body = res.json()
    assert body["categoriaSugerida"] == {"id": "MLC180937", "nombre": "Cuadernos"}
    assert body["categoriaConfirmada"] is False  # SIEMPRE False acá, nunca autoconfirmada
    assert body["titulo"] == "Torre Cuaderno universitario"
    assert body["precio"] == 5000.0
    assert body["marketplaceStock"] == 5
    assert body["imagenes"] == ["http://cdn.test/img.png"]
    assert body["advertencias"] == []
    assert ruta_prediccion.calls.call_count == 0  # ya tenía categoría, no hizo falta predecir
    # FASE 3 (30 de agosto de 2026) — descripción revisable antes de publicar.
    assert body["descripcionCorta"] == "Cuaderno universitario. Marca Torre."
    assert body["descripcionCompleta"] == body["descripcionCorta"] + "\n\n- Marca: Torre"
    assert "Marca: Torre" in body["caracteristicas"]
    assert body["especificaciones"] == {"Marca": "Torre"}


@respx.mock
def test_preparar_trunca_el_titulo_al_max_title_length_real_de_la_categoria(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    producto = Product(
        store=a_store, internal_sku="TITULO-LARGO", name="Cuaderno universitario espiralado tapa dura cien hojas cuadriculado",
        brand="Torre", ml_category_id="MLC180937", ml_category_name="Cuadernos", product_type="simple", created_at=NOW, updated_at=NOW,
    )
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="TITULO-LARGO", price=5000, cost_price=3000, marketplace_stock=5, created_at=NOW, updated_at=NOW))
    db_session.add(ProductImage(product=producto, url="http://cdn.test/img.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id

    respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(
        return_value=httpx.Response(200, json={"id": "MLC180937", "name": "Cuadernos", "settings": {"max_title_length": 30}})
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")

    assert res.status_code == 200
    assert len(res.json()["titulo"]) <= 30
    assert res.json()["titulo"].endswith("…")


@respx.mock
def test_preparar_sin_categoria_previa_predice_una_nueva(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="SIN-CAT", nombre="Cuaderno universitario", marca="Torre", categoria="Papelería", precio=5000, costo=3000)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
    )
    respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL))

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")

    assert res.status_code == 200
    assert res.json()["categoriaSugerida"] == {"id": "MLC180937", "nombre": "Cuadernos"}


@respx.mock
def test_preparar_sin_categoria_y_sin_prediccion_posible_avisa_sin_bloquear(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="RARO", nombre="asdf", marca=None, categoria=None, precio=5000, costo=3000, con_imagen=False)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[])
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")

    assert res.status_code == 200
    body = res.json()
    assert body["categoriaSugerida"] is None
    assert "No pudimos sugerir una categoría" in " ".join(body["advertencias"])
    assert "Sin imagen cargada." in body["advertencias"]


def test_preparar_nunca_llama_a_post_items(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    # Ninguna ruta de POST /items está mockeada — si el endpoint la
    # llamara, respx (fuera de este test, sin @respx.mock) dejaría pasar
    # una request real a la red y el test fallaría por timeout/conexión;
    # acá lo confirmamos explícitamente inspeccionando que ni siquiera se
    # intenta armar ese payload: alcanza con que preparar responda 200 sin
    # necesitar mockear /items en absoluto.
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(
        db_session, a_store, sku="NUNCA-ITEMS", nombre="Cuaderno", marca="Torre", categoria="Papelería", precio=5000, costo=3000
    )
    with respx.mock:  # cualquier request HTTP real no mockeada acá adentro lanza AssertionError de respx
        respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
            return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
        )
        respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL))
        res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")
    assert res.status_code == 200


# ------------------------------------------------------------------
# POST /{variant_id}/mercadolibre/validar
# ------------------------------------------------------------------


@respx.mock
def test_validar_atributos_completos_y_faltantes_con_datos_reales(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="VAL-1", nombre="Cuaderno universitario", marca="Torre", categoria="Papelería", precio=5000, costo=3000)

    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"}
    )

    assert res.status_code == 200
    body = res.json()
    ids_completos = {a["id"] for a in body["atributosCompletos"]}
    ids_faltantes = {f["id"] for f in body["atributosFaltantes"]}

    assert "BRAND" in ids_completos  # Nexo ya tenía la marca
    assert "ITEM_CONDITION" in ids_completos  # resuelto dinámicamente, nunca pedido al dueño
    item_condition = next(a for a in body["atributosCompletos"] if a["id"] == "ITEM_CONDITION")
    assert item_condition["valueId"] == "2230284"
    assert item_condition["valueName"] == "Nuevo"
    assert item_condition["nombre"] == "Condición del ítem"  # nombre humano, nunca el id crudo en pantalla
    brand_completo = next(a for a in body["atributosCompletos"] if a["id"] == "BRAND")
    assert brand_completo["nombre"] == "Marca"

    assert "MODEL" not in ids_faltantes  # solo catalog_required, no aplica en v1
    assert "GTIN" in ids_faltantes  # conditional_required, sin código de barras cargado
    assert "COLOR" in ids_faltantes  # required, sin dato
    faltante_color = next(f for f in body["atributosFaltantes"] if f["id"] == "COLOR")
    assert faltante_color["opciones"] == [{"id": "52049", "name": "Azul"}, {"id": "62050", "name": "Rojo"}]

    assert body["listoParaPublicar"] is False
    assert "no autoriza a publicar" in body["nota"]


@respx.mock
def test_validar_usado_resuelve_item_condition_usado(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="VAL-USADO", nombre="Cuaderno", marca="Torre", categoria="Papelería", precio=5000, costo=3000)
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "used"}
    )

    item_condition = next(a for a in res.json()["atributosCompletos"] if a["id"] == "ITEM_CONDITION")
    assert item_condition["valueId"] == "2230581"
    assert item_condition["valueName"] == "Usado"


@respx.mock
def test_validar_con_codigo_de_barras_completa_gtin(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    producto = Product(store=a_store, internal_sku="CON-EAN", name="Cuaderno", brand="Torre", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="CON-EAN", price=5000, cost_price=3000, barcode="7891234567895", created_at=NOW, updated_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id

    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
    )
    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})

    ids_faltantes = {f["id"] for f in res.json()["atributosFaltantes"]}
    assert "GTIN" not in ids_faltantes


@respx.mock
def test_validar_con_categoria_inexistente_devuelve_400_amigable_no_json_crudo(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="CAT-MALA", nombre="Cuaderno", marca="Torre", categoria="X", precio=5000, costo=3000)

    respx.get("https://api.mercadolibre.com/categories/MLC999999999/attributes").mock(
        return_value=httpx.Response(404, json={"message": "Category not found", "error": "not_found", "status": 404})
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC999999999", "condition": "new"})

    assert res.status_code == 400
    detalle = res.json()["detail"]
    assert "no existe" in detalle.lower() or "no es válida" in detalle.lower()
    assert "Category not found" not in detalle  # nunca el JSON/mensaje crudo de ML


@respx.mock
def test_validar_con_mercado_libre_caido_devuelve_502_amigable(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="ML-CAIDO", nombre="Cuaderno", marca="Torre", categoria="X", precio=5000, costo=3000)

    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(side_effect=httpx.ConnectError("sin red"))

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})

    assert res.status_code == 502
    assert "ConnectError" not in res.json()["detail"]


def test_validar_sin_cuenta_ml_conectada_devuelve_400(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="SIN-CUENTA", nombre="Cuaderno", marca="Torre", categoria="X", precio=5000, costo=3000)

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})
    assert res.status_code == 400


def test_validar_de_variante_de_otra_tienda_da_404(client, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/publicaciones/999999/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})
    assert res.status_code == 404


def test_validar_condition_invalida_devuelve_400(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="COND-MALA", nombre="Cuaderno", marca="Torre", categoria="X", precio=5000, costo=3000)
    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "reacondicionado"})
    assert res.status_code == 400


@respx.mock
def test_validar_muestra_rentabilidad_actual_pero_nunca_como_autorizacion(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    from app.db.models import ChannelCostSettings

    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # Canal Mercado Libre configurado (si no, la clasificación es
    # "sin_datos" — correcto, pero no es lo que este test quiere mostrar).
    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=15.0, updated_at=NOW))
    # Producto NO rentable (precio menor al costo) — validar lo muestra,
    # pero listoParaPublicar depende solo de los atributos, no del margen:
    # el gate real es responsabilidad de /confirmar, todavía no construido.
    # marketplace_stock cargado para que el motivo de "no rentable" sea el
    # margen negativo, no la falta de stock reservado (chequeo anterior).
    producto = Product(store=a_store, internal_sku="NO-RENTABLE", name="Cuaderno", brand="Torre", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="NO-RENTABLE", price=1000, cost_price=5000, marketplace_stock=5, created_at=NOW, updated_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=[{"id": "BRAND", "name": "Marca", "tags": {"required": True}, "value_type": "string"}])
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})

    body = res.json()
    assert body["rentabilidad"]["clasificacion"] == "no_rentable"
    assert "no autoriza a publicar" in body["nota"]


def test_validar_nunca_crea_marketplace_listing(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    from app.db.models import MarketplaceListing

    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="SIN-LISTING", nombre="Cuaderno", marca="Torre", categoria="X", precio=5000, costo=3000)
    with respx.mock:
        respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
            return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
        )
        client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})

    assert db_session.query(MarketplaceListing).count() == 0


# ------------------------------------------------------------------
# POST /{variant_id}/mercadolibre/confirmar — publicación REAL (29 de
# agosto de 2026, commit 4/N): el único flujo de todo el backend que puede
# terminar ejecutando POST /items de verdad contra Mercado Libre.
# ------------------------------------------------------------------


@respx.mock
def test_confirmar_publica_arma_el_payload_correcto_y_persiste_item_id_y_user_product_id(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="CONF-OK", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(200, json=FEES_CUADERNOS)
    )
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(
            201,
            json={"id": "MLC123456789", "user_product_id": "MLCU1234567", "permalink": "https://articulo.mercadolibre.cl/x"},
        )
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["itemId"] == "MLC123456789"
    assert body["userProductId"] == "MLCU1234567"
    assert body["permalink"] == "https://articulo.mercadolibre.cl/x"

    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert payload_enviado["title"] == "Torre Cuaderno universitario"
    assert payload_enviado["category_id"] == "MLC180937"
    assert payload_enviado["price"] == 5000
    assert payload_enviado["currency_id"] == "CLP"
    assert payload_enviado["available_quantity"] == 5
    assert payload_enviado["listing_type_id"] == "gold_special"  # Clásica, resuelto por nombre
    assert payload_enviado["shipping"] == {"mode": "not_specified"}
    assert "condition" not in payload_enviado  # nunca como campo raíz
    assert "sale_terms" not in payload_enviado  # nunca en v1 (solo new/used)
    assert "family_name" not in payload_enviado  # cuenta legacy (sin user_product_seller) — nunca lo manda

    atributos = {a["id"]: a for a in payload_enviado["attributes"]}
    assert atributos["ITEM_CONDITION"]["value_id"] == "2230284"  # resuelto dinámicamente por nombre
    assert atributos["COLOR"]["value_name"] == "Azul"  # dato ingresado a mano por el dueño
    assert atributos["GTIN"]["value_name"] == "7891234567895"  # dato que Nexo ya tenía
    assert "MODEL" not in atributos  # catalog_required, no aplica en v1

    listing = db_session.query(MarketplaceListing).one()
    assert listing.external_listing_id == "MLC123456789"
    assert listing.user_product_id == "MLCU1234567"
    assert listing.status == "active"
    assert listing.account_id == cuenta_ml_conectada.id
    listing_variant = db_session.query(MarketplaceListingVariant).one()
    assert listing_variant.variant_id == variant_id
    assert listing_variant.listing_id == listing.id


@respx.mock
def test_confirmar_con_premium_resuelve_listing_type_id_por_nombre_no_por_constante(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="CONF-PREMIUM", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC999999999"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "premium", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 200, res.text
    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert payload_enviado["listing_type_id"] == "gold_pro"


# ------------------------------------------------------------------
# /confirmar con cuenta user_product_seller (30 de agosto de 2026) — la
# cuenta ya migró al modelo User Products de Mercado Libre: el payload
# manda family_name en vez de title (ver domain/ml_seller_capabilities.py
# y domain/ml_listing_payload.py).
# ------------------------------------------------------------------

CATEGORIA_CUADERNOS_REAL = {
    "id": "MLC180937", "name": "Cuadernos",
    "settings": {"max_title_length": 60, "max_sub_title_length": 70},
}


@respx.mock
def test_confirmar_con_user_product_seller_manda_family_name_calcula_default_y_persiste(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="UP-OK", barcode="7891234567895")

    _mock_users_me(USER_INFO_USER_PRODUCT_SELLER)
    ruta_categoria = respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(
        return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL)
    )
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(200, json=FEES_CUADERNOS)
    )
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "MLC777777777", "user_product_id": "MLCU7777777",
                "title": "Torre Cuaderno universitario Azul",  # generado por ML, no lo mandamos nosotros
                "family_name": "Torre Cuaderno universitario",
            },
        )
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={
            "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
            "attributes": {"COLOR": "Azul", "MODEL": "Universitario"},
        },
    )

    assert res.status_code == 200, res.text
    assert ruta_categoria.calls.call_count == 1  # se consultó UNA vez para calcular el default

    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert payload_enviado["family_name"] == "Torre Cuaderno universitario"  # default = título truncado
    assert "title" not in payload_enviado  # nunca se manda title a una cuenta user_product_seller

    listing = db_session.query(MarketplaceListing).one()
    assert listing.external_listing_id == "MLC777777777"
    assert listing.family_name == "Torre Cuaderno universitario"
    assert listing.title == "Torre Cuaderno universitario Azul"  # el que devolvió Mercado Libre


@respx.mock
def test_confirmar_con_user_product_seller_y_family_name_explicito_no_consulta_la_categoria(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """Si el dueño ya mandó un family_name, no hace falta gastar un
    llamado extra a Mercado Libre calculando un default (backend-architect,
    revisión del 30 de agosto de 2026)."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="UP-FAMILY-EXPLICITO", barcode="7891234567895")

    _mock_users_me(USER_INFO_USER_PRODUCT_SELLER)
    ruta_categoria = respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(
        return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL)
    )
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS)
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(200, json=FEES_CUADERNOS)
    )
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC888888888"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={
            "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
            "attributes": {"COLOR": "Azul", "MODEL": "Universitario"}, "family_name": "Mi familia elegida a mano",
        },
    )

    assert res.status_code == 200, res.text
    assert ruta_categoria.calls.call_count == 0  # no se consultó — el dueño ya lo dio
    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert payload_enviado["family_name"] == "Mi familia elegida a mano"


@respx.mock
def test_confirmar_con_user_product_seller_y_ml_rechazando_400_no_crea_ningun_registro(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """Representativo de los 8 casos de error ya cubiertos para la rama
    legacy — el manejo de errores es agnóstico del payload (title vs
    family_name), así que alcanza con confirmarlo en UN caso real."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="UP-400", barcode="7891234567895")

    _mock_users_me(USER_INFO_USER_PRODUCT_SELLER)
    respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL))
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(400, json={"message": "family_name required", "error": "bad_request"})
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={
            "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
            "attributes": {"COLOR": "Azul", "MODEL": "Universitario"},
        },
    )

    assert res.status_code == 400
    assert ruta_items.calls.call_count == 1
    assert db_session.query(MarketplaceListing).count() == 0


# ------------------------------------------------------------------
# Validación local nueva (30 de agosto de 2026, auditoría post-prueba
# real): GTIN con checksum inválido y EMPTY_GTIN_REASON inventado se
# bloquean 100% local, ANTES de cualquier llamado a Mercado Libre — nunca
# se descubre el problema recién con un POST /items real.
# ------------------------------------------------------------------


def test_confirmar_con_gtin_checksum_invalido_bloquea_local_sin_llamar_a_mercado_libre(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # El código real que Mercado Libre rechazó en la prueba end-to-end del
    # 30 de agosto de 2026 (checksum EAN-13 inválido, verificado a mano).
    variant_id = _producto_publicable(db_session, a_store, sku="GTIN-MAL", barcode="8058647628161")

    with respx.mock:  # cero requests a ML: se bloquea antes de consultar nada
        res = client.post(
            f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
            json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
        )

    assert res.status_code == 400
    assert "checksum" in res.json()["detail"].lower() or "no es válido" in res.json()["detail"].lower()
    assert db_session.query(MarketplaceListing).count() == 0


def test_confirmar_con_empty_gtin_reason_inventada_es_rechazada_localmente(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="RAZON-INVENTADA")  # sin GTIN

    with respx.mock:  # cero requests a ML — la razón inventada se rechaza antes de consultar nada
        res = client.post(
            f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
            json={
                "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
                "attributes": {"EMPTY_GTIN_REASON": "no sabemos por qué"},  # no es una de las 4 opciones reales
            },
        )

    assert res.status_code == 400
    assert "El producto no tiene código registrado" in res.json()["detail"]  # lista las opciones reales
    assert db_session.query(MarketplaceListing).count() == 0


def test_confirmar_con_no_tiene_codigo_registrado_sin_confirmar_es_datos_incompletos(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """Caso D: Nexo no conoce el GTIN, pero el dueño NUNCA confirmó
    explícitamente que el producto no tiene uno (gtin_confirmado_ausente
    sigue en False, el default). Elegir esta razón específica sin esa
    confirmación previa queda bloqueado — evita que se use como atajo para
    esconder un dato que en realidad falta cargar."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="DATOS-INCOMPLETOS")  # sin GTIN, sin confirmar

    with respx.mock:  # cero requests a ML
        res = client.post(
            f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
            json={
                "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
                "attributes": {"COLOR": "Azul", "EMPTY_GTIN_REASON": "El producto no tiene código registrado"},
            },
        )

    assert res.status_code == 400
    assert "Datos incompletos" in res.json()["detail"]
    assert "codigo-barras" in res.json()["detail"]
    assert db_session.query(MarketplaceListing).count() == 0


def test_confirmar_con_otra_razon_gtin_no_requiere_confirmacion_previa(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """El bloqueo de Caso D es puntual a "no tiene código registrado" — las
    otras 3 razones reales (artesanal/kit/otra razón) no tienen la misma
    ambigüedad "quizás Nexo simplemente no lo cargó todavía", así que no
    exigen la confirmación previa."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="OTRA-RAZON")  # sin GTIN, sin confirmar

    with respx.mock:
        respx.get("https://api.mercadolibre.com/users/me").mock(return_value=httpx.Response(200, json=USER_INFO_LEGACY))
        respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
        respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
        respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC000000K"}))
        res = client.post(
            f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
            json={
                "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
                "attributes": {"COLOR": "Azul", "EMPTY_GTIN_REASON": "El producto es un kit o un pack"},
            },
        )

    assert res.status_code == 200, res.text


@respx.mock
def test_confirmar_con_empty_gtin_reason_real_pasa_el_gate_local(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """Contraparte del test anterior: una de las 4 razones reales de
    Mercado Libre sí se acepta."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # gtin_confirmado_ausente=True: el dueño ya confirmó explícitamente que
    # no tiene GTIN — sin esto, esta razón específica queda bloqueada
    # localmente (Caso D, ver test de abajo).
    variant_id = _producto_publicable(db_session, a_store, sku="RAZON-REAL", gtin_confirmado_ausente=True)

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC000000R"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={
            "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
            "attributes": {"COLOR": "Azul", "EMPTY_GTIN_REASON": "El producto no tiene código registrado"},
        },
    )

    assert res.status_code == 200, res.text
    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert not any(a["id"] == "GTIN" for a in payload_enviado["attributes"])
    assert any(a["id"] == "EMPTY_GTIN_REASON" for a in payload_enviado["attributes"])


@respx.mock
def test_confirmar_con_user_product_seller_sin_model_es_rechazado_localmente(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="UP-SIN-MODEL", barcode="7891234567895")

    _mock_users_me(USER_INFO_USER_PRODUCT_SELLER)
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 400
    assert "Modelo" in res.json()["detail"]
    assert db_session.query(MarketplaceListing).count() == 0


# ------------------------------------------------------------------
# POST /{variant_id}/mercadolibre/confirmar/preview — 30 de agosto de
# 2026: misma validación y payload que /confirmar, pero nunca ejecuta
# POST /items. Nunca expone token/refresh_token/client_secret/cookies.
# ------------------------------------------------------------------


@respx.mock
def test_preview_devuelve_el_payload_sanitizado_sin_publicar(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="PREVIEW-OK", barcode="7891234567895")

    _mock_users_me(USER_INFO_USER_PRODUCT_SELLER)
    respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL))
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items")  # sin .mock() — si se llamara, respx haría fallar el test

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar/preview",
        json={
            "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
            "attributes": {"COLOR": "Azul", "MODEL": "Universitario"},
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["userProductSeller"] is True
    assert body["familyName"]
    assert body["title"] is None
    assert body["model"] == "Universitario"
    assert body["gtin"] == "7891234567895"
    assert ruta_items.calls.call_count == 0  # NUNCA se publicó de verdad
    assert db_session.query(MarketplaceListing).count() == 0
    # Nunca expone secretos.
    assert "access_token" not in json.dumps(body)
    assert "token" not in json.dumps(body).lower()


# ------------------------------------------------------------------
# GET /{variant_id}/mercadolibre/competencia — 30 de agosto de 2026, FASE 4.
# Solo lectura, nunca publica.
# ------------------------------------------------------------------


@respx.mock
def test_competencia_con_producto_encontrado_devuelve_el_analisis_real(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="COMP-OK", precio=22000, barcode="7891234567895")

    ruta_busqueda = respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "MLC44481022"}]})
    )
    respx.get("https://api.mercadolibre.com/products/MLC44481022").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MLC44481022", "name": "Cuaderno Moleskine Clásico",
                "buy_box_winner": {"item_id": "MLC1", "price": 22990, "currency_id": "CLP", "condition": "new", "shipping": {"free_shipping": True, "logistic_type": "fulfillment"}, "seller": {"reputation_level_id": "5_green"}},
                "buy_box_winner_price_range": {"min": {"price": 19990}, "max": {"price": 25990}},
            },
        )
    )

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/competencia")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["encontrado"] is True
    assert body["catalogProductId"] == "MLC44481022"
    assert body["analisis"]["hayCompetencia"] is True
    assert body["analisis"]["precioGanador"] == 22990
    assert body["analisis"]["posicionPrecioPropio"] == "en_rango"  # 22000 está entre 19990 y 25990
    assert "product_identifier=7891234567895" in str(ruta_busqueda.calls[0].request.url)  # GTIN válido, se buscó por código


@respx.mock
def test_competencia_sin_gtin_valido_busca_por_nombre(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="COMP-SIN-GTIN")  # sin barcode

    ruta_busqueda = respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/competencia")

    assert res.status_code == 200, res.text
    assert res.json()["encontrado"] is False
    assert res.json()["analisis"] is None
    assert "q=Cuaderno" in str(ruta_busqueda.calls[0].request.url).replace("%20", " ").replace("+", " ")


def test_competencia_de_variante_de_otra_empresa_da_404(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    otro_usuario = User(email="comp@empresa.cl", password_hash=hash_password("x"), full_name="Otro", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    otra_tienda = Store(owner=otro_usuario, name="Otra empresa", created_at=NOW)
    db_session.add(otra_tienda)
    db_session.commit()
    variant_id_ajeno = _producto_publicable(db_session, otra_tienda, sku="COMP-AJENO")

    res = client.get(f"/api/publicaciones/{variant_id_ajeno}/mercadolibre/competencia")
    assert res.status_code == 404


# ------------------------------------------------------------------
# GET /{variant_id}/mercadolibre/precio-recomendado — 30 de agosto de 2026,
# FASE 5. Solo lectura, solo RECOMIENDA — nunca modifica ningún precio.
# ------------------------------------------------------------------


def _configurar_margen(db_session, tienda, *, objetivo=None, minimo=None):
    canal = db_session.query(ChannelCostSettings).filter_by(store_id=tienda.id, channel="mercadolibre").first()
    canal.target_margin_pct = objetivo
    canal.min_margin_pct = minimo
    db_session.commit()


def test_precio_recomendado_sin_margen_objetivo_configurado_es_datos_insuficientes(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="PRECIO-SIN-MARGEN")  # ChannelCostSettings sin target_margin_pct

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tipo"] == "RECOMENDACION"  # nunca "CAMBIO_AUTOMATICO"
    assert body["estado"] == "datos_insuficientes"
    assert "margen objetivo del canal" in body["faltantes"]
    assert body["precioRecomendado"] is None


def test_precio_recomendado_sin_costo_es_datos_insuficientes(client, db_session, a_store):
    producto = Product(store=a_store, internal_sku="SIN-COSTO", name="Producto sin costo", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=15.0, target_margin_pct=25.0, updated_at=NOW))
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="SIN-COSTO", price=10000, created_at=NOW, updated_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "datos_insuficientes"
    assert "costo de compra" in body["faltantes"]


def test_precio_recomendado_con_datos_completos_y_sin_cuenta_ml_sigue_funcionando(client, db_session, a_store):
    """Sin cuenta de Mercado Libre conectada, la recomendación de precio
    (costo + comisión + margen) igual se calcula — la competencia es un
    agregado opcional, nunca un bloqueo."""
    variant_id = _producto_publicable(db_session, a_store, sku="PRECIO-SIN-ML", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "recomendacion"
    assert body["precioRecomendado"] > 0
    assert body["alcanzaMargenObjetivo"] is True
    assert body["alcanzaMargenMinimo"] is True
    assert body["posicionFrenteACompetencia"] is None  # sin cuenta ML conectada, no hay con qué comparar
    assert body["clasificacion"] is None  # hook de FASE 6, todavía no implementado


@respx.mock
def test_precio_recomendado_integra_competencia_real_cuando_hay_cuenta_conectada(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="PRECIO-CON-COMP", costo=8000, precio=20000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, objetivo=25.0)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "MLC1"}]})
    )
    respx.get("https://api.mercadolibre.com/products/MLC1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MLC1", "name": "Competidor",
                "buy_box_winner": {"price": 13990, "currency_id": "CLP", "condition": "new", "shipping": {}, "seller": {}},
                "buy_box_winner_price_range": {"min": {"price": 12000}, "max": {"price": 16000}},
            },
        )
    )

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["precioMercadoGanador"] == 13990
    assert body["posicionFrenteACompetencia"] in ("por_debajo", "en_rango", "por_encima")


def test_precio_recomendado_si_mercado_libre_falla_igual_devuelve_recomendacion(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """La búsqueda de competencia puede fallar (timeout, 500, lo que sea) —
    nunca tira abajo la recomendación de precio en sí."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="PRECIO-ML-CAIDO", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=25.0)

    with respx.mock:
        respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(side_effect=httpx.ConnectError("sin red"))
        res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "recomendacion"
    assert body["precioRecomendado"] is not None
    assert body["posicionFrenteACompetencia"] is None


def test_precio_recomendado_de_variante_de_otra_empresa_da_404(client, db_session, a_store):
    otro_usuario = User(email="precio@empresa.cl", password_hash=hash_password("x"), full_name="Otro", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    otra_tienda = Store(owner=otro_usuario, name="Otra empresa", created_at=NOW)
    db_session.add(otra_tienda)
    db_session.commit()
    variant_id_ajeno = _producto_publicable(db_session, otra_tienda, sku="PRECIO-AJENO")

    res = client.get(f"/api/publicaciones/{variant_id_ajeno}/mercadolibre/precio-recomendado")
    assert res.status_code == 404


# ------------------------------------------------------------------
# GET /{variant_id}/mercadolibre/decision — 30 de agosto de 2026, FASE 6.
# Motor "¿conviene vender?" — SOLO lectura/cálculo, nunca publica ni
# modifica nada en Mercado Libre. Comparte _resolver_recomendacion_precio
# con /precio-recomendado — nunca duplica la consulta a Mercado Libre.
# ------------------------------------------------------------------


def test_decision_datos_insuficientes_nunca_inventa_una_decision(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="DECISION-SIN-MARGEN")  # sin target_margin_pct

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tipo"] == "DECISION"
    assert body["decision"] == "revisar"
    assert "margen objetivo del canal" in body["faltantes"]
    assert body["precioRecomendado"] is None


def test_decision_conviene_sin_cuenta_ml_conectada(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="DECISION-CONVIENE", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["decision"] == "conviene"
    assert body["precioRecomendado"] > 0
    assert body["competencia"] is None
    assert isinstance(body["razon"], str) and len(body["razon"]) > 0


def test_decision_no_conviene_no_alcanza_margen_minimo(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="DECISION-NO-CONVIENE", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=5.0, minimo=20.0)

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision")

    assert res.status_code == 200, res.text
    assert res.json()["decision"] == "no_conviene"


@respx.mock
def test_decision_revisar_precio_por_encima_de_la_competencia(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="DECISION-CARO", costo=8000, precio=20000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, objetivo=40.0, minimo=10.0)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "MLC1"}]})
    )
    respx.get("https://api.mercadolibre.com/products/MLC1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MLC1", "name": "Competidor",
                "buy_box_winner": {"price": 9000, "currency_id": "CLP", "condition": "new", "shipping": {}, "seller": {}},
                "buy_box_winner_price_range": {"min": {"price": 8000}, "max": {"price": 10000}},
            },
        )
    )

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["decision"] == "revisar"
    assert body["competencia"]["posicionPrecioPropio"] == "por_encima"


@respx.mock
def test_decision_conviene_con_competencia_en_rango(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="DECISION-EN-RANGO", costo=8000, precio=20000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "MLC1"}]})
    )
    respx.get("https://api.mercadolibre.com/products/MLC1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MLC1", "name": "Competidor",
                "buy_box_winner": {"price": 13990, "currency_id": "CLP", "condition": "new", "shipping": {}, "seller": {}},
                "buy_box_winner_price_range": {"min": {"price": 8000}, "max": {"price": 16000}},
            },
        )
    )

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["decision"] == "conviene"
    assert body["competencia"]["precioGanador"] == 13990


def test_decision_de_variante_de_otra_empresa_da_404(client, db_session, a_store):
    otro_usuario = User(email="decision@empresa.cl", password_hash=hash_password("x"), full_name="Otro", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    otra_tienda = Store(owner=otro_usuario, name="Otra empresa", created_at=NOW)
    db_session.add(otra_tienda)
    db_session.commit()
    variant_id_ajeno = _producto_publicable(db_session, otra_tienda, sku="DECISION-AJENA")

    res = client.get(f"/api/publicaciones/{variant_id_ajeno}/mercadolibre/decision")
    assert res.status_code == 404


@respx.mock
def test_decision_nunca_expone_tokens_ni_publica(client, db_session, a_store):
    # Sin cuenta ML conectada: /decision no debería llamar a NINGÚN
    # endpoint de Mercado Libre (respx sin mocks — cualquier llamada real
    # haría fallar el test), y mucho menos publicar nada.
    variant_id = _producto_publicable(db_session, a_store, sku="DECISION-SIN-SECRETOS", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision")

    assert res.status_code == 200, res.text
    body_texto = json.dumps(res.json())
    assert "access_token" not in body_texto
    assert "token" not in body_texto.lower()
    assert db_session.query(MarketplaceListing).count() == 0


def test_decision_lote_calcula_para_todas_las_variantes_sin_llamar_a_ml(client, db_session, a_store):
    variant_id_1 = _producto_publicable(db_session, a_store, sku="LOTE-1", costo=8000, precio=20000)
    variant_id_2 = _producto_publicable(db_session, a_store, sku="LOTE-2", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    with respx.mock:  # sin ningún mock — cualquier llamada a Mercado Libre haría fallar el test
        res = client.get("/api/publicaciones/mercadolibre/decision-lote")

    assert res.status_code == 200, res.text
    body = res.json()
    ids = {fila["variantId"] for fila in body}
    assert variant_id_1 in ids and variant_id_2 in ids
    for fila in body:
        if fila["variantId"] in (variant_id_1, variant_id_2):
            assert fila["decision"] == "conviene"
            assert fila["precioRecomendado"] > 0


def test_decision_lote_sin_margen_configurado_es_revisar_para_todos(client, db_session, a_store):
    _producto_publicable(db_session, a_store, sku="LOTE-SIN-MARGEN", costo=8000, precio=20000)

    res = client.get("/api/publicaciones/mercadolibre/decision-lote")

    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) >= 1
    assert all(fila["decision"] == "revisar" for fila in body)
    assert all("margen objetivo del canal" in fila["faltantes"] for fila in body)


# ------------------------------------------------------------------
# 31 de agosto de 2026 — unificación comisión real vs. manual en
# /precio-recomendado, /decision y /decision-lote (mismo criterio que
# tests/test_rentabilidad.py, acá a nivel de integración HTTP completa).
# ------------------------------------------------------------------


def _agregar_comision_ml_real(db_session, tienda, *, category_id, price, listing_type_id, percentage_fee, fixed_fee=0.0):
    db_session.add(MercadoLibreCategoryFee(
        store=tienda, category_id=category_id, listing_type_id=listing_type_id, price=price,
        percentage_fee=percentage_fee, fixed_fee=fixed_fee, sale_fee_amount=price * percentage_fee / 100 + fixed_fee,
        fetched_at=NOW,
    ))
    db_session.commit()


def _configurar_canal_con_pref(db_session, tienda, *, commission_pct, listing_type_pref):
    canal = db_session.query(ChannelCostSettings).filter_by(store_id=tienda.id, channel="mercadolibre").first()
    canal.commission_pct = commission_pct
    canal.listing_type_pref = listing_type_pref
    db_session.commit()


def test_precio_recomendado_usa_comision_real_en_vez_de_manual(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="PR-REAL", costo=8000, precio=20000)
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    producto.ml_category_id = "MLC180937"
    db_session.commit()
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=10.0)
    _configurar_canal_con_pref(db_session, a_store, commission_pct=50.0, listing_type_pref="classic")  # manual absurda, no debe usarse
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "recomendacion"
    assert body["comisionMlFuente"] == "real"
    # costos_fijos=8000; precio = 8000 / (1 - 0.25 - 0.10) = 8000/0.65 (comisión REAL 10%, nunca la manual 50%)
    assert body["precioRecomendado"] == round(8000 / 0.65, 2)


def test_precio_recomendado_sin_comision_real_cae_al_fallback_manual(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="PR-MANUAL", costo=8000, precio=20000)
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)  # comisión manual 15% (default del helper), sin comisión real cacheada

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["comisionMlFuente"] == "manual"
    assert body["precioRecomendado"] == round(8000 / (1 - 0.25 - 0.15), 2)


def test_precio_recomendado_y_decision_usan_exactamente_la_misma_comision(client, db_session, a_store):
    """Caso 6 del pedido del dueño: mismos números para el mismo
    producto — ambos endpoints comparten _resolver_recomendacion_precio,
    que ahora resuelve la comisión una sola vez."""
    variant_id = _producto_publicable(db_session, a_store, sku="MISMA-COMISION", costo=8000, precio=20000)
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    producto.ml_category_id = "MLC180937"
    db_session.commit()
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=11.0)
    _configurar_canal_con_pref(db_session, a_store, commission_pct=40.0, listing_type_pref="classic")
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    precio = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    decision = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision").json()

    assert precio["comisionMlFuente"] == "real"
    assert decision["comisionMlFuente"] == "real"
    assert precio["precioRecomendado"] == decision["precioRecomendado"]
    assert precio["gananciaEstimada"] == decision["gananciaEstimada"]


def test_decision_lote_tambien_usa_comision_real(client, db_session, a_store):
    """El hallazgo real de product-reviewer: decision-lote armaba su
    propio ChannelCosts manual por separado, sin pasar por
    _resolver_recomendacion_precio — la columna Decisión de Oportunidades
    podía contradecir el precio recomendado calculado con la comisión
    real. Confirma que ahora coincide."""
    variant_id = _producto_publicable(db_session, a_store, sku="LOTE-REAL", costo=8000, precio=20000)
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    producto.ml_category_id = "MLC180937"
    db_session.commit()
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=11.0)
    _configurar_canal_con_pref(db_session, a_store, commission_pct=40.0, listing_type_pref="classic")
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    precio = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    with respx.mock:  # decision-lote nunca debe llamar a Mercado Libre
        lote = client.get("/api/publicaciones/mercadolibre/decision-lote").json()
    fila = next(f for f in lote if f["variantId"] == variant_id)

    assert fila["precioRecomendado"] == precio["precioRecomendado"]


def test_precio_recomendado_de_comision_real_nunca_usa_la_de_otra_empresa(client, db_session, a_store):
    """Caso 5 a nivel de endpoint (no solo de modelo/rentabilidad): dos
    empresas, misma categoría/precio, comisión real distinta cacheada —
    nunca se mezclan."""
    variant_id = _producto_publicable(db_session, a_store, sku="AISLADO-A", costo=8000, precio=20000)
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    producto.ml_category_id = "MLC180937"
    db_session.commit()
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=10.0)
    _configurar_canal_con_pref(db_session, a_store, commission_pct=15.0, listing_type_pref="classic")
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    otro_usuario = User(email="otra-empresa@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.commit()
    # Empresa B: misma categoría, mismo precio, comisión real MUY distinta (40%).
    variant_id_b = _producto_publicable(db_session, tienda_b, sku="AISLADO-B", costo=8000, precio=20000)
    producto_b = db_session.query(ProductVariant).filter_by(id=variant_id_b).one().product
    producto_b.ml_category_id = "MLC180937"
    db_session.commit()
    _agregar_comision_ml_real(db_session, tienda_b, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=40.0)
    _configurar_canal_con_pref(db_session, tienda_b, commission_pct=15.0, listing_type_pref="classic")
    _configurar_margen(db_session, tienda_b, objetivo=25.0, minimo=10.0)

    body_a = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    assert body_a["comisionMlFuente"] == "real"
    assert body_a["precioRecomendado"] == round(8000 / (1 - 0.25 - 0.10), 2)  # 10% de A, nunca el 40% de B

    autenticar(client, db_session, otro_usuario, tienda_b, ahora=NOW)
    body_b = client.get(f"/api/publicaciones/{variant_id_b}/mercadolibre/precio-recomendado").json()
    assert body_b["comisionMlFuente"] == "real"
    assert body_b["precioRecomendado"] == round(8000 / (1 - 0.25 - 0.40), 2)  # 40% de B, nunca el 10% de A


def _quitar_comision_manual(db_session, tienda):
    canal = db_session.query(ChannelCostSettings).filter_by(store_id=tienda.id, channel="mercadolibre").first()
    canal.commission_pct = None
    db_session.commit()


def test_precio_recomendado_sin_ninguna_comision_es_datos_insuficientes(client, db_session, a_store):
    """Caso 4 del pedido del dueño: ni comisión real cacheada ni manual
    configurada -> nunca se inventa un número, comisionMlFuente queda None
    (no False, no 'manual' con un 0% inventado)."""
    variant_id = _producto_publicable(db_session, a_store, sku="SIN-NINGUNA-COMISION", costo=8000, precio=20000)
    _quitar_comision_manual(db_session, a_store)
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "datos_insuficientes"
    assert "comisión/costos del canal" in body["faltantes"]
    assert body["precioRecomendado"] is None
    assert body["comisionMlFuente"] is None


def test_preparar_expone_fuente_de_comision_real(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """El paso "Preparar publicación" comparte la misma `fila` (rentabilidad.py)
    que Rentabilidad/Oportunidades — nunca debe mostrar una ganancia en
    Mercado Libre sin decir de dónde sale esa comisión."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    producto = Product(
        store=a_store, internal_sku="PREPARAR-REAL", name="Cuaderno universitario", brand="Torre",
        ml_category_id="MLC180937", ml_category_name="Cuadernos", product_type="simple", created_at=NOW, updated_at=NOW,
    )
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="PREPARAR-REAL", price=20000, cost_price=8000, marketplace_stock=5, created_at=NOW, updated_at=NOW))
    db_session.add(ProductImage(product=producto, url="http://cdn.test/img.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=10.0)
    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=50.0, listing_type_pref="classic", updated_at=NOW))  # manual absurda
    db_session.commit()

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rentabilidad"]["comisionMlFuente"] == "real"
    assert body["rentabilidad"]["margenMercadoLibreClp"] == 20000 - 8000 - 20000 * 0.10  # comisión real 10%, nunca la manual 50%


def test_preparar_sin_comision_real_expone_fuente_manual(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="PREPARAR-MANUAL", costo=8000, precio=20000)  # comisión manual 15%, sin real cacheada

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rentabilidad"]["comisionMlFuente"] == "manual"


def test_validar_expone_fuente_de_comision(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    producto = Product(
        store=a_store, internal_sku="VALIDAR-REAL", name="Cuaderno universitario", brand="Torre",
        ml_category_id="MLC180937", ml_category_name="Cuadernos", product_type="simple", created_at=NOW, updated_at=NOW,
    )
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="VALIDAR-REAL", price=20000, cost_price=8000, marketplace_stock=5, created_at=NOW, updated_at=NOW))
    db_session.commit()
    variant_id = producto.variants[0].id
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=10.0)
    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=50.0, listing_type_pref="classic", updated_at=NOW))
    db_session.commit()

    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=[]))
    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/validar", json={"category_id": "MLC180937", "condition": "new"})

    assert res.status_code == 200, res.text
    assert res.json()["rentabilidad"]["comisionMlFuente"] == "real"


def test_confirmar_sin_imagen_bloquea_con_400(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="SIN-IMG", con_imagen=False)

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 400
    assert "imagen" in res.json()["detail"].lower()
    assert db_session.query(MarketplaceListing).count() == 0


def test_confirmar_producto_no_rentable_bloquea_con_400(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="NO-RENT", precio=1000, costo=5000)

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 400
    assert "rentable" in res.json()["detail"].lower()
    assert db_session.query(MarketplaceListing).count() == 0


# ------------------------------------------------------------------
# 31 de agosto de 2026 — cierre de inconsistencia de negocio: el gate de
# /confirmar ahora respeta el margen mínimo configurado (ChannelCostSettings
# .min_margin_pct), no solo el margen negativo. Evalúa siempre al precio
# ACTUAL de la variante (el que se publica), nunca al precio recomendado.
# ------------------------------------------------------------------


def test_confirmar_bloquea_si_no_alcanza_el_margen_minimo_configurado(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # precio=5000, costo=3000, comisión manual 15% -> margen 25% (rentable,
    # positivo) -- pero por debajo del mínimo que el dueño configuró (40%).
    variant_id = _producto_publicable(db_session, a_store, sku="MARGEN-BAJO", precio=5000, costo=3000)
    _configurar_margen(db_session, a_store, minimo=40.0)

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 400, res.text
    assert "rentable" in res.json()["detail"].lower()
    assert "mínimo" in res.json()["detail"].lower()
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_permite_publicar_si_alcanza_el_margen_minimo_configurado(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="MARGEN-OK", precio=5000, costo=3000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, minimo=20.0)  # margen real (25%) alcanza el mínimo

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )
    assert res.status_code == 200, res.text


@respx.mock
def test_confirmar_margen_exactamente_igual_al_minimo_no_bloquea(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """classify_product compara con `<`, nunca `<=` -- igualar el mínimo
    exactamente alcanza, no bloquea (documentado en domain/catalog_selection.py)."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="MARGEN-IGUAL", precio=5000, costo=3000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, minimo=25.0)  # margen real es EXACTAMENTE 25%

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )
    assert res.status_code == 200, res.text


@respx.mock
def test_confirmar_sin_margen_minimo_configurado_solo_bloquea_por_negativo(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """Excepción documentada: sin min_margin_pct configurado, el gate no
    cambia -- sigue bloqueando únicamente margen negativo, nunca se inventa
    un mínimo implícito."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # Margen bajo (5%) pero positivo, y NINGÚN mínimo configurado.
    variant_id = _producto_publicable(db_session, a_store, sku="SIN-MINIMO", precio=5000, costo=4000, barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )
    assert res.status_code == 200, res.text


@respx.mock
def test_confirmar_evalua_el_margen_al_precio_actual_no_al_recomendado(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """El precio recomendado (calculado a partir de target_margin_pct) puede
    ser mucho más alto que el precio actual -- el gate SIEMPRE debe evaluar
    el margen al precio que realmente se va a publicar (variante.price),
    nunca al hipotético recomendado."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # Precio actual 5000, costo 3000 -> margen real 25%. target_margin_pct
    # 60% haría que /precio-recomendado sugiera un precio bastante más alto
    # -- el gate no debe mirar ESE número, solo el margen al precio actual.
    variant_id = _producto_publicable(db_session, a_store, sku="PRECIO-ACTUAL", precio=5000, costo=3000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, objetivo=60.0, minimo=20.0)

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )
    assert res.status_code == 200, res.text
    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert payload_enviado["price"] == 5000  # el precio actual, nunca el recomendado


@respx.mock
def test_confirmar_margen_minimo_de_otra_empresa_nunca_afecta_el_gate(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """Aislamiento multiempresa: el min_margin_pct de la empresa B (altísimo)
    nunca debe bloquear una publicación de la empresa A."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="AISLADO-A", precio=5000, costo=3000, barcode="7891234567895")
    _configurar_margen(db_session, a_store, minimo=20.0)

    otro_usuario = User(email="empresa-b-margen@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa B", store_name="Empresa B"))
    db_session.commit()
    _producto_publicable(db_session, tienda_b, sku="AISLADO-B", precio=5000, costo=3000)
    _configurar_margen(db_session, tienda_b, minimo=99.0)  # absurdo, nunca debe usarse para A

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )
    assert res.status_code == 200, res.text  # el 99% de B nunca bloqueó a A


def test_confirmar_recalcula_rentabilidad_de_cero_aunque_antes_pareciera_una_oportunidad(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """/confirmar nunca confía en una clasificación calculada antes (ni de
    /validar, ni de la vista de Oportunidades) — la vuelve a calcular con
    los datos de la base EN ESTE MOMENTO."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="CAMBIO-RENT", precio=5000, costo=3000)

    # El costo sube DESPUÉS de que el producto se hubiera visto como
    # rentable — nada en /confirmar debería seguir tratándolo como tal.
    variante = db_session.get(ProductVariant, variant_id)
    variante.cost_price = 9000
    db_session.commit()

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 400
    assert "rentable" in res.json()["detail"].lower()
    assert db_session.query(MarketplaceListing).count() == 0


def test_confirmar_sin_cuenta_ml_conectada_devuelve_400(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="SIN-CUENTA-CONF")

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 400


def test_confirmar_de_variante_de_otra_empresa_da_404(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    otro_usuario = User(email="otra@empresa.cl", password_hash=hash_password("x"), full_name="Otro", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    otra_tienda = Store(owner=otro_usuario, name="Otra empresa", created_at=NOW)
    db_session.add(otra_tienda)
    db_session.commit()
    variant_id_ajeno = _producto_publicable(db_session, otra_tienda, sku="AJENO")

    res = client.post(
        f"/api/publicaciones/{variant_id_ajeno}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 404  # nunca 403 — no confirma que el producto existe
    assert db_session.query(MarketplaceListing).count() == 0


def test_confirmar_bloquea_publicacion_duplicada_para_la_misma_cuenta(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="DUP")
    variante = db_session.get(ProductVariant, variant_id)

    listing_previo = MarketplaceListing(
        account=cuenta_ml_conectada, product=variante.product, external_listing_id="MLC000000000", status="active", created_at=NOW
    )
    db_session.add(listing_previo)
    db_session.flush()
    db_session.add(MarketplaceListingVariant(listing=listing_previo, variant=variante, price=5000, stock_quantity=5))
    db_session.commit()

    with respx.mock:  # ningún request a ML debería salir: se bloquea antes de consultar nada
        res = client.post(
            f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
            json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
        )
    assert res.status_code == 409
    assert db_session.query(MarketplaceListing).count() == 1  # sigue siendo solo el previo


@respx.mock
def test_confirmar_otra_variante_del_mismo_producto_ya_publicado_no_duplica_localmente(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """30 de agosto de 2026 — hallazgo de qa-engineer: el chequeo previo de
    "¿ya publicado?" está scopeado por variant_id, así que NUNCA detectaba
    este caso (una segunda variante del MISMO producto, publicada para la
    MISMA cuenta) — pasaba de largo el SELECT y llegaba hasta acá. La
    constraint uq_listing_account_product (nueva) es la que realmente lo
    bloquea, con un mensaje honesto en vez de un 500 crudo."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id_a = _producto_publicable(db_session, a_store, sku="DUP-PROD-A", barcode="7891234567895")
    variante_a = db_session.get(ProductVariant, variant_id_a)
    producto = variante_a.product

    # Segunda variante del MISMO producto — nunca pasó por _producto_publicable
    # (que crea un producto nuevo cada vez), se agrega a mano.
    variante_b = ProductVariant(
        product=producto, store_id=a_store.id, variant_sku="DUP-PROD-B", price=5000, cost_price=3000,
        marketplace_stock=5, barcode="7891234567895", created_at=NOW, updated_at=NOW,
    )
    db_session.add(variante_b)
    db_session.commit()

    listing_previo = MarketplaceListing(
        account=cuenta_ml_conectada, product=producto, external_listing_id="MLC000000000", status="active", created_at=NOW
    )
    db_session.add(listing_previo)
    db_session.flush()
    db_session.add(MarketplaceListingVariant(listing=listing_previo, variant=variante_a, price=5000, stock_quantity=5))
    db_session.commit()

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC000000B"}))

    res = client.post(
        f"/api/publicaciones/{variante_b.id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 409, res.text
    assert "MLC000000B" in res.json()["detail"]  # nunca se oculta el item_id real
    # Sigue existiendo solo el listing previo — la carrera no dejó un
    # segundo registro local silencioso.
    assert db_session.query(MarketplaceListing).count() == 1
    assert db_session.query(MarketplaceListingVariant).count() == 1


@respx.mock
def test_confirmar_con_atributos_obligatorios_faltantes_devuelve_400(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="FALTAN-ATRIB")  # sin barcode, sin COLOR

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic"},
    )

    assert res.status_code == 400
    assert "Color" in res.json()["detail"]
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_con_categoria_inexistente_devuelve_400(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="CAT-MALA-CONF")
    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC999999999/attributes").mock(
        return_value=httpx.Response(404, json={"message": "Category not found"})
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC999999999", "condition": "new", "listing_type": "classic"},
    )
    assert res.status_code == 400


@respx.mock
def test_confirmar_con_ml_rechazando_400_no_crea_ningun_registro(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-400", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(400, json={"message": "invalid price", "error": "bad_request"})
    )

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 400
    assert "invalid price" not in res.json()["detail"]  # nunca el JSON/mensaje crudo de ML
    assert ruta_items.calls.call_count == 1
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_con_ml_rechazando_precio_da_mensaje_especifico_de_precio(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """1 de septiembre de 2026 — antes siempre el mismo mensaje genérico;
    ahora distingue precio/categoría/atributos usando la causa real que
    manda Mercado Libre (domain/ml_error_messages.py), sin exponer el
    código interno ni el JSON crudo."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-PRECIO-INVALIDO", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(400, json={
        "cause": [{"department": "items", "cause_id": 111, "type": "error", "code": "item.price.invalid",
                    "references": ["item.price"], "message": "Currency Peso Chileno (CLP) does not support decimal precision."}],
        "message": "Validation error",
    }))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "El precio ingresado no es válido para esta publicación."
    assert "CLP" not in res.json()["detail"]  # nunca el mensaje crudo de Mercado Libre
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_con_ml_rechazando_atributos_da_mensaje_especifico_de_atributos(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-ATRIBUTO-INVALIDO", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(400, json={
        "cause": [{"department": "supply", "cause_id": 7711, "type": "error",
                    "code": "item.attribute.product_identifier.invalid_format",
                    "references": ["item.attributes[2].values"], "message": "Product Identifier [GTIN] contains values with invalid format: [cuaderno]."}],
        "message": "Validation error",
    }))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Faltan algunos datos obligatorios del producto. Revisá los atributos marcados."
    assert "GTIN" not in res.json()["detail"]
    assert "cuaderno" not in res.json()["detail"]


@respx.mock
def test_confirmar_con_ml_rechazando_autenticacion_no_crea_ningun_registro(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-403", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(403, json={"message": "forbidden"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 502
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_con_ml_caido_5xx_nunca_reintenta_y_no_crea_registro_fantasma(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-500", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(500, json={"message": "internal error"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 502
    assert ruta_items.calls.call_count == 1  # NUNCA reintenta un POST /items, ni siquiera con 500
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_con_timeout_de_ml_nunca_reintenta_y_no_asume_que_no_se_creo(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-TIMEOUT", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(side_effect=httpx.ConnectTimeout("se cortó la conexión"))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 502
    assert ruta_items.calls.call_count == 1  # un solo intento — nunca reintenta un timeout
    assert db_session.query(MarketplaceListing).count() == 0


@respx.mock
def test_confirmar_con_respuesta_de_ml_sin_item_id_no_persiste_nada(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="ML-SIN-ID", barcode="7891234567895")

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"status": "ok"}))  # sin "id"

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 502
    assert db_session.query(MarketplaceListing).count() == 0


def test_preparar_publicaciones_en_lote_arma_el_resumen(client, db_session, a_store):
    id_rentable = _producto(db_session, a_store, sku="R1", nombre="Producto rentable", marca="X", categoria="Y", precio=20000, costo=5000)
    id_no_rentable = _producto(db_session, a_store, sku="R2", nombre="Producto no rentable", marca="X", categoria="Y", precio=5000, costo=6000)
    id_inexistente = 999999

    res = client.post(
        "/api/publicaciones/preparar",
        json={"variant_ids": [id_rentable, id_no_rentable, id_inexistente], "requiere_stock": False},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["resumen"]["total"] == 2
    assert body["resumen"]["listosParaPublicar"] == 1
    assert body["resumen"]["noRecomendados"] == 1
    assert body["noEncontrados"] == [id_inexistente]


# ------------------------------------------------------------------
# 1 de septiembre de 2026 — hallazgo de qa-engineer (ronda de pulido):
# cada paso del flujo tenía tests aislados con fixtures propias, pero
# ningún test seguía UN MISMO producto de punta a punta (Rentabilidad ->
# Oportunidades -> Precio recomendado -> Decisión -> Preparar -> Confirmar)
# para probar que los números se reconcilian entre sí. Este es ese test.
# ------------------------------------------------------------------


@respx.mock
def test_flujo_completo_un_producto_da_los_mismos_numeros_en_cada_pantalla(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    # "Excel" -> producto publicable, con categoría de ML ya detectada.
    variant_id = _producto_publicable(db_session, a_store, sku="FLUJO-COMPLETO", precio=20000, costo=8000, barcode="7891234567895")
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    producto.ml_category_id = "MLC180937"
    db_session.commit()
    # Comisión real cacheada (10%) vs. manual absurda (50%) -- todo el
    # flujo debe usar la real, nunca la manual.
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=10.0)
    _configurar_canal_con_pref(db_session, a_store, commission_pct=50.0, listing_type_pref="classic")
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=15.0)
    # Mercado Libre no encuentra el producto en su catálogo de competencia
    # -- escenario real y legítimo (analisis_competencia.hay_competencia
    # queda False), no lo que este test evalúa; necesario para que
    # /precio-recomendado y /decision no fallen por request sin mockear.
    respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search.*").mock(return_value=httpx.Response(200, json={"results": []}))

    # 1. Rentabilidad -- margen al precio actual, comisión real.
    rentabilidad = client.get("/api/rentabilidad").json()
    fila = next(f for f in rentabilidad["productos"] if f["sku"] == "FLUJO-COMPLETO")
    assert fila["comisionMlFuente"] == "real"
    margen_ml_rentabilidad = fila["margenMercadoLibreClp"]
    assert margen_ml_rentabilidad == 20000 - 8000 - 2000  # 10% real de 20000, nunca el 50% manual

    # 2. Oportunidades (decision-lote) -- mismo precio recomendado que el endpoint individual.
    lote = client.get("/api/publicaciones/mercadolibre/decision-lote").json()
    fila_lote = next(f for f in lote if f["variantId"] == variant_id)

    # 3. Precio recomendado.
    precio = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    assert precio["comisionMlFuente"] == "real"
    assert precio["precioRecomendado"] == fila_lote["precioRecomendado"]

    # 4. Decisión -- misma comisión, mismo precio recomendado que el paso 3.
    decision = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision").json()
    assert decision["comisionMlFuente"] == "real"
    assert decision["precioRecomendado"] == precio["precioRecomendado"]
    assert decision["gananciaEstimada"] == precio["gananciaEstimada"]

    # 5. Preparar publicación -- mismo margen que Rentabilidad (paso 1),
    #    calculado al precio ACTUAL, no al recomendado.
    respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(return_value=httpx.Response(200, json=CATEGORIA_CUADERNOS_REAL))
    preparado = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/preparar").json()
    assert preparado["rentabilidad"]["comisionMlFuente"] == "real"
    assert preparado["rentabilidad"]["margenMercadoLibreClp"] == margen_ml_rentabilidad

    # 6. Confirmar -- publica al precio ACTUAL (20000), nunca al recomendado
    #    (que es distinto, ya que target_margin_pct=25% no es el margen real).
    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    ruta_items = respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"}))
    confirmar = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )
    assert confirmar.status_code == 200, confirmar.text
    payload_enviado = json.loads(ruta_items.calls[0].request.content)
    assert payload_enviado["price"] == 20000  # el precio actual, coherente con todas las pantallas de arriba


# ------------------------------------------------------------------
# 1 de septiembre de 2026 — gestión de una publicación ya creada: estado
# real / pausar / reactivar / eliminar. Mismo criterio de siempre: se
# consulta/actualiza Mercado Libre de verdad (mockeado acá), nunca se
# inventa un estado local.
# ------------------------------------------------------------------


def _publicar_variante_de_prueba(db_session, tienda, cuenta, *, sku, external_listing_id="MLC0000TEST", status="active"):
    variant_id = _producto_publicable(db_session, tienda, sku=sku)
    variante = db_session.query(ProductVariant).filter_by(id=variant_id).one()
    listing = MarketplaceListing(
        account=cuenta, product=variante.product, external_listing_id=external_listing_id, status=status, created_at=NOW
    )
    db_session.add(listing)
    db_session.flush()
    db_session.add(MarketplaceListingVariant(listing=listing, variant=variante, price=5000, stock_quantity=5))
    db_session.commit()
    return variant_id, listing.id


def test_estado_publicacion_sin_publicacion_previa_da_404(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto_publicable(db_session, a_store, sku="SIN-PUBLICAR")

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/publicacion")
    assert res.status_code == 404


@respx.mock
def test_estado_publicacion_consulta_en_vivo_y_sincroniza_estado_local(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """El estado guardado en Nexo puede haber quedado desactualizado
    (Mercado Libre pausó la publicación por su cuenta, ej. revisión de
    fotos) -- /publicacion siempre reconsulta y sincroniza, nunca confía
    ciegamente en `listing.status`."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="ESTADO-VIVO", status="active")

    respx.get("https://api.mercadolibre.com/items/MLC0000TEST").mock(
        return_value=httpx.Response(200, json={"id": "MLC0000TEST", "status": "paused", "permalink": "https://articulo.mercadolibre.cl/x"})
    )

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/publicacion")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "pausada"
    assert body["accionesDisponibles"] == ["reactivar", "eliminar"]
    assert body["permalink"] == "https://articulo.mercadolibre.cl/x"
    listing = db_session.get(MarketplaceListing, listing_id)
    assert listing.status == "paused"  # se sincronizó, ya no dice "active"


@respx.mock
def test_estado_publicacion_cuando_ml_ya_no_la_encuentra_da_desconocido(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """Caso real confirmado en la primera publicación real de Nexo: una
    cuenta sin "Listo para vender" completado puede terminar con un ítem
    que ya no es accesible (403/404) -- nunca se inventa que sigue activa."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, _listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="ESTADO-403", status="active")

    respx.get("https://api.mercadolibre.com/items/MLC0000TEST").mock(return_value=httpx.Response(403, json={"message": "forbidden"}))

    res = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/publicacion")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "desconocido"
    assert body["accionesDisponibles"] == []


@respx.mock
def test_pausar_publicacion_activa_la_pausa_en_mercado_libre(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="PAUSAR-OK", status="active")

    ruta_put = respx.put("https://api.mercadolibre.com/items/MLC0000TEST").mock(
        return_value=httpx.Response(200, json={"id": "MLC0000TEST", "status": "paused"})
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/pausar")

    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "pausada"
    assert res.json()["accionesDisponibles"] == ["reactivar", "eliminar"]
    assert json.loads(ruta_put.calls[0].request.content) == {"status": "paused"}
    assert db_session.get(MarketplaceListing, listing_id).status == "paused"


@respx.mock
def test_reactivar_publicacion_pausada_la_vuelve_a_activar(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="REACTIVAR-OK", status="paused")

    ruta_put = respx.put("https://api.mercadolibre.com/items/MLC0000TEST").mock(
        return_value=httpx.Response(200, json={"id": "MLC0000TEST", "status": "active"})
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/reactivar")

    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "activa"
    assert res.json()["accionesDisponibles"] == ["pausar", "eliminar"]
    assert json.loads(ruta_put.calls[0].request.content) == {"status": "active"}
    assert db_session.get(MarketplaceListing, listing_id).status == "active"


@respx.mock
def test_eliminar_publicacion_la_cierra_de_forma_terminal(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="ELIMINAR-OK", status="active")

    ruta_put = respx.put("https://api.mercadolibre.com/items/MLC0000TEST").mock(
        return_value=httpx.Response(200, json={"id": "MLC0000TEST", "status": "closed"})
    )

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/eliminar")

    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "eliminada"
    assert res.json()["accionesDisponibles"] == []  # terminal, ninguna acción más tiene sentido
    assert json.loads(ruta_put.calls[0].request.content) == {"status": "closed"}
    assert db_session.get(MarketplaceListing, listing_id).status == "closed"


@respx.mock
def test_pausar_publicacion_rechazada_por_ml_da_mensaje_amigable(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="PAUSAR-RECHAZADO", status="active")

    respx.put("https://api.mercadolibre.com/items/MLC0000TEST").mock(return_value=httpx.Response(400, json={
        "cause": [{"type": "error", "code": "item.status.invalid_transition", "message": "cannot pause a closed item"}],
    }))

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/pausar")

    assert res.status_code == 400
    assert "cannot pause" not in res.json()["detail"]  # nunca el mensaje crudo de Mercado Libre
    # No se actualizó el estado local con algo que Mercado Libre rechazó.
    assert db_session.get(MarketplaceListing, listing_id).status == "active"


def test_pausar_publicacion_de_otra_empresa_da_404(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    otro_usuario = User(email="otra-empresa-listing@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa B", store_name="Empresa B"))
    db_session.commit()
    cuenta_b = MarketplaceAccount(
        store=tienda_b, marketplace="mercadolibre", status="connected", external_account_id="999",
        external_account_site_id="MLC", connected_at=NOW,
        access_token_encrypted=encrypt_token("token-b", TEST_ENCRYPTION_KEY), refresh_token_encrypted=encrypt_token("refresh-b", TEST_ENCRYPTION_KEY),
        token_expires_at=datetime(2027, 1, 1),
    )
    db_session.add(cuenta_b)
    db_session.commit()
    variant_id_b, _listing_id = _publicar_variante_de_prueba(db_session, tienda_b, cuenta_b, sku="AISLADO-LISTING-B")

    with respx.mock:  # ningún request a ML debería salir: se bloquea antes por tenant
        res_estado = client.get(f"/api/publicaciones/{variant_id_b}/mercadolibre/publicacion")
        res_pausar = client.post(f"/api/publicaciones/{variant_id_b}/mercadolibre/pausar")

    assert res_estado.status_code == 404
    assert res_pausar.status_code == 404


@respx.mock
def test_confirmar_de_nuevo_despues_de_eliminada_reusa_la_fila_en_vez_de_bloquear_para_siempre(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """1 de septiembre de 2026 — hallazgo propio al construir "eliminar
    publicación": la UniqueConstraint(account_id, product_id) permite como
    máximo UNA fila por producto/cuenta, y el gate de duplicados de arriba
    bloqueaba con CUALQUIER estado salvo "not_published" -- una vez
    "closed" (eliminada desde Nexo), el dueño nunca podría volver a
    publicar este producto, aunque un vendedor real SÍ puede hacerlo en
    Mercado Libre después de cerrar una publicación."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="REPUBLICAR", external_listing_id="MLC0000TEST", status="closed")
    db_session.get(ProductVariant, variant_id).gtin_confirmado_ausente = True
    db_session.commit()

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC0000NUEVO", "user_product_id": "MLCU0000NUEVO"}))

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={
            "category_id": "MLC180937", "condition": "new", "listing_type": "classic",
            "attributes": {"COLOR": "Azul", "EMPTY_GTIN_REASON": "El producto no tiene código registrado"},
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["itemId"] == "MLC0000NUEVO"
    assert res.json()["status"] == "active"
    # Misma fila reusada (mismo listingId), nunca una segunda -- respeta
    # la UniqueConstraint(account_id, product_id) sin bloquear al dueño.
    assert res.json()["listingId"] == listing_id
    assert db_session.query(MarketplaceListing).count() == 1
    listing_actualizado = db_session.get(MarketplaceListing, listing_id)
    assert listing_actualizado.external_listing_id == "MLC0000NUEVO"
    assert listing_actualizado.status == "active"


@respx.mock
def test_confirmar_con_otra_variante_mientras_hay_una_activa_sigue_bloqueado_con_409(
    client, db_session, a_store, cuenta_ml_conectada, monkeypatch
):
    """Contraparte del test anterior: si la publicación existente sigue
    VIVA (no eliminada), publicar otra variante del mismo producto para la
    misma cuenta debe seguir bloqueado -- nunca se pisa una publicación
    real todavía activa."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id, _listing_id = _publicar_variante_de_prueba(db_session, a_store, cuenta_ml_conectada, sku="YA-ACTIVA", external_listing_id="MLC0000TEST", status="active")
    variante = db_session.get(ProductVariant, variant_id)
    variante_b = ProductVariant(
        product=variante.product, store_id=a_store.id, variant_sku="YA-ACTIVA-B", price=5000, cost_price=3000,
        marketplace_stock=5, barcode="7891234567895", created_at=NOW, updated_at=NOW,
    )
    db_session.add(variante_b)
    db_session.commit()

    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    respx.post("https://api.mercadolibre.com/items").mock(return_value=httpx.Response(201, json={"id": "MLC0000OTRA"}))

    res = client.post(
        f"/api/publicaciones/{variante_b.id}/mercadolibre/confirmar",
        json={"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}},
    )

    assert res.status_code == 409
    assert db_session.query(MarketplaceListing).count() == 1
