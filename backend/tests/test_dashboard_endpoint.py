"""
Pruebas end-to-end de GET /api/dashboard/resumen — mismo patrón que
test_catalogo_endpoints.py (SQLite en memoria, cliente FastAPI real).

Cada sección de la respuesta se prueba por separado: catálogo/stock,
rentabilidad, ventas importadas y estado de conexión con Mercado Libre —
nunca un número inventado, siempre calculado a partir de filas reales.
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
from app.db.models import MarketplaceAccount, Order, Product, ProductVariant, Store, StoreSettings, User
from app.db.session import get_db
from app.domain.security import hash_password
from app.main import app

NOW = datetime(2026, 8, 24, 12, 0, 0)


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
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda", low_stock_threshold=5))
    db_session.commit()
    return tienda


def _producto(db_session, tienda, *, sku, nombre, precio=None, costo=None, stock=None, gestiona=True):
    producto = Product(store=tienda, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    estado_stock = "instock" if (stock or 0) > 0 else "outofstock"
    variante = ProductVariant(
        product=producto, store_id=tienda.id, variant_sku=sku, price=precio, cost_price=costo,
        stock_quantity=stock, manage_stock=gestiona, stock_status=estado_stock, created_at=NOW, updated_at=NOW,
    )
    db_session.add(variante)
    db_session.commit()
    return variante


def test_dashboard_vacio_sin_productos_ni_ventas(client, a_store):
    body = client.get("/api/dashboard/resumen").json()

    assert body["catalogo"] == {"total": 0, "conStock": 0, "sinStock": 0, "stockBajo": 0, "alertasStockBajo": [], "alertasSinStock": []}
    assert body["rentabilidad"] == {"totalProductos": 0, "productosConCosto": 0, "productosRentables": None, "canalesConfigurados": []}
    assert body["ventas"] == {"pedidosImportados": 0, "pedidosUltimos30Dias": 0, "ultimaVentaImportada": None}
    assert body["mercadoLibre"]["conectado"] is False


def test_catalogo_cuenta_stock_bajo_y_agotado_segun_el_umbral_de_la_tienda(client, db_session, a_store):
    _producto(db_session, a_store, sku="A", nombre="Con stock normal", stock=50)
    _producto(db_session, a_store, sku="B", nombre="Stock bajo", stock=3)  # <= umbral (5)
    _producto(db_session, a_store, sku="C", nombre="Agotado", stock=0)
    _producto(db_session, a_store, sku="D", nombre="Por encargo", stock=None, gestiona=False)

    body = client.get("/api/dashboard/resumen").json()
    cat = body["catalogo"]

    assert cat["total"] == 4
    assert cat["stockBajo"] == 1
    assert cat["sinStock"] == 1
    assert [a["sku"] for a in cat["alertasStockBajo"]] == ["B"]
    assert [a["sku"] for a in cat["alertasSinStock"]] == ["C"]


def test_rentabilidad_distingue_sin_costo_de_cero_rentables(client, db_session, a_store):
    # Sin ningún producto con costo cargado: productosRentables debe ser
    # None (no calculable), nunca 0 (0 sugeriría "ninguno conviene").
    _producto(db_session, a_store, sku="X", nombre="Sin costo", precio=10000)
    body = client.get("/api/dashboard/resumen").json()
    assert body["rentabilidad"]["productosConCosto"] == 0
    assert body["rentabilidad"]["productosRentables"] is None


def test_rentabilidad_cuenta_solo_los_de_margen_positivo(client, db_session, a_store):
    _producto(db_session, a_store, sku="R1", nombre="Rentable", precio=10000, costo=6000)
    _producto(db_session, a_store, sku="R2", nombre="No rentable", precio=5000, costo=6000)  # margen negativo
    _producto(db_session, a_store, sku="R3", nombre="Sin costo", precio=8000)

    body = client.get("/api/dashboard/resumen").json()
    rent = body["rentabilidad"]
    assert rent["totalProductos"] == 3
    assert rent["productosConCosto"] == 2
    assert rent["productosRentables"] == 1


def test_ventas_cuenta_pedidos_importados_y_los_de_los_ultimos_30_dias(client, db_session, a_store):
    reciente = Order(
        store=a_store, channel="mercadolibre", external_order_id="1", order_date=datetime.now() - timedelta(days=2),
        status="completado", total_amount=10000, created_at=NOW, updated_at=NOW,
    )
    viejo = Order(
        store=a_store, channel="mercadolibre", external_order_id="2", order_date=datetime.now() - timedelta(days=90),
        status="completado", total_amount=5000, created_at=NOW, updated_at=NOW,
    )
    db_session.add_all([reciente, viejo])
    db_session.commit()

    body = client.get("/api/dashboard/resumen").json()
    ventas = body["ventas"]
    assert ventas["pedidosImportados"] == 2
    assert ventas["pedidosUltimos30Dias"] == 1
    assert ventas["ultimaVentaImportada"] is not None


def test_mercado_libre_refleja_la_cuenta_conectada_de_verdad(client, db_session, a_store):
    cuenta = MarketplaceAccount(
        store=a_store, marketplace="mercadolibre", status="connected", external_account_id="999",
        connected_at=NOW, last_checked_at=NOW,
    )
    db_session.add(cuenta)
    db_session.commit()

    body = client.get("/api/dashboard/resumen").json()
    assert body["mercadoLibre"]["conectado"] is True
    assert body["mercadoLibre"]["cuentaExternaId"] == "999"


def test_dashboard_sin_tienda_creada_no_revienta(client):
    # Sin app/db/seed_demo.py corrido todavía: no hay ninguna Store. El
    # dashboard tiene que responder con ceros, no un 404/500 — es la primera
    # pantalla que ve un dueño nuevo.
    res = client.get("/api/dashboard/resumen")
    assert res.status_code == 200
    assert res.json()["catalogo"]["total"] == 0
