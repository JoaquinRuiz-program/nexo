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
from app.db.models import ChannelCostSettings, MarketplaceAccount, Order, Product, ProductVariant, Store, StoreSettings, User
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
    db_session.add(StoreSettings(store=tienda, company_name="Tienda", store_name="Tienda", low_stock_threshold=5))
    db_session.commit()
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
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

    assert body["catalogo"] == {
        "total": 0, "conStock": 0, "sinStock": 0, "stockBajo": 0, "productosConImagenes": 0,
        "alertasStockBajo": [], "alertasSinStock": [],
    }
    assert body["rentabilidad"] == {"totalProductos": 0, "productosConCosto": 0, "productosRentables": None, "canalesConfigurados": []}
    assert body["ventas"] == {"pedidosImportados": 0, "pedidosUltimos30Dias": 0, "ultimaVentaImportada": None}
    assert body["mercadoLibre"]["conectado"] is False
    assert body["publicaciones"] == {"total": 0, "activas": 0, "pausadas": 0, "cerradas": 0}
    # a_store se crea acá directo en la base (no vía /api/auth/registro) —
    # nunca tiene una Subscription real, mismo caso que una tienda vieja
    # previa al sistema de planes (ver test_suscripcion_endpoint.py para el
    # caso de una empresa que sí se registra por el endpoint real).
    assert body["suscripcion"]["plan"] is None


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


def test_rentabilidad_cuenta_los_que_convienen_en_mercado_libre(client, db_session, a_store):
    # 15 de septiembre de 2026 — misma regla que Oportunidades: margen neto de
    # Mercado Libre contra los mínimos por defecto (15 % o $3.000).
    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=15, updated_at=NOW))
    db_session.commit()
    _producto(db_session, a_store, sku="R1", nombre="Rentable", precio=10000, costo=6000)  # 10000-6000-1500 = 2500 (25 %)
    _producto(db_session, a_store, sku="R2", nombre="No rentable", precio=5000, costo=6000)  # margen negativo
    _producto(db_session, a_store, sku="R3", nombre="Sin costo", precio=8000)  # costo $0: 8000-1200 = 6800 (85 %)

    body = client.get("/api/dashboard/resumen").json()
    rent = body["rentabilidad"]
    assert rent["totalProductos"] == 3
    assert rent["productosConCosto"] == 2
    assert rent["productosRentables"] == 2


def test_rentabilidad_sin_mercado_libre_configurado_no_decide(client, db_session, a_store):
    _producto(db_session, a_store, sku="S1", nombre="Con costo", precio=10000, costo=6000)
    rent = client.get("/api/dashboard/resumen").json()["rentabilidad"]
    assert rent["productosConCosto"] == 1
    assert rent["productosRentables"] is None


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


def test_publicaciones_cuenta_por_estado(client, db_session, a_store):
    from app.db.models import MarketplaceListing

    cuenta = MarketplaceAccount(store=a_store, marketplace="mercadolibre", status="connected", external_account_id="1")
    db_session.add(cuenta)
    p1 = _producto(db_session, a_store, sku="PUB-1", nombre="Activo").product
    p2 = _producto(db_session, a_store, sku="PUB-2", nombre="Pausado").product
    p3 = _producto(db_session, a_store, sku="PUB-3", nombre="Cerrado").product
    db_session.add(MarketplaceListing(account=cuenta, product=p1, status="active", created_at=NOW))
    db_session.add(MarketplaceListing(account=cuenta, product=p2, status="paused", created_at=NOW))
    db_session.add(MarketplaceListing(account=cuenta, product=p3, status="closed", created_at=NOW))
    db_session.commit()

    body = client.get("/api/dashboard/resumen").json()
    assert body["publicaciones"] == {"total": 3, "activas": 1, "pausadas": 1, "cerradas": 1}


def test_productos_con_imagenes_cuenta_productos_no_variantes(client, db_session, a_store):
    from app.db.models import ProductImage

    variante = _producto(db_session, a_store, sku="IMG-1", nombre="Con imagen")
    db_session.add(ProductImage(product=variante.product, url="http://cdn.test/a.png", source="excel_url", position=0, created_at=NOW))
    _producto(db_session, a_store, sku="IMG-2", nombre="Sin imagen")
    db_session.commit()

    body = client.get("/api/dashboard/resumen").json()
    assert body["catalogo"]["productosConImagenes"] == 1


def test_dashboard_de_un_usuario_recien_registrado_sin_catalogo_no_revienta(client, a_store):
    # 29 de agosto de 2026: con auth obligatorio, "ninguna Store en toda la
    # base" ya no es un estado alcanzable por una request autenticada real
    # (POST /api/auth/registro siempre crea una junto con el usuario) — lo
    # que sí sigue siendo el primer estado real de un dueño nuevo es "mi
    # empresa existe, pero todavía no subí ningún catálogo". El dashboard
    # tiene que responder con ceros ahí también, no un 404/500.
    res = client.get("/api/dashboard/resumen")
    assert res.status_code == 200
    assert res.json()["catalogo"]["total"] == 0


def test_dashboard_sin_sesion_devuelve_401(client):
    # Sin cookie de sesión (nadie logueado) — nunca debe devolver datos,
    # ni siquiera "en ceros": eso seguiría confirmando que el endpoint
    # existe y responde sin pedir credenciales.
    res = client.get("/api/dashboard/resumen")
    assert res.status_code == 401
