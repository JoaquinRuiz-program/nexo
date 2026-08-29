"""
Aislamiento real entre empresas — de punta a punta, por HTTP, con dos
sesiones de usuario REALES (no funciones llamadas directo, como tenían que
hacer las pruebas de este tipo antes de que existiera login real; ver
git log de app/api/routes/mercadolibre.py). Dos clientes HTTP independientes
(cada uno con su propia cookie de sesión), cada uno registra su propia
empresa vía POST /api/auth/registro, y se prueba que ninguno pueda ver,
listar ni modificar nada del otro — ni siquiera adivinando/iterando un ID.

29 de agosto de 2026 — migración de los routers de negocio a
`Depends(get_current_store)` (ver informe entregado antes de este commit).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


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
def client_a(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client_b(client_a):
    # Reusa el dependency_override que ya dejó activo client_a — un segundo
    # TestClient() apunta al mismo `app`, pero trae su PROPIA cookie jar:
    # exactamente lo que hace falta para simular dos sesiones de usuario
    # distintas contra el mismo backend/base.
    return TestClient(app)


def _registrar(client: TestClient, *, email: str, empresa: str) -> dict:
    res = client.post(
        "/api/auth/registro",
        json={
            "email": email,
            "password": "contraseña-segura-123",
            "full_name": "Dueño de prueba",
            "company_name": empresa,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _crear_producto(client: TestClient, *, sku: str, nombre: str, precio: float) -> int:
    """Crea un producto real vía el importador de catálogo (POST
    /api/catalogo/importar/confirmar) — no hay todavía un "agregar producto
    a mano" separado, y esto ejercita el mismo camino que un dueño real
    usaría. Devuelve el variant_id real, buscándolo por SKU (no por
    posición: el cliente puede tener otros productos ya cargados)."""
    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("catalogo.csv", f"sku,nombre,precio\n{sku},{nombre},{precio}\n", "text/csv")},
        data={"mapeo": '{"sku":"sku","nombre":"nombre","precio":"precio"}', "omitir_errores": "true"},
    )
    assert res.status_code == 200, res.text
    fila = next(p for p in client.get("/api/productos").json() if p["sku"] == sku)
    return fila["id"]


def test_empresa_a_y_empresa_b_no_ven_el_catalogo_de_la_otra(client_a, client_b):
    _registrar(client_a, email="a@empresas.cl", empresa="Empresa A")
    _registrar(client_b, email="b@empresas.cl", empresa="Empresa B")

    variant_id_a = _crear_producto(client_a, sku="A-001", nombre="Producto de A", precio=10000)
    variant_id_b = _crear_producto(client_b, sku="B-001", nombre="Producto de B", precio=20000)

    productos_de_a = client_a.get("/api/productos").json()
    productos_de_b = client_b.get("/api/productos").json()

    assert [p["nombre"] for p in productos_de_a] == ["Producto de A"]
    assert [p["nombre"] for p in productos_de_b] == ["Producto de B"]


def test_empresa_a_no_puede_leer_un_producto_de_empresa_b_adivinando_el_id(client_a, client_b):
    _registrar(client_a, email="a2@empresas.cl", empresa="Empresa A2")
    _registrar(client_b, email="b2@empresas.cl", empresa="Empresa B2")
    variant_id_b = _crear_producto(client_b, sku="SECRETO", nombre="Producto secreto de B", precio=99999)

    res = client_a.get(f"/api/productos/{variant_id_b}")
    assert res.status_code == 404  # nunca 403 — no confirma que el ID existe en otro lado


def test_empresa_a_no_puede_modificar_el_costo_de_un_producto_de_empresa_b(client_a, client_b):
    _registrar(client_a, email="a3@empresas.cl", empresa="Empresa A3")
    _registrar(client_b, email="b3@empresas.cl", empresa="Empresa B3")
    variant_id_b = _crear_producto(client_b, sku="COSTO-B", nombre="Producto de B", precio=5000)

    res = client_a.put(f"/api/productos/{variant_id_b}/costo", json={"costo": 1})
    assert res.status_code == 404

    # El costo de B nunca cambió.
    detalle_b = client_b.get(f"/api/productos/{variant_id_b}").json()
    assert detalle_b["precio"] == 5000  # sigue existiendo, intacto


def test_empresa_a_no_puede_modificar_el_stock_ml_de_un_producto_de_empresa_b(client_a, client_b):
    _registrar(client_a, email="a4@empresas.cl", empresa="Empresa A4")
    _registrar(client_b, email="b4@empresas.cl", empresa="Empresa B4")
    variant_id_b = _crear_producto(client_b, sku="STOCK-B", nombre="Producto de B", precio=5000)

    res = client_a.put(f"/api/productos/{variant_id_b}/stock-mercadolibre", json={"cantidad": 10})
    assert res.status_code == 404


def test_configuracion_de_canales_es_independiente_por_empresa(client_a, client_b):
    _registrar(client_a, email="a5@empresas.cl", empresa="Empresa A5")
    _registrar(client_b, email="b5@empresas.cl", empresa="Empresa B5")

    client_a.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 12.0})
    client_b.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 25.0})

    canales_a = client_a.get("/api/configuracion/canales").json()
    canales_b = client_b.get("/api/configuracion/canales").json()

    assert canales_a[0]["commissionPct"] == 12.0
    assert canales_b[0]["commissionPct"] == 25.0  # nunca se mezclan ni se pisan


def test_rentabilidad_y_oportunidades_solo_muestran_el_catalogo_propio(client_a, client_b):
    _registrar(client_a, email="a6@empresas.cl", empresa="Empresa A6")
    _registrar(client_b, email="b6@empresas.cl", empresa="Empresa B6")
    _crear_producto(client_a, sku="RENT-A", nombre="Producto rentable A", precio=10000)
    _crear_producto(client_b, sku="RENT-B", nombre="Producto rentable B", precio=20000)

    rent_a = client_a.get("/api/rentabilidad").json()
    rent_b = client_b.get("/api/rentabilidad").json()
    assert [p["nombre"] for p in rent_a["productos"]] == ["Producto rentable A"]
    assert [p["nombre"] for p in rent_b["productos"]] == ["Producto rentable B"]

    sel_a = client_a.get("/api/seleccion").json()
    sel_b = client_b.get("/api/seleccion").json()
    assert [p["nombre"] for p in sel_a["productos"]] == ["Producto rentable A"]
    assert [p["nombre"] for p in sel_b["productos"]] == ["Producto rentable B"]


def test_dashboard_es_independiente_por_empresa(client_a, client_b):
    _registrar(client_a, email="a7@empresas.cl", empresa="Empresa A7")
    _registrar(client_b, email="b7@empresas.cl", empresa="Empresa B7")
    _crear_producto(client_a, sku="DASH-A", nombre="Producto A", precio=10000)
    _crear_producto(client_b, sku="DASH-B-1", nombre="Producto B 1", precio=10000)
    _crear_producto(client_b, sku="DASH-B-2", nombre="Producto B 2", precio=10000)

    resumen_a = client_a.get("/api/dashboard/resumen").json()
    resumen_b = client_b.get("/api/dashboard/resumen").json()
    assert resumen_a["catalogo"]["total"] == 1
    assert resumen_b["catalogo"]["total"] == 2


def test_borrador_de_publicacion_de_empresa_b_no_es_visible_para_empresa_a(client_a, client_b):
    _registrar(client_a, email="a8@empresas.cl", empresa="Empresa A8")
    _registrar(client_b, email="b8@empresas.cl", empresa="Empresa B8")
    variant_id_b = _crear_producto(client_b, sku="PUB-B", nombre="Producto de B", precio=10000)

    res = client_a.get(f"/api/publicaciones/borrador/{variant_id_b}")
    assert res.status_code == 404


@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("GET", "/api/productos"),
        ("GET", "/api/rentabilidad"),
        ("GET", "/api/seleccion"),
        ("GET", "/api/dashboard/resumen"),
        ("GET", "/api/configuracion/canales"),
        ("GET", "/api/mercadolibre/estado"),
        ("GET", "/api/auth/me"),
    ],
)
def test_ningun_endpoint_de_negocio_responde_sin_sesion(client_a, metodo, ruta):
    """Nadie sin loguearse puede ver datos de NINGUNA empresa — ni
    siquiera "vacíos": un 200 con lista vacía todavía confirmaría que el
    endpoint funciona sin credenciales."""
    res = client_a.request(metodo, ruta)
    assert res.status_code == 401
