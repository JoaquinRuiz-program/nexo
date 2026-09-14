"""
Pruebas end-to-end de /api/catalogo/importar/* — sube archivos reales
(csv y xlsx) con distintas convenciones de columnas, contra una base
SQLite en memoria.
"""

from __future__ import annotations

import io
import json
from datetime import datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Plan, Product, ProductImage, ProductVariant, Store, StoreSettings, Subscription, User
from app.db.session import get_db
from app.domain.security import hash_password
from tests.auth_helpers import autenticar
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
def a_store(client, db_session):
    usuario = User(email="tienda@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Tienda de prueba", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda"))
    db_session.commit()
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    return tienda


CSV_LIBRERIA = (
    "SKU,Nombre,Marca,Categoría,Precio,Costo,Stock,Descripción,Imagen\n"
    "LIB-001,Cuaderno universitario,Torre,Cuadernos,3990,2000,25,Cuaderno 100 hojas,http://cdn.test/cuaderno.png\n"
    "LIB-002,Lápiz grafito HB,Faber,Papelería,690,300,120,,\n"
)

CSV_DESORDENADO = (
    "Producto,Codigo,Precio venta,Existencia,Marca,costo compra\n"
    "Taladro percutor,FER-001,45990,4,Bosch,28000\n"
    "Set de brocas,FER-002,,15,,\n"  # sin precio -> revision, no error
)


def test_analizar_csv_de_libreria_detecta_columnas_exactas(client, a_store):
    archivo = io.BytesIO(CSV_LIBRERIA.encode("utf-8"))
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("libreria.csv", archivo, "text/csv")})

    assert res.status_code == 200
    body = res.json()
    assert body["mapeoPropuesto"]["sku"] == "SKU"
    assert body["mapeoPropuesto"]["nombre"] == "Nombre"
    assert body["mapeoPropuesto"]["precio"] == "Precio"
    assert body["resumen"]["totalFilas"] == 2


def test_analizar_csv_desordenado_igual_detecta_las_columnas(client, a_store):
    archivo = io.BytesIO(CSV_DESORDENADO.encode("utf-8"))
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("desordenado.csv", archivo, "text/csv")})

    assert res.status_code == 200
    body = res.json()
    assert body["mapeoPropuesto"]["nombre"] == "Producto"
    assert body["mapeoPropuesto"]["sku"] == "Codigo"
    assert body["mapeoPropuesto"]["precio"] == "Precio venta"
    assert body["mapeoPropuesto"]["stock"] == "Existencia"
    assert body["mapeoPropuesto"]["costo"] == "costo compra"
    # Fila sin precio -> no bloqueante (revision), no debería aparecer como error
    fila_sin_precio = next(f for f in body["filas"] if f["sku"] == "FER-002")
    assert fila_sin_precio["estado"] == "revision"


def test_confirmar_crea_productos_variantes_e_imagen(client, db_session, a_store):
    archivo = io.BytesIO(CSV_LIBRERIA.encode("utf-8"))
    mapeo = {
        "sku": "SKU", "nombre": "Nombre", "marca": "Marca", "categoria": "Categoría",
        "precio": "Precio", "costo": "Costo", "stock": "Stock", "descripcion": "Descripción", "imagen_url": "Imagen",
    }
    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("libreria.csv", archivo, "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["creados"] == 2
    assert body["actualizados"] == 0

    productos = db_session.query(Product).order_by(Product.internal_sku).all()
    assert [p.internal_sku for p in productos] == ["LIB-001", "LIB-002"]
    assert productos[0].brand == "Torre"
    assert productos[0].source == "csv_upload"
    # Regresión: un encabezado con tilde ("Categoría") tiene que sobrevivir
    # todo el camino (mapeo -> build_rows -> Product.category), no solo los
    # campos sin acentos.
    assert productos[0].category == "Cuadernos"

    variante = db_session.query(ProductVariant).filter_by(variant_sku="LIB-001").one()
    assert float(variante.price) == 3990
    assert float(variante.cost_price) == 2000
    assert variante.stock_quantity == 25

    imagen = db_session.query(ProductImage).filter_by(product_id=productos[0].id).one()
    assert imagen.url == "http://cdn.test/cuaderno.png"
    assert imagen.source == "excel_url"


def test_confirmar_omite_filas_con_error_por_defecto(client, db_session, a_store):
    csv_con_error = "Nombre,Precio\n,1000\nProducto OK,2000\n"  # primera fila sin nombre -> error
    archivo = io.BytesIO(csv_con_error.encode("utf-8"))
    mapeo = {"nombre": "Nombre", "precio": "Precio"}

    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("con_error.csv", archivo, "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )

    body = res.json()
    assert body["creados"] == 1
    assert body["omitidos"] == 1
    assert db_session.query(Product).count() == 1


def test_reimportar_el_mismo_sku_actualiza_en_vez_de_duplicar(client, db_session, a_store):
    mapeo = {"sku": "SKU", "nombre": "Nombre", "precio": "Precio"}

    primera = "SKU,Nombre,Precio\nLIB-001,Cuaderno,3990\n"
    client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("v1.csv", io.BytesIO(primera.encode()), "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )

    segunda = "SKU,Nombre,Precio\nLIB-001,Cuaderno Actualizado,4500\n"
    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("v2.csv", io.BytesIO(segunda.encode()), "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )

    assert res.json()["creados"] == 0
    assert res.json()["actualizados"] == 1
    assert db_session.query(Product).count() == 1
    producto = db_session.query(Product).one()
    assert producto.name == "Cuaderno Actualizado"
    assert float(producto.variants[0].price) == 4500


def test_analizar_xlsx_real_funciona_igual_que_csv(client, a_store):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Codigo", "Producto", "Precio venta", "Existencia"])
    ws.append(["ELEC-001", "Mouse inalámbrico", "8990", "40"])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    res = client.post(
        "/api/catalogo/importar/analizar",
        files={"file": ("electronica.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["mapeoPropuesto"]["sku"] == "Codigo"
    assert body["mapeoPropuesto"]["nombre"] == "Producto"
    assert body["resumen"]["totalFilas"] == 1


def test_analizar_xlsx_con_titulo_arriba_y_notas_abajo(client, a_store):
    """Planilla estilo 'Calculadora de precios' del piloto: título e
    instrucciones antes de la tabla, y notas al pie después. El encabezado
    real está varias filas abajo y no en la primera fila."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Calculadora de precio de venta en Mercado Libre"])   # título (1 celda)
    ws.append(["Completá las columnas azules por producto."])        # instrucción (1 celda)
    ws.append([])                                                    # fila en blanco
    ws.append(["Producto", "SKU / Código", "Costo de compra (CLP)", "Precio de venta sugerido (CLP)"])  # encabezado real
    ws.append(["Cien años de soledad", "LIB-001", 6000, 8000])
    ws.append(["Cuaderno universitario", "ESC-014", 900, 1200])
    ws.append([])                                                    # separación
    ws.append(["Cómo se calcula el precio sugerido:"])               # nota al pie (basura)
    ws.append(["Celda amarilla = dato que confirmás vos."])          # nota al pie (basura)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    res = client.post(
        "/api/catalogo/importar/analizar",
        files={"file": ("calculadora.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mapeoPropuesto"]["nombre"] == "Producto"
    assert body["mapeoPropuesto"]["sku"] == "SKU / Código"
    assert body["mapeoPropuesto"]["precio"] == "Precio de venta sugerido (CLP)"
    assert body["mapeoPropuesto"]["costo"] == "Costo de compra (CLP)"
    # Las 2 filas de la tabla, sin las notas al pie de abajo.
    assert body["resumen"]["totalFilas"] == 2


def test_formato_no_soportado_devuelve_400(client, a_store):
    archivo = io.BytesIO(b"esto no es una planilla")
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("archivo.pdf", archivo, "application/pdf")})
    assert res.status_code == 400


def test_xlsx_corrupto_devuelve_400_no_500(client, a_store):
    # Extensión válida pero contenido dañado (no es un zip válido) — antes
    # esto escapaba como una excepción sin manejar (500 sin headers CORS),
    # dejando al frontend con un fallo de red sin ninguna explicación.
    archivo = io.BytesIO(b"PK\x03\x04esto no es un zip valido de verdad")
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("catalogo.xlsx", archivo, "application/octet-stream")})
    assert res.status_code == 400
    assert "no pudimos leer el archivo" in res.json()["detail"].lower()


# ------------------------------------------------------------------
# 5 de septiembre de 2026 — límite de productos del plan (ver
# app/domain/plans.py). Nunca se puede manipular desde el frontend: se
# evalúa siempre server-side, contando lo que YA existe en la base.
# ------------------------------------------------------------------


def test_importar_omite_productos_nuevos_que_excedan_el_limite_del_plan(client, db_session, a_store):
    plan = Plan(code="plan-chico", name="Plan chico", product_limit=1, price_demo_label="Precio demo: $0")
    db_session.add(plan)
    db_session.flush()
    db_session.add(Subscription(store=a_store, plan=plan, status="active", started_at=NOW, current_period_end=NOW.date()))
    db_session.commit()

    archivo = io.BytesIO(CSV_LIBRERIA.encode("utf-8"))  # 2 productos nuevos, límite = 1
    mapeo = {"sku": "SKU", "nombre": "Nombre", "marca": "Marca", "categoria": "Categoría", "precio": "Precio", "costo": "Costo", "stock": "Stock"}
    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("libreria.csv", archivo, "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["creados"] == 1
    assert body["omitidos"] == 1
    assert "límite" in body["detalleOmitidos"][0]["problemas"][0].lower()
    assert db_session.query(Product).filter_by(store_id=a_store.id).count() == 1


def test_importar_sin_suscripcion_no_tiene_ningun_limite(client, db_session, a_store):
    """Dato viejo (tienda sin Subscription, previa a este sistema de
    planes) — nunca se bloquea una importación por falta de suscripción."""
    archivo = io.BytesIO(CSV_LIBRERIA.encode("utf-8"))
    mapeo = {"sku": "SKU", "nombre": "Nombre", "marca": "Marca", "categoria": "Categoría", "precio": "Precio", "costo": "Costo", "stock": "Stock"}
    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("libreria.csv", archivo, "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )
    assert res.status_code == 200, res.text
    assert res.json()["creados"] == 2


# ------------------------------------------------------------------
# Topes de importación (6 de septiembre de 2026, P1-2 de la auditoría
# pre-producción): sin esto, un archivo enorme podía agotar la memoria del
# proceso — y con un solo worker en producción, dejar sin servicio a TODAS
# las empresas, no solo a la que subió el archivo.
# ------------------------------------------------------------------


def test_archivo_mas_grande_que_el_tope_se_rechaza_sin_procesarlo(client, a_store):
    from app.domain.spreadsheet_io import MAX_ARCHIVO_BYTES

    gigante = io.BytesIO(b"a" * (MAX_ARCHIVO_BYTES + 1))
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("enorme.csv", gigante, "text/csv")})

    assert res.status_code == 400
    assert "MB" in res.json()["detail"]


def test_archivo_con_mas_filas_que_el_tope_se_rechaza(client, a_store):
    from app.domain.spreadsheet_io import MAX_FILAS

    filas = "\n".join(f"SKU-{i},Producto {i},1000" for i in range(MAX_FILAS + 1))
    csv_largo = f"SKU,Nombre,Precio\n{filas}\n"
    res = client.post(
        "/api/catalogo/importar/analizar",
        files={"file": ("muchas-filas.csv", io.BytesIO(csv_largo.encode("utf-8")), "text/csv")},
    )

    assert res.status_code == 400
    assert "filas" in res.json()["detail"].lower()


def test_un_archivo_normal_sigue_importandose_igual_que_antes(client, db_session, a_store):
    """El tope no puede volverse un obstáculo para un catálogo real: el
    archivo de siempre tiene que seguir funcionando exactamente igual."""
    archivo = io.BytesIO(CSV_LIBRERIA.encode("utf-8"))
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("libreria.csv", archivo, "text/csv")})

    assert res.status_code == 200, res.text
    assert res.json()["resumen"]["totalFilas"] == 2


def test_importacion_de_costos_tambien_respeta_el_tope_de_tamano(client, a_store):
    from app.domain.spreadsheet_io import MAX_ARCHIVO_BYTES

    gigante = io.BytesIO(b"a" * (MAX_ARCHIVO_BYTES + 1))
    res = client.post("/api/costos/importar", files={"file": ("costos-enorme.csv", gigante, "text/csv")})

    assert res.status_code == 400
    assert "MB" in res.json()["detail"]
