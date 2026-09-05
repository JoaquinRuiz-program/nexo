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
from app.db.models import Product, ProductImage, ProductVariant, Store, StoreSettings, User
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
# eliminar, reordenar). Nexo no tiene almacenamiento de archivos todavía
# (ver docstring de ProductImage) — esto es el CRUD sobre lo que ya existe
# (URL + orden), no una subida de archivos real.
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
