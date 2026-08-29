"""
Pruebas end-to-end de GET /api/seleccion — "¿qué conviene publicar en
Mercado Libre?" contra datos reales en una base SQLite en memoria.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Product, ProductVariant, Store, StoreSettings, User
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
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda"))
    db_session.commit()
    return tienda


def _producto(db_session, tienda, *, sku, precio, costo=None, marketplace_stock=None):
    producto = Product(store=tienda, internal_sku=sku, name=f"Producto {sku}", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(
        ProductVariant(
            product=producto, store_id=tienda.id, variant_sku=sku, price=precio, cost_price=costo,
            marketplace_stock=marketplace_stock, created_at=NOW, updated_at=NOW,
        )
    )
    db_session.commit()


def test_seleccion_vacia_sin_productos(client, a_store):
    res = client.get("/api/seleccion")
    assert res.status_code == 200
    assert res.json()["resumen"]["total"] == 0


def test_clasifica_rentable_no_rentable_sin_stock_y_sin_datos(client, db_session, a_store):
    _producto(db_session, a_store, sku="A", precio=20000, costo=5000, marketplace_stock=3)  # rentable
    _producto(db_session, a_store, sku="B", precio=5000, costo=6000, marketplace_stock=3)  # no_rentable
    _producto(db_session, a_store, sku="C", precio=10000, costo=5000, marketplace_stock=0)  # sin_stock
    _producto(db_session, a_store, sku="D", precio=10000, marketplace_stock=3)  # sin costo -> sin_datos

    body = client.get("/api/seleccion").json()
    por_sku = {p["sku"]: p["clasificacion"] for p in body["productos"]}
    assert por_sku == {"A": "rentable", "B": "no_rentable", "C": "sin_stock", "D": "sin_datos"}
    assert body["resumen"] == {
        "total": 4, "rentables": 1, "margenBajo": 0, "noRentables": 1,
        "sinStock": 1, "sinDatos": 1, "noSeleccionados": 0,
    }


def test_filtro_margen_minimo_en_pesos(client, db_session, a_store):
    _producto(db_session, a_store, sku="ALTO", precio=20000, costo=5000, marketplace_stock=1)  # margen 15000
    _producto(db_session, a_store, sku="BAJO", precio=6000, costo=5000, marketplace_stock=1)  # margen 1000

    body = client.get("/api/seleccion", params={"margen_minimo_clp": 5000}).json()
    por_sku = {p["sku"]: p["clasificacion"] for p in body["productos"]}
    assert por_sku["ALTO"] == "rentable"
    assert por_sku["BAJO"] == "margen_bajo"


def test_filtro_top_n(client, db_session, a_store):
    _producto(db_session, a_store, sku="A", precio=20000, costo=5000, marketplace_stock=1)  # margen 15000
    _producto(db_session, a_store, sku="B", precio=15000, costo=5000, marketplace_stock=1)  # margen 10000
    _producto(db_session, a_store, sku="C", precio=10000, costo=5000, marketplace_stock=1)  # margen 5000

    body = client.get("/api/seleccion", params={"top": 2}).json()
    por_sku = {p["sku"]: p["clasificacion"] for p in body["productos"]}
    assert por_sku["A"] == "rentable"
    assert por_sku["B"] == "rentable"
    assert por_sku["C"] == "no_seleccionado"


def test_requiere_stock_se_puede_desactivar(client, db_session, a_store):
    _producto(db_session, a_store, sku="A", precio=20000, costo=5000, marketplace_stock=None)

    con_requisito = client.get("/api/seleccion").json()
    sin_requisito = client.get("/api/seleccion", params={"requiere_stock": "false"}).json()

    assert con_requisito["productos"][0]["clasificacion"] == "sin_stock"
    assert sin_requisito["productos"][0]["clasificacion"] == "rentable"
