"""
Pruebas end-to-end de /api/publicaciones/* — el "borrador de publicación"
en modo simulación, contra datos reales en una base SQLite en memoria.
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
from app.db.models import Product, ProductImage, ProductVariant, Store, StoreSettings, User
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
