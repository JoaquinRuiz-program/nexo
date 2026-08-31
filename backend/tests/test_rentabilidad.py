"""
Pruebas end-to-end de GET /api/rentabilidad y PUT /api/configuracion/canales
— mismo patrón que test_productos_db.py (cliente HTTP real, SQLite en
memoria vía dependency_override).
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
    usuario = User(
        email="tienda@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW
    )
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Tienda de prueba", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda"))
    db_session.commit()
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    return tienda


def _producto_con_precio_y_costo(db_session, tienda, *, sku, nombre, precio, costo):
    producto = Product(store=tienda, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(
        ProductVariant(
            product=producto, store_id=tienda.id, variant_sku=sku, price=precio, cost_price=costo,
            created_at=NOW, updated_at=NOW,
        )
    )
    db_session.commit()


def test_rentabilidad_vacia_sin_productos(client, a_store):
    res = client.get("/api/rentabilidad")
    assert res.status_code == 200
    body = res.json()
    assert body["productos"] == []
    assert body["resumen"] == {"totalProductos": 0, "productosConCosto": 0, "canalesConfigurados": []}


def test_producto_sin_costo_no_tiene_margen(client, db_session, a_store):
    producto = Product(store=a_store, internal_sku="LIB-001", name="Libro sin costo", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="LIB-001", price=10000, created_at=NOW, updated_at=NOW))
    db_session.commit()

    body = client.get("/api/rentabilidad").json()
    filas = body["productos"]
    assert len(filas) == 1
    assert filas[0]["tieneCosto"] is False
    assert filas[0]["margenTiendaClp"] is None
    assert filas[0]["margenMercadoLibreClp"] is None
    # El resumen es lo que un futuro frontend usa para mostrar el aviso
    # "Aún no hay costos de compra cargados" en vez de una tabla vacía.
    assert body["resumen"]["productosConCosto"] == 0
    assert body["resumen"]["totalProductos"] == 1


def test_producto_con_costo_tiene_margen_tienda_pero_no_ml_sin_configurar(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="LIB-002", nombre="Rayuela", precio=10000, costo=7000)

    body = client.get("/api/rentabilidad").json()
    filas = body["productos"]
    assert len(filas) == 1
    assert body["resumen"]["productosConCosto"] == 1
    assert body["resumen"]["canalesConfigurados"] == []
    fila = filas[0]
    assert fila["tieneCosto"] is True
    assert fila["margenTiendaClp"] == 3000
    assert fila["margenTiendaPct"] == 30.0
    # Sin comisión de ML configurada -> no se inventa ningún margen neto.
    assert fila["mercadoLibreConfigurado"] is False
    assert fila["margenMercadoLibreClp"] is None
    assert fila["margenMercadoLibrePct"] is None


def test_configurar_canal_mercado_libre_habilita_el_margen_neto(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="LIB-003", nombre="Libro B", precio=10000, costo=7000)

    put_res = client.put(
        "/api/configuracion/canales/mercadolibre",
        json={"commission_pct": 12.0, "shipping_cost": 1500, "other_fixed_cost": 0},
    )
    assert put_res.status_code == 200
    assert put_res.json()["configurado"] is True

    body = client.get("/api/rentabilidad").json()
    assert body["resumen"]["canalesConfigurados"] == ["mercadolibre"]
    fila = body["productos"][0]
    assert fila["mercadoLibreConfigurado"] is True
    assert fila["margenMercadoLibreClp"] == 300  # igual que el ejemplo del dueño: Libro B


def test_productos_sin_costo_quedan_al_final_no_ordenados_como_cero(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="ALTO", nombre="Margen alto", precio=20000, costo=5000)
    producto_sin_costo = Product(store=a_store, internal_sku="SIN-COSTO", name="Sin costo", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto_sin_costo)
    db_session.flush()
    db_session.add(ProductVariant(product=producto_sin_costo, store_id=a_store.id, variant_sku="SIN-COSTO", price=5000, created_at=NOW, updated_at=NOW))
    _producto_con_precio_y_costo(db_session, a_store, sku="BAJO", nombre="Margen bajo", precio=5000, costo=4800)

    body = client.get("/api/rentabilidad").json()
    skus_en_orden = [f["sku"] for f in body["productos"]]
    assert skus_en_orden == ["ALTO", "BAJO", "SIN-COSTO"]
    assert body["resumen"] == {"totalProductos": 3, "productosConCosto": 2, "canalesConfigurados": []}


def test_listar_canales_vacio_antes_de_configurar(client, a_store):
    assert client.get("/api/configuracion/canales").json() == []


def test_rentabilidad_esta_scopeada_por_tienda_no_mezcla_empresas(client, db_session, a_store):
    """Antes (29 de agosto de 2026) build_profitability_rows consultaba
    Product/ChannelCostSettings SIN filtrar por store_id — con una sola
    tienda en desarrollo no se notaba, pero mezclaba el catálogo de TODAS
    las empresas apenas hubiera una segunda."""
    _producto_con_precio_y_costo(db_session, a_store, sku="A-001", nombre="Producto de Empresa A", precio=10000, costo=6000)

    otro_usuario = User(email="otra@empresa.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.commit()
    _producto_con_precio_y_costo(db_session, tienda_b, sku="B-001", nombre="Producto de Empresa B", precio=20000, costo=15000)

    body = client.get("/api/rentabilidad").json()
    nombres = [f["nombre"] for f in body["productos"]]
    assert nombres == ["Producto de Empresa A"]
    assert "Producto de Empresa B" not in nombres


def test_configurar_canal_sin_dato_no_lo_marca_configurado(client, a_store):
    res = client.put("/api/configuracion/canales/mercadolibre", json={})
    assert res.json()["configurado"] is False


def test_configurar_margen_objetivo_via_endpoint_habilita_precio_recomendado(client, db_session, a_store):
    """30 de agosto de 2026 — hallazgo de qa-engineer: todos los tests que
    ejercitan margen objetivo/mínimo lo insertaban directo en la base
    (ChannelCostSettings.target_margin_pct = ...), nunca a través del PUT
    real — es decir, nadie probaba automáticamente que la pantalla
    "Configurar costos y margen" funciona de punta a punta. Este test hace
    el PUT real (comisión + margen) y confirma en el endpoint de precio
    recomendado que deja de dar "datos_insuficientes"."""
    _producto_con_precio_y_costo(db_session, a_store, sku="MARGEN-HTTP", nombre="Producto con margen vía HTTP", precio=10000, costo=7000)

    res = client.put(
        "/api/configuracion/canales/mercadolibre",
        json={"commission_pct": 15.0, "shipping_cost": 0, "other_fixed_cost": 0, "target_margin_pct": 25.0, "min_margin_pct": 10.0},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["targetMarginPct"] == 25.0
    assert body["minMarginPct"] == 10.0

    canal = client.get("/api/configuracion/canales").json()[0]
    assert canal["targetMarginPct"] == 25.0
    assert canal["minMarginPct"] == 10.0
