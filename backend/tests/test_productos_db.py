"""
Pruebas end-to-end del catálogo respaldado por la base de datos
(app/api/routes/productos_db.py) — contra un cliente HTTP real de FastAPI,
con una base SQLite en memoria inyectada vía dependency_override (nunca
toca nexo.db, WooCommerce ni Mercado Libre).
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
import httpx
import respx

from app.db.models import (
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingVariant,
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

NOW = datetime(2026, 8, 22, 12, 0, 0)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def db_session():
    # StaticPool: el endpoint corre en un hilo del threadpool de FastAPI
    # (las rutas son `def`, no `async def`), y un SQLite ":memory:" normal
    # es un motor distinto por conexión/hilo — sin esto, la ruta vería una
    # base vacía aunque el fixture ya haya creado las tablas.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
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
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def a_store(client, db_session):
    usuario = User(
        email="tienda@ejemplo.cl",
        password_hash=hash_password("no-se-usa-todavia"),
        full_name="Dueño de prueba",
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Tienda de prueba", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Tienda de prueba", store_name="Tienda de prueba"))
    db_session.commit()
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    return tienda


_TEST_KEY = "1zjb1QwlLnRZVODeUOZ7dEP9CzO2gxIx3vT-YQEbG9E="
_SETTINGS_ML = Settings(
    mercadolibre_client_id="test-client-id",
    mercadolibre_client_secret="test-client-secret",
    mercadolibre_redirect_uri="http://localhost:8000/api/mercadolibre/callback",
    token_encryption_key=_TEST_KEY,
)


def _variante_publicada_en_ml(db_session, tienda, *, sku, item_id, stock_ml):
    producto = Product(store=tienda, internal_sku=sku, name=f"Producto {sku}", product_type="simple", created_at=NOW, updated_at=NOW)
    variante = ProductVariant(product=producto, store_id=tienda.id, variant_sku=sku, price=10000, marketplace_stock=stock_ml, created_at=NOW, updated_at=NOW)
    cuenta = db_session.query(MarketplaceAccount).filter_by(store_id=tienda.id).first() or MarketplaceAccount(
        store=tienda, marketplace="mercadolibre", status="connected", external_account_id="555", external_account_site_id="MLC",
        access_token_encrypted=encrypt_token("token-de-prueba", _TEST_KEY), refresh_token_encrypted=encrypt_token("refresh", _TEST_KEY),
        token_expires_at=datetime(2027, 1, 1),
    )
    listing = MarketplaceListing(account=cuenta, product=producto, external_listing_id=item_id, status="paused", created_at=NOW)
    db_session.add_all([producto, variante, cuenta, listing])
    db_session.flush()
    db_session.add(MarketplaceListingVariant(listing=listing, variant=variante, stock_quantity=stock_ml))
    db_session.commit()
    return variante.id


@respx.mock
def test_cambiar_stock_ml_de_un_producto_publicado_actualiza_la_publicacion_real(client, db_session, a_store, monkeypatch):
    """14 de septiembre de 2026 — caso real: el stock reservado cambiaba en
    Nexo pero la publicación de Mercado Libre seguía con el viejo."""
    monkeypatch.setattr("app.api.routes.productos_db.get_settings", lambda: _SETTINGS_ML)
    variant_id = _variante_publicada_en_ml(db_session, a_store, sku="PUB-1", item_id="MLC2244564341", stock_ml=5)
    ruta = respx.put("https://api.mercadolibre.com/items/MLC2244564341").mock(return_value=httpx.Response(200, json={"id": "MLC2244564341", "available_quantity": 8}))

    res = client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": 8})

    assert res.status_code == 200, res.text
    assert res.json()["sincronizacionMl"] == {"publicacionesActualizadas": 1, "conError": 0}
    assert json.loads(ruta.calls[0].request.content) == {"available_quantity": 8}
    assert db_session.query(MarketplaceListingVariant).one().stock_quantity == 8


@respx.mock
def test_stock_ml_en_lote_actualiza_publicaciones_y_un_error_de_ml_no_deshace_nexo(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.productos_db.get_settings", lambda: _SETTINGS_ML)
    ok_id = _variante_publicada_en_ml(db_session, a_store, sku="PUB-OK", item_id="MLC1", stock_ml=1)
    falla_id = _variante_publicada_en_ml(db_session, a_store, sku="PUB-FALLA", item_id="MLC2", stock_ml=1)
    respx.put("https://api.mercadolibre.com/items/MLC1").mock(return_value=httpx.Response(200, json={"id": "MLC1"}))
    respx.put("https://api.mercadolibre.com/items/MLC2").mock(return_value=httpx.Response(400, json={"message": "item.available_quantity.invalid"}))

    res = client.put("/api/productos/stock-mercadolibre/lote", json={"variantIds": None, "cantidad": 3})

    assert res.status_code == 200, res.text
    assert res.json()["sincronizacionMl"] == {"publicacionesActualizadas": 1, "conError": 1}
    assert {v.id: v.marketplace_stock for v in db_session.query(ProductVariant).all()} == {ok_id: 3, falla_id: 3}
    # El rechazo de ML queda registrado para el admin (SyncJob/SyncLog), no solo en el log.
    from app.db.models import SyncJob

    job = db_session.query(SyncJob).one()
    assert (job.direction, job.status, job.products_affected) == ("ml_stock", "partial_error", 1)
    assert [log.variant_id for log in job.logs] == [falla_id]
    assert "MLC2" in job.logs[0].message and "item.available_quantity.invalid" in job.logs[0].message


def test_lista_de_productos_trae_costo_y_margen_de_venta_menos_compra(client, db_session, a_store):
    """14 de septiembre de 2026 — caso real (Excel con "Precio de Compra" y
    "Precio de Venta Recomendado"): la lista mostraba solo el precio, sin el
    costo ni el margen que el dueño cargó."""
    con_costo = Product(store=a_store, internal_sku="DEP-001", name="Zapatilla adidas F50", product_type="simple", created_at=NOW, updated_at=NOW)
    sin_costo = Product(store=a_store, internal_sku="SIN-COSTO", name="Producto sin costo", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add_all([con_costo, sin_costo])
    db_session.flush()
    db_session.add_all([
        ProductVariant(product=con_costo, store_id=a_store.id, variant_sku="DEP-001", price=74990, cost_price=45000, created_at=NOW, updated_at=NOW),
        ProductVariant(product=sin_costo, store_id=a_store.id, variant_sku="SIN-COSTO", price=10000, created_at=NOW, updated_at=NOW),
    ])
    db_session.commit()

    filas = {f["sku"]: f for f in client.get("/api/productos").json()}

    assert (filas["DEP-001"]["costo"], filas["DEP-001"]["margenClp"], filas["DEP-001"]["margenPct"]) == (45000.0, 29990.0, 39.99)
    # Sin costo cargado no se inventa ningún margen.
    assert (filas["SIN-COSTO"]["costo"], filas["SIN-COSTO"]["margenClp"], filas["SIN-COSTO"]["margenPct"]) == (None, None, None)


def _producto_simple(db_session, tienda, *, sku, nombre, precio, stock):
    producto = Product(
        store=tienda, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW
    )
    db_session.add(producto)
    db_session.flush()
    db_session.add(
        ProductVariant(
            product=producto,
            store_id=tienda.id,
            variant_sku=sku,
            price=precio,
            stock_quantity=stock,
            # `stock=None` = el producto no gestiona stock (caso real: un Excel
            # sin columna de stock). Los demas tests pasan un entero.
            manage_stock=stock is not None,
            stock_status="instock" if (stock or 0) > 0 else "outofstock",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.commit()
    return producto


def _producto_variable(db_session, tienda, *, nombre, colores_stock):
    producto = Product(
        store=tienda, internal_sku=None, name=nombre, product_type="variable", created_at=NOW, updated_at=NOW
    )
    db_session.add(producto)
    db_session.flush()
    for color, sku, stock in colores_stock:
        db_session.add(
            ProductVariant(
                product=producto,
                store_id=tienda.id,
                variant_sku=sku,
                variant_label=color,
                price=2490,
                stock_quantity=stock,
                manage_stock=True,
                stock_status="instock" if stock > 0 else "outofstock",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    db_session.commit()
    return producto


def test_listar_productos_vacio_devuelve_lista_vacia(client, a_store):
    res = client.get("/api/productos")
    assert res.status_code == 200
    assert res.json() == []


def test_producto_simple_devuelve_una_fila(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-001", nombre="Cien años de soledad", precio=12990, stock=34)

    res = client.get("/api/productos")
    assert res.status_code == 200
    filas = res.json()
    assert len(filas) == 1
    assert filas[0]["sku"] == "LIB-001"
    assert filas[0]["esVariante"] is False
    assert filas[0]["colorVariante"] is None
    assert filas[0]["stockQuantity"] == 34
    assert filas[0]["precio"] == 12990
    # Sin configurar todavía -> no se está ofreciendo por Mercado Libre.
    assert filas[0]["marketplaceStock"] is None
    # 6 de septiembre de 2026 — "estado claro de cada producto": nunca se
    # publicó -> None, nunca se inventa un estado.
    assert filas[0]["estadoPublicacionMercadoLibre"] is None


def test_producto_variable_devuelve_una_fila_por_color(client, db_session, a_store):
    _producto_variable(
        db_session,
        a_store,
        nombre="Cuaderno universitario",
        colores_stock=[("Azul", "CUA-001-AZU", 25), ("Rojo", "CUA-001-ROJ", 0)],
    )

    res = client.get("/api/productos")
    filas = res.json()
    assert len(filas) == 2
    assert {f["colorVariante"] for f in filas} == {"Azul", "Rojo"}
    assert all(f["esVariante"] for f in filas)
    sin_stock = next(f for f in filas if f["colorVariante"] == "Rojo")
    assert sin_stock["estadoStock"] == "outofstock"


def test_obtener_producto_por_id(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-002", nombre="Rayuela", precio=11490, stock=22)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.get(f"/api/productos/{variant_id}")
    assert res.status_code == 200
    assert res.json()["sku"] == "LIB-002"


def test_obtener_producto_inexistente_devuelve_404(client, a_store):
    res = client.get("/api/productos/999999")
    assert res.status_code == 404


def test_configurar_stock_mercado_libre_no_toca_el_stock_de_woocommerce(client, db_session, a_store):
    """El ejemplo del dueño: Producto X con stock físico desconocido y 5
    unidades reservadas para ML — stockQuantity (WooCommerce) y
    marketplaceStock son campos completamente separados."""
    _producto_simple(db_session, a_store, sku="LIB-006", nombre="Producto X", precio=9990, stock=999)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": 5})

    assert res.status_code == 200
    body = res.json()
    assert body["marketplaceStock"] == 5
    assert body["stockQuantity"] == 999  # intacto — no es lo mismo que el stock reservado para ML


def test_el_dueno_puede_cambiar_el_tope_varias_veces(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-007", nombre="Producto Y", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    for cantidad in (5, 10, 0):
        res = client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": cantidad})
        assert res.json()["marketplaceStock"] == cantidad


def test_poner_en_null_deja_de_ofrecer_por_ml(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-008", nombre="Producto Z", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": 5})

    res = client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": None})

    assert res.json()["marketplaceStock"] is None


def test_no_se_puede_configurar_un_tope_negativo(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-009", nombre="Producto W", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": -1})

    assert res.status_code == 400


def test_configurar_stock_ml_de_producto_inexistente_devuelve_404(client, a_store):
    res = client.put("/api/productos/999999/stock-mercadolibre", json={"cantidad": 5})
    assert res.status_code == 404


# ------------------------------------------------------------------
# PUT /stock-mercadolibre/lote — reservar en muchos a la vez (14 sep 2026).
# ------------------------------------------------------------------


def test_reservar_stock_ml_en_lote_a_todos(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="L1", nombre="A", precio=1000, stock=5)
    _producto_simple(db_session, a_store, sku="L2", nombre="B", precio=2000, stock=5)
    _producto_simple(db_session, a_store, sku="L3", nombre="C", precio=3000, stock=5)

    res = client.put("/api/productos/stock-mercadolibre/lote", json={"variantIds": None, "cantidad": 7})
    assert res.status_code == 200
    assert res.json()["actualizados"] == 3
    for v in db_session.query(ProductVariant).all():
        assert v.marketplace_stock == 7


def test_reservar_stock_ml_en_lote_solo_a_los_indicados(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="L1", nombre="A", precio=1000, stock=5)
    _producto_simple(db_session, a_store, sku="L2", nombre="B", precio=2000, stock=5)
    ids = [v.id for v in db_session.query(ProductVariant).order_by(ProductVariant.id).all()]

    res = client.put("/api/productos/stock-mercadolibre/lote", json={"variantIds": [ids[0]], "cantidad": 9})
    assert res.json()["actualizados"] == 1
    v0 = db_session.get(ProductVariant, ids[0])
    v1 = db_session.get(ProductVariant, ids[1])
    assert v0.marketplace_stock == 9
    assert v1.marketplace_stock is None


def test_lote_nunca_toca_productos_de_otra_empresa(client, db_session, a_store):
    """Aislamiento: aunque el body mande el variantId de OTRA empresa, no se
    toca — solo variantes de la tienda de la sesión."""
    _producto_simple(db_session, a_store, sku="MIO", nombre="Mío", precio=1000, stock=5)
    otro_usuario = User(email="otra-lote@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa B", store_name="Empresa B"))
    db_session.commit()
    _producto_simple(db_session, tienda_b, sku="AJENO", nombre="Ajeno", precio=1000, stock=5)
    ajena = db_session.query(ProductVariant).filter_by(store_id=tienda_b.id).one()

    res = client.put("/api/productos/stock-mercadolibre/lote", json={"variantIds": [ajena.id], "cantidad": 50})
    assert res.status_code == 200
    assert res.json()["actualizados"] == 0          # el id ajeno no matchea
    db_session.refresh(ajena)
    assert ajena.marketplace_stock is None          # intacto


def test_lote_stock_negativo_da_400(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="L1", nombre="A", precio=1000, stock=5)
    res = client.put("/api/productos/stock-mercadolibre/lote", json={"variantIds": None, "cantidad": -3})
    assert res.status_code == 400


def test_lote_sin_sesion_da_401(client):
    # `client` sin autenticar: no se llamó a `a_store` que pone la cookie.
    res = client.put("/api/productos/stock-mercadolibre/lote", json={"variantIds": None, "cantidad": 5})
    assert res.status_code == 401


# ------------------------------------------------------------------
# Eliminar producto (14 de septiembre de 2026)
# ------------------------------------------------------------------


def _variante_id(db_session, tienda):
    return db_session.query(ProductVariant).filter_by(store_id=tienda.id).first().id


def test_eliminar_producto_lo_saca_del_catalogo(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="DEL-1", nombre="Para borrar", precio=1000, stock=5)
    vid = _variante_id(db_session, a_store)

    res = client.delete(f"/api/productos/{vid}")
    assert res.status_code == 200
    assert res.json()["eliminado"] is True
    assert db_session.query(Product).count() == 0
    assert db_session.query(ProductVariant).count() == 0


def test_eliminar_producto_variable_borra_todas_sus_variantes(client, db_session, a_store):
    _producto_variable(db_session, a_store, nombre="Remera", colores_stock=[("Rojo", "R-R", 3), ("Azul", "R-A", 4)])
    vid = _variante_id(db_session, a_store)

    res = client.delete(f"/api/productos/{vid}")
    assert res.status_code == 200
    assert db_session.query(ProductVariant).count() == 0


def test_eliminar_producto_publicado_en_mercadolibre_da_409(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="PUB-1", nombre="Publicado", precio=1000, stock=5)
    cuenta = MarketplaceAccount(store=a_store, marketplace="mercadolibre", status="connected")
    db_session.add(cuenta)
    db_session.flush()
    db_session.add(
        MarketplaceListing(
            account=cuenta, product_id=producto.id, external_listing_id="MLC1", status="active", created_at=NOW
        )
    )
    db_session.commit()
    vid = _variante_id(db_session, a_store)

    res = client.delete(f"/api/productos/{vid}")
    assert res.status_code == 409
    assert "mercado libre" in res.json()["detail"].lower()
    assert db_session.query(Product).count() == 1   # sigue existiendo


def test_eliminar_producto_conserva_las_ventas_desvinculando(client, db_session, a_store):
    """Una venta ya registrada no se pierde al borrar el producto: el
    OrderItem se desvincula (variant_id -> None) pero conserva su SKU."""
    from app.db.models import Order, OrderItem

    producto = _producto_simple(db_session, a_store, sku="VEN-1", nombre="Vendido", precio=1000, stock=5)
    variante = producto.variants[0]
    orden = Order(
        store=a_store, channel="mercadolibre", external_order_id="O-1", order_date=NOW,
        total_amount=1000, created_at=NOW, updated_at=NOW,
    )
    db_session.add(orden)
    db_session.flush()
    db_session.add(
        OrderItem(order=orden, variant_id=variante.id, external_item_sku="VEN-1", quantity=1, unit_price=1000, created_at=NOW)
    )
    db_session.commit()
    vid = variante.id

    res = client.delete(f"/api/productos/{vid}")
    assert res.status_code == 200
    item = db_session.query(OrderItem).one()          # la venta sigue
    assert item.variant_id is None                    # desvinculada
    assert item.external_item_sku == "VEN-1"          # con su SKU intacto


def test_eliminar_producto_inexistente_da_404(client, a_store):
    assert client.delete("/api/productos/999999").status_code == 404


def test_no_se_puede_eliminar_producto_de_otra_empresa(client, db_session, a_store):
    otro = User(email="otra-del@ejemplo.cl", password_hash=hash_password("x"), full_name="B", created_at=NOW, updated_at=NOW)
    db_session.add(otro)
    tienda_b = Store(owner=otro, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="B", store_name="B"))
    db_session.commit()
    _producto_simple(db_session, tienda_b, sku="AJENO", nombre="Ajeno", precio=1000, stock=5)
    ajena = db_session.query(ProductVariant).filter_by(store_id=tienda_b.id).one()

    res = client.delete(f"/api/productos/{ajena.id}")
    assert res.status_code == 404                      # IDOR -> 404, nunca 403
    assert db_session.query(Product).filter_by(store_id=tienda_b.id).count() == 1


def test_agregar_costo_a_un_producto_puntual(client, db_session, a_store):
    """Cierra el flujo de Oportunidades: completar el costo de UN producto
    sin volver a subir el catálogo entero por Excel."""
    _producto_simple(db_session, a_store, sku="LIB-010", nombre="Producto sin costo", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/costo", json={"costo": 6000})

    assert res.status_code == 200
    variante = db_session.get(ProductVariant, variant_id)
    assert float(variante.cost_price) == 6000

    # El margen ya se recalcula solo con el mismo dato, sin duplicar lógica.
    rentabilidad = client.get("/api/rentabilidad").json()
    fila = next(f for f in rentabilidad["productos"] if f["id"] == variant_id)
    assert fila["tieneCosto"] is True
    assert fila["margenTiendaClp"] == 4000


def test_borrar_el_costo_lo_deja_sin_datos_no_en_cero(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-011", nombre="Producto con costo", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id
    client.put(f"/api/productos/{variant_id}/costo", json={"costo": 6000})

    res = client.put(f"/api/productos/{variant_id}/costo", json={"costo": None})

    assert res.status_code == 200
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.cost_price is None


def test_no_se_puede_cargar_un_costo_negativo(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="LIB-012", nombre="Producto", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/costo", json={"costo": -100})

    assert res.status_code == 400


def test_configurar_costo_de_producto_inexistente_devuelve_404(client, a_store):
    res = client.put("/api/productos/999999/costo", json={"costo": 100})
    assert res.status_code == 404


# ------------------------------------------------------------------
# PUT /{variant_id}/stock — 13 de septiembre de 2026. La mayoria de los
# Excel reales solo traen codigo, nombre, costo y precio: sin este endpoint
# el stock quedaba en None para siempre, sin forma de corregirlo desde la
# aplicacion.
# ------------------------------------------------------------------


def test_cargar_stock_a_mano_en_un_producto_que_no_lo_traia(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="STK-001", nombre="Producto sin stock", precio=10000, stock=None)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/stock", json={"cantidad": 12})

    assert res.status_code == 200
    assert res.json()["stockQuantity"] == 12
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.stock_quantity == 12
    assert variante.manage_stock is True
    assert variante.stock_status == "instock"


def test_stock_en_cero_queda_sin_stock_pero_sigue_gestionando(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="STK-002", nombre="Producto", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/stock", json={"cantidad": 0})

    assert res.status_code == 200
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.stock_quantity == 0
    assert variante.manage_stock is True          # 0 no es "no gestiona stock"
    assert variante.stock_status == "outofstock"


def test_vaciar_el_stock_significa_que_no_se_gestiona(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="STK-003", nombre="Producto", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/stock", json={"cantidad": None})

    assert res.status_code == 200
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.stock_quantity is None
    assert variante.manage_stock is False


def test_no_se_puede_cargar_un_stock_negativo(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="STK-004", nombre="Producto", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/stock", json={"cantidad": -3})

    assert res.status_code == 400


def test_cambiar_el_stock_no_toca_el_reservado_para_mercado_libre(client, db_session, a_store):
    """Son dos numeros separados a proposito (ver domain/marketplace_stock.py)."""
    _producto_simple(db_session, a_store, sku="STK-005", nombre="Producto", precio=10000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id
    client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": 3})

    client.put(f"/api/productos/{variant_id}/stock", json={"cantidad": 40})

    variante = db_session.get(ProductVariant, variant_id)
    assert variante.stock_quantity == 40
    assert variante.marketplace_stock == 3


def test_configurar_stock_de_producto_inexistente_devuelve_404(client, a_store):
    res = client.put("/api/productos/999999/stock", json={"cantidad": 5})
    assert res.status_code == 404


# ------------------------------------------------------------------
# PUT /{variant_id}/codigo-barras — 30 de agosto de 2026, distingue Caso
# A/B/C/D de GTIN (ver PUBLICACION_MERCADOLIBRE.md).
# ------------------------------------------------------------------


def test_producto_sin_gtin_cargado_queda_en_datos_incompletos(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="GTIN-001", nombre="Producto nuevo", precio=5000, stock=5)
    res = client.get("/api/productos")
    assert res.json()[0]["estadoGtin"] == "datos_incompletos"
    assert res.json()[0]["codigoBarras"] is None


def test_cargar_un_gtin_valido_queda_como_valido(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="GTIN-002", nombre="Producto", precio=5000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/codigo-barras", json={"barcode": "9788883701122"})

    assert res.status_code == 200
    assert res.json()["codigoBarras"] == "9788883701122"
    assert res.json()["estadoGtin"] == "valido"


def test_cargar_un_gtin_con_checksum_invalido_es_rechazado(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="GTIN-003", nombre="Producto", precio=5000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/codigo-barras", json={"barcode": "8058647628161"})

    assert res.status_code == 400
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.barcode is None  # nunca se guarda un código inválido


def test_confirmar_sin_codigo_marca_el_estado_correspondiente(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="GTIN-004", nombre="Producto artesanal", precio=5000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.put(f"/api/productos/{variant_id}/codigo-barras", json={"confirmarSinCodigo": True})

    assert res.status_code == 200
    assert res.json()["codigoBarras"] is None
    assert res.json()["estadoGtin"] == "sin_codigo_confirmado"
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.gtin_confirmado_ausente is True


def test_cargar_un_gtin_real_despues_de_haber_confirmado_que_no_tenia_lo_reemplaza(client, db_session, a_store):
    """Si después aparece el código real, cargarlo vuelve a dejar el
    producto en estado "válido" — no se queda pegado en "confirmado sin
    código"."""
    _producto_simple(db_session, a_store, sku="GTIN-005", nombre="Producto", precio=5000, stock=5)
    variant_id = db_session.query(ProductVariant).one().id
    client.put(f"/api/productos/{variant_id}/codigo-barras", json={"confirmarSinCodigo": True})

    res = client.put(f"/api/productos/{variant_id}/codigo-barras", json={"barcode": "9788883701122"})

    assert res.json()["estadoGtin"] == "valido"
    variante = db_session.get(ProductVariant, variant_id)
    assert variante.gtin_confirmado_ausente is False


def test_configurar_codigo_barras_de_producto_inexistente_devuelve_404(client, a_store):
    res = client.put("/api/productos/999999/codigo-barras", json={"barcode": "9788883701122"})
    assert res.status_code == 404


def test_ruta_reporte_no_es_capturada_por_la_ruta_dinamica(client, a_store, monkeypatch):
    """Si /api/productos/{variant_id} se matcheara antes que la ruta literal
    /api/productos/reporte, FastAPI intentaría convertir "reporte" a int y
    esta request devolvería 422 — en vez de eso debe llegar al handler de
    WooCommerce y fallar con su 500 normal por falta de credenciales (sin
    llamar a la red real: se fuerzan credenciales vacías). Necesita
    woocommerce_legacy_store_id apuntando a ESTA tienda — si no, el nuevo
    gate de tienda (30 de agosto de 2026) devuelve 404 antes de llegar acá."""
    monkeypatch.setattr(
        "app.api.routes.productos.get_settings",
        lambda: Settings(
            woocommerce_url="", woocommerce_consumer_key="", woocommerce_consumer_secret="",
            woocommerce_legacy_store_id=a_store.id,
        ),
    )
    res = client.get("/api/productos/reporte")
    assert res.status_code == 500
    assert "WooCommerce" in res.json()["detail"]


def test_reporte_sin_legacy_store_id_configurado_da_404_para_cualquier_tienda(client, a_store, monkeypatch):
    """30 de agosto de 2026 — hallazgo de security-engineer: sin este
    setting, el endpoint queda deshabilitado para TODAS las tiendas (nunca
    un fallback abierto por accidente)."""
    monkeypatch.setattr(
        "app.api.routes.productos.get_settings",
        lambda: Settings(woocommerce_url="", woocommerce_consumer_key="", woocommerce_consumer_secret=""),
    )
    res = client.get("/api/productos/reporte")
    assert res.status_code == 404


def test_reporte_de_una_tienda_distinta_a_la_legacy_da_404(client, a_store, monkeypatch):
    """Empresa real, pero no es la única autorizada al catálogo WooCommerce
    global — nunca ve el catálogo de otra empresa."""
    monkeypatch.setattr(
        "app.api.routes.productos.get_settings",
        lambda: Settings(
            woocommerce_url="", woocommerce_consumer_key="", woocommerce_consumer_secret="",
            woocommerce_legacy_store_id=a_store.id + 999,
        ),
    )
    res = client.get("/api/productos/reporte")
    assert res.status_code == 404


# ------------------------------------------------------------------
# 1 de septiembre de 2026 — CRUD real de imágenes (agregar por URL,
# eliminar, reordenar). 5 de septiembre de 2026 — se suma la subida real
# desde el computador (ver app/domain/image_storage.py y los tests de
# subir_imagenes más abajo); el CRUD por URL de acá sigue existiendo tal
# cual (por ejemplo, para pegar la URL de una imagen ya alojada afuera).
# ------------------------------------------------------------------


def test_obtener_producto_incluye_imagenes_en_orden_con_la_principal_marcada(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="IMG-001", nombre="Producto con imágenes", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    db_session.add(ProductImage(product=producto, url="http://cdn.test/a.png", source="excel_url", position=0, created_at=NOW))
    db_session.add(ProductImage(product=producto, url="http://cdn.test/b.png", source="excel_url", position=1, created_at=NOW))
    db_session.commit()

    body = client.get(f"/api/productos/{variant_id}").json()

    assert [img["url"] for img in body["imagenes"]] == ["http://cdn.test/a.png", "http://cdn.test/b.png"]
    assert body["imagenes"][0]["principal"] is True
    assert body["imagenes"][1]["principal"] is False


def test_agregar_imagen_la_suma_al_final_y_no_toca_las_anteriores(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="IMG-002", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    db_session.add(ProductImage(product=producto, url="http://cdn.test/a.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()

    res = client.post(f"/api/productos/{variant_id}/imagenes", json={"url": "https://cdn.test/b.png"})

    assert res.status_code == 200, res.text
    urls = [img["url"] for img in res.json()["imagenes"]]
    assert urls == ["http://cdn.test/a.png", "https://cdn.test/b.png"]
    assert res.json()["imagenes"][0]["principal"] is True  # la primera nunca se movió


def test_agregar_imagen_a_producto_sin_ninguna_queda_como_principal(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="IMG-003", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.post(f"/api/productos/{variant_id}/imagenes", json={"url": "https://cdn.test/unica.png"})

    assert res.status_code == 200, res.text
    assert res.json()["imagenes"] == [{"id": res.json()["imagenes"][0]["id"], "url": "https://cdn.test/unica.png", "principal": True}]


@pytest.mark.parametrize("url_invalida", ["", "   ", "ftp://cdn.test/a.png", "cdn.test/a.png"])
def test_agregar_imagen_con_url_invalida_da_400(client, db_session, a_store, url_invalida):
    _producto_simple(db_session, a_store, sku="IMG-004", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.post(f"/api/productos/{variant_id}/imagenes", json={"url": url_invalida})

    assert res.status_code == 400


def test_eliminar_imagen_reordena_y_la_siguiente_pasa_a_ser_principal(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="IMG-005", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    img_a = ProductImage(product=producto, url="http://cdn.test/a.png", source="excel_url", position=0, created_at=NOW)
    img_b = ProductImage(product=producto, url="http://cdn.test/b.png", source="excel_url", position=1, created_at=NOW)
    db_session.add_all([img_a, img_b])
    db_session.commit()

    res = client.delete(f"/api/productos/{variant_id}/imagenes/{img_a.id}")

    assert res.status_code == 200, res.text
    assert res.json()["imagenes"] == [{"id": img_b.id, "url": "http://cdn.test/b.png", "principal": True}]


def test_eliminar_imagen_inexistente_da_404(client, db_session, a_store):
    _producto_simple(db_session, a_store, sku="IMG-006", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.delete(f"/api/productos/{variant_id}/imagenes/999999")
    assert res.status_code == 404


def test_reordenar_imagenes_cambia_cual_es_la_principal(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="IMG-007", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    img_a = ProductImage(product=producto, url="http://cdn.test/a.png", source="excel_url", position=0, created_at=NOW)
    img_b = ProductImage(product=producto, url="http://cdn.test/b.png", source="excel_url", position=1, created_at=NOW)
    db_session.add_all([img_a, img_b])
    db_session.commit()

    res = client.put(f"/api/productos/{variant_id}/imagenes/orden", json={"orden": [img_b.id, img_a.id]})

    assert res.status_code == 200, res.text
    assert [img["url"] for img in res.json()["imagenes"]] == ["http://cdn.test/b.png", "http://cdn.test/a.png"]
    assert res.json()["imagenes"][0]["principal"] is True


def test_reordenar_imagenes_con_ids_que_no_coinciden_da_400(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="IMG-008", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    img_a = ProductImage(product=producto, url="http://cdn.test/a.png", source="excel_url", position=0, created_at=NOW)
    db_session.add(img_a)
    db_session.commit()

    res = client.put(f"/api/productos/{variant_id}/imagenes/orden", json={"orden": [img_a.id, 999999]})
    assert res.status_code == 400


def test_gestion_de_imagenes_de_producto_de_otra_empresa_da_404(client, db_session, a_store):
    otro_usuario = User(email="otra-empresa-img@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa B", store_name="Empresa B"))
    db_session.commit()
    producto_b = _producto_simple(db_session, tienda_b, sku="IMG-B-001", nombre="Producto de B", precio=5000, stock=10)
    img_b = ProductImage(product=producto_b, url="http://cdn.test/b.png", source="excel_url", position=0, created_at=NOW)
    db_session.add(img_b)
    db_session.commit()
    variant_id_b = db_session.query(ProductVariant).filter_by(product_id=producto_b.id).one().id

    # a_store sigue siendo la sesión autenticada acá (el fixture autentica
    # al crearse) -- nunca ve ni puede tocar las imágenes de la empresa B.
    assert client.post(f"/api/productos/{variant_id_b}/imagenes", json={"url": "https://cdn.test/x.png"}).status_code == 404
    assert client.delete(f"/api/productos/{variant_id_b}/imagenes/{img_b.id}").status_code == 404
    assert client.put(f"/api/productos/{variant_id_b}/imagenes/orden", json={"orden": [img_b.id]}).status_code == 404


# ------------------------------------------------------------------
# 5 de septiembre de 2026 — subida real de imágenes desde el computador
# (click o drag & drop en el frontend, ver app/domain/image_storage.py).
# Guarda en disco (tmp_path acá, nunca la carpeta real de dev) y sirve la
# URL absoluta con settings.backend_public_base_url.
# ------------------------------------------------------------------


def _png_valido(color=(255, 0, 0)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def settings_de_upload(monkeypatch, tmp_path):
    settings = Settings(uploads_dir=str(tmp_path), backend_public_base_url="http://testserver")
    monkeypatch.setattr("app.api.routes.productos_db.get_settings", lambda: settings)
    return settings


def test_subir_una_imagen_valida_la_guarda_y_la_asocia_al_producto(client, db_session, a_store, settings_de_upload):
    _producto_simple(db_session, a_store, sku="UP-001", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[("files", ("foto.png", _png_valido(), "image/png"))],
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subidas"]["guardadas"] == 1
    assert body["subidas"]["rechazadas"] == []
    assert len(body["imagenes"]) == 1
    url = body["imagenes"][0]["url"]
    assert url.startswith("http://testserver/uploads/product_images/")
    nombre_archivo = url.rsplit("/", 1)[-1]
    assert (Path(settings_de_upload.uploads_dir) / "product_images" / str(a_store.id) / nombre_archivo).exists()


def test_subir_varias_imagenes_a_la_vez(client, db_session, a_store, settings_de_upload):
    _producto_simple(db_session, a_store, sku="UP-002", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[
            ("files", ("a.png", _png_valido((255, 0, 0)), "image/png")),
            ("files", ("b.png", _png_valido((0, 255, 0)), "image/png")),
        ],
    )
    assert res.status_code == 200, res.text
    assert res.json()["subidas"]["guardadas"] == 2
    assert len(res.json()["imagenes"]) == 2


def test_subir_archivo_corrupto_es_rechazado_sin_romper_los_demas(client, db_session, a_store, settings_de_upload):
    _producto_simple(db_session, a_store, sku="UP-003", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    res = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[
            ("files", ("bueno.png", _png_valido(), "image/png")),
            ("files", ("malo.png", b"esto no es una imagen de verdad", "image/png")),
        ],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subidas"]["guardadas"] == 1
    assert len(body["subidas"]["rechazadas"]) == 1
    assert body["subidas"]["rechazadas"][0]["archivo"] == "malo.png"
    # Mensaje simple, nunca técnico (nunca "corrupto"/"UnidentifiedImageError").
    assert "imagen" in body["subidas"]["rechazadas"][0]["motivo"].lower()


def test_subir_formato_no_soportado_es_rechazado(client, db_session, a_store, settings_de_upload):
    _producto_simple(db_session, a_store, sku="UP-004", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id

    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="GIF")
    res = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[("files", ("animado.gif", buffer.getvalue(), "image/gif"))],
    )
    assert res.status_code == 200, res.text
    assert res.json()["subidas"]["guardadas"] == 0
    # Mismo mensaje simple para formato inválido que para tamaño excedido
    # (ver domain/image_storage.py::MENSAJE_REQUISITOS) — nunca el nombre
    # técnico del formato detectado.
    assert "JPG" in res.json()["subidas"]["rechazadas"][0]["motivo"]


def test_subir_imagen_demasiado_grande_es_rechazada(client, db_session, a_store, settings_de_upload, monkeypatch):
    _producto_simple(db_session, a_store, sku="UP-005", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    monkeypatch.setattr("app.domain.image_storage.TAMANO_MAXIMO_BYTES", 10)

    res = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[("files", ("grande.png", _png_valido(), "image/png"))],
    )
    assert res.status_code == 200, res.text
    assert res.json()["subidas"]["guardadas"] == 0
    assert "MB" in res.json()["subidas"]["rechazadas"][0]["motivo"]


def test_subir_respeta_el_maximo_de_imagenes_por_producto(client, db_session, a_store, settings_de_upload, monkeypatch):
    producto = _producto_simple(db_session, a_store, sku="UP-006", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    monkeypatch.setattr("app.api.routes.productos_db.MAX_IMAGENES_POR_PRODUCTO", 1)
    db_session.add(ProductImage(product=producto, url="http://cdn.test/ya-existe.png", source="excel_url", position=0, created_at=NOW))
    db_session.commit()

    res = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[("files", ("nueva.png", _png_valido(), "image/png"))],
    )
    assert res.status_code == 200, res.text
    assert res.json()["subidas"]["guardadas"] == 0
    assert "máximo" in res.json()["subidas"]["rechazadas"][0]["motivo"].lower()


def test_subir_imagen_a_producto_de_otra_empresa_da_404(client, db_session, a_store, settings_de_upload):
    otro_usuario = User(email="otra-upload@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa Upload B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa Upload B", store_name="Empresa Upload B"))
    db_session.commit()
    producto_b = _producto_simple(db_session, tienda_b, sku="UP-B-001", nombre="Producto de B", precio=5000, stock=10)
    variant_id_b = db_session.query(ProductVariant).filter_by(product_id=producto_b.id).one().id

    res = client.post(
        f"/api/productos/{variant_id_b}/imagenes/upload",
        files=[("files", ("x.png", _png_valido(), "image/png"))],
    )
    assert res.status_code == 404


def test_eliminar_imagen_subida_borra_tambien_el_archivo_fisico(client, db_session, a_store, settings_de_upload):
    _producto_simple(db_session, a_store, sku="UP-007", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    subida = client.post(
        f"/api/productos/{variant_id}/imagenes/upload",
        files=[("files", ("borrame.png", _png_valido(), "image/png"))],
    ).json()
    image_id = subida["imagenes"][0]["id"]
    url = subida["imagenes"][0]["url"]
    nombre_archivo = url.rsplit("/", 1)[-1]
    ruta_fisica = Path(settings_de_upload.uploads_dir) / "product_images" / str(a_store.id) / nombre_archivo
    assert ruta_fisica.exists()

    res = client.delete(f"/api/productos/{variant_id}/imagenes/{image_id}")
    assert res.status_code == 200, res.text
    assert not ruta_fisica.exists()


def test_eliminar_imagen_por_url_externa_nunca_intenta_borrar_nada_en_disco(client, db_session, a_store, settings_de_upload):
    """Una imagen cargada por URL (no subida desde el computador) no tiene
    ningún archivo propio en disco -- eliminar_archivo_si_es_local no debe
    romper ni intentar borrar nada fuera de uploads_dir."""
    producto = _producto_simple(db_session, a_store, sku="UP-008", nombre="Producto", precio=5000, stock=10)
    variant_id = db_session.query(ProductVariant).one().id
    img = ProductImage(product=producto, url="https://cdn-externo.test/foto.png", source="excel_url", position=0, created_at=NOW)
    db_session.add(img)
    db_session.commit()

    res = client.delete(f"/api/productos/{variant_id}/imagenes/{img.id}")
    assert res.status_code == 200, res.text


# ------------------------------------------------------------------
# 6 de septiembre de 2026 — "estado claro de cada producto" (automatización
# comercial): la lista de productos ahora trae el estado real de
# publicación en Mercado Libre (active/paused/closed/None), sin tener que
# entrar al detalle de cada uno. Una sola consulta agregada, nunca una por
# fila — ver _estado_publicacion_por_producto.
# ------------------------------------------------------------------


def _cuenta_ml(db_session, tienda, *, external_account_id="1"):
    cuenta = MarketplaceAccount(store=tienda, marketplace="mercadolibre", status="connected", external_account_id=external_account_id)
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


def test_listar_productos_incluye_el_estado_real_de_publicacion(client, db_session, a_store):
    producto = _producto_simple(db_session, a_store, sku="ML-PUB-1", nombre="Publicado", precio=5000, stock=5)
    otro_producto = _producto_simple(db_session, a_store, sku="ML-PUB-2", nombre="Pausado", precio=5000, stock=5)
    cuenta = _cuenta_ml(db_session, a_store)
    db_session.add(MarketplaceListing(account=cuenta, product=producto, status="active", price=5000, created_at=NOW))
    db_session.add(MarketplaceListing(account=cuenta, product=otro_producto, status="paused", price=5000, created_at=NOW))
    db_session.commit()

    filas = {f["sku"]: f["estadoPublicacionMercadoLibre"] for f in client.get("/api/productos").json()}
    assert filas["ML-PUB-1"] == "active"
    assert filas["ML-PUB-2"] == "paused"


def test_estado_de_publicacion_de_otra_empresa_nunca_aparece(client, db_session, a_store):
    """Aislamiento: el estado de publicación se calcula por tienda — el
    producto de otra empresa nunca debería contaminar esta lista (ni
    siquiera compartiendo el mismo product_id por coincidencia de IDs)."""
    otro_usuario = User(email="otra-estado-ml@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa Estado ML B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa Estado ML B", store_name="Empresa Estado ML B"))
    db_session.commit()
    producto_b = _producto_simple(db_session, tienda_b, sku="ML-PUB-B", nombre="De otra empresa", precio=5000, stock=5)
    cuenta_b = _cuenta_ml(db_session, tienda_b, external_account_id="999")
    db_session.add(MarketplaceListing(account=cuenta_b, product=producto_b, status="active", price=5000, created_at=NOW))
    db_session.commit()

    _producto_simple(db_session, a_store, sku="ML-PUB-MIA", nombre="Mi producto", precio=5000, stock=5)

    filas = client.get("/api/productos").json()
    assert len(filas) == 1
    assert filas[0]["estadoPublicacionMercadoLibre"] is None
