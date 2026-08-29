"""
Pruebas end-to-end del catálogo respaldado por la base de datos
(app/api/routes/productos_db.py) — contra un cliente HTTP real de FastAPI,
con una base SQLite en memoria inyectada vía dependency_override (nunca
toca libreria_central.db, WooCommerce ni Mercado Libre).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import Product, ProductVariant, Store, StoreSettings, User
from app.db.session import get_db
from app.domain.security import hash_password
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
def a_store(db_session):
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
    return tienda


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
            manage_stock=True,
            stock_status="instock" if stock > 0 else "outofstock",
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


def test_listar_productos_vacio_devuelve_lista_vacia(client):
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


def test_obtener_producto_inexistente_devuelve_404(client):
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


def test_configurar_stock_ml_de_producto_inexistente_devuelve_404(client):
    res = client.put("/api/productos/999999/stock-mercadolibre", json={"cantidad": 5})
    assert res.status_code == 404


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


def test_configurar_costo_de_producto_inexistente_devuelve_404(client):
    res = client.put("/api/productos/999999/costo", json={"costo": 100})
    assert res.status_code == 404


def test_ruta_reporte_no_es_capturada_por_la_ruta_dinamica(client, monkeypatch):
    """Si /api/productos/{variant_id} se matcheara antes que la ruta literal
    /api/productos/reporte, FastAPI intentaría convertir "reporte" a int y
    esta request devolvería 422 — en vez de eso debe llegar al handler de
    WooCommerce y fallar con su 500 normal por falta de credenciales (sin
    llamar a la red real: se fuerzan credenciales vacías)."""
    monkeypatch.setattr(
        "app.api.routes.productos.get_settings",
        lambda: Settings(woocommerce_url="", woocommerce_consumer_key="", woocommerce_consumer_secret=""),
    )
    res = client.get("/api/productos/reporte")
    assert res.status_code == 500
    assert "WooCommerce" in res.json()["detail"]
