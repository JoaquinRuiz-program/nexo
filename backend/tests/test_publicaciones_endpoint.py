"""
Pruebas end-to-end de /api/publicaciones/* — el "borrador de publicación"
en modo simulación, contra datos reales en una base SQLite en memoria.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import MarketplaceAccount, Product, ProductImage, ProductVariant, Store, StoreSettings, User
from app.db.session import get_db
from app.domain.security import hash_password
from tests.auth_helpers import autenticar
from app.main import app
from app.config import Settings

NOW = datetime(2026, 8, 24, 12, 0, 0)

CONFIGURED_SETTINGS = Settings(
    mercadolibre_client_id="test-client-id",
    mercadolibre_client_secret="test-client-secret",
    mercadolibre_redirect_uri="http://localhost:8000/api/mercadolibre/callback",
    mercadolibre_auth_domain="auth.mercadolibre.cl",
    token_encryption_key="no-se-usa-en-estos-tests",
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
    )
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


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


@respx.mock
def test_preparar_sin_categoria_previa_predice_una_nueva(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    variant_id = _producto(db_session, a_store, sku="SIN-CAT", nombre="Cuaderno universitario", marca="Torre", categoria="Papelería", precio=5000, costo=3000)

    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
    )

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
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="CON-EAN", price=5000, cost_price=3000, barcode="7891234567890", created_at=NOW, updated_at=NOW))
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
