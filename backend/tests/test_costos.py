"""
Pruebas end-to-end de POST /api/costos/importar — sube un archivo real
(CSV y XLSX) vía HTTP, contra una base SQLite en memoria.
"""

from __future__ import annotations

import io
from datetime import datetime

import openpyxl
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
def a_store(db_session):
    usuario = User(
        email="tienda@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW
    )
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Tienda de prueba", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda"))
    db_session.commit()
    return tienda


def _crear_producto(db_session, tienda, *, sku, nombre):
    producto = Product(store=tienda, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=tienda.id, variant_sku=sku, price=10000, created_at=NOW, updated_at=NOW))
    db_session.commit()


def test_sube_un_csv_y_actualiza_el_costo(client, db_session, a_store):
    _crear_producto(db_session, a_store, sku="LIB-001", nombre="Cien años de soledad")
    archivo = io.BytesIO(b"sku,costo\nLIB-001,8500\n")

    res = client.post("/api/costos/importar", files={"file": ("costos.csv", archivo, "text/csv")})

    assert res.status_code == 200
    body = res.json()
    assert body["actualizados"] == ["LIB-001"]
    assert body["noEncontrados"] == []


def test_sube_un_xlsx_y_actualiza_el_costo(client, db_session, a_store):
    _crear_producto(db_session, a_store, sku="LIB-002", nombre="Rayuela")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["sku", "costo"])
    ws.append(["LIB-002", 7500])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    res = client.post(
        "/api/costos/importar",
        files={"file": ("costos.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert res.status_code == 200
    assert res.json()["actualizados"] == ["LIB-002"]


def test_formato_no_soportado_devuelve_400_no_500(client, a_store):
    archivo = io.BytesIO(b"esto no es un csv ni un excel")

    res = client.post("/api/costos/importar", files={"file": ("costos.pdf", archivo, "application/pdf")})

    assert res.status_code == 400
    assert "no soportado" in res.json()["detail"].lower()


def test_sku_no_encontrado_se_reporta_sin_romper_la_respuesta(client, a_store):
    archivo = io.BytesIO(b"sku,costo\nNO-EXISTE,1000\n")

    res = client.post("/api/costos/importar", files={"file": ("costos.csv", archivo, "text/csv")})

    assert res.status_code == 200
    assert res.json()["noEncontrados"] == ["NO-EXISTE"]
