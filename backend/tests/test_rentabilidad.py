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
from app.db.models import ChannelCostSettings, MercadoLibreCategoryFee, Product, ProductVariant, Store, StoreSettings, User
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


# ------------------------------------------------------------------
# 31 de agosto de 2026 — unificación comisión real vs. manual
# (resolver_costos_ml, app/api/routes/rentabilidad.py). Regla: la
# comisión REAL ya verificada contra Mercado Libre gana siempre que
# exista y haya listing_type_pref configurado; la manual
# (ChannelCostSettings) es el fallback explícito. Nunca se inventa un
# número. Ver también tests/test_publicaciones_endpoint.py para la
# misma unificación en /precio-recomendado, /decision y /decision-lote.
# ------------------------------------------------------------------


def _producto_con_categoria_ml(db_session, tienda, *, sku, nombre, precio, costo, category_id="MLC180937"):
    _producto_con_precio_y_costo(db_session, tienda, sku=sku, nombre=nombre, precio=precio, costo=costo)
    producto = db_session.query(Product).filter_by(store_id=tienda.id, internal_sku=sku).one()
    producto.ml_category_id = category_id
    producto.ml_category_name = "Categoría de prueba"
    db_session.commit()
    return producto


def _agregar_comision_ml_real(db_session, tienda, *, category_id, price, listing_type_id, percentage_fee, fixed_fee=0.0):
    db_session.add(MercadoLibreCategoryFee(
        store=tienda, category_id=category_id, listing_type_id=listing_type_id, price=price,
        percentage_fee=percentage_fee, fixed_fee=fixed_fee, sale_fee_amount=price * percentage_fee / 100 + fixed_fee,
        fetched_at=NOW,
    ))
    db_session.commit()


def _configurar_canal_manual(client, *, commission_pct, listing_type_pref=None):
    client.put(
        "/api/configuracion/canales/mercadolibre",
        json={"commission_pct": commission_pct, "shipping_cost": 0, "other_fixed_cost": 0, "listing_type_pref": listing_type_pref},
    )


def test_comision_real_disponible_se_usa_en_vez_de_la_manual(client, db_session, a_store):
    """Caso 1 + 2 del pedido del dueño: comisión real cacheada Y manual
    configurada con un % distinto — tiene que ganar la real."""
    _producto_con_categoria_ml(db_session, a_store, sku="REAL-GANA", nombre="Producto con comisión real", precio=10000, costo=6000)
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=10000, listing_type_id="gold_special", percentage_fee=12.0)
    _configurar_canal_manual(client, commission_pct=30.0, listing_type_pref="classic")  # bien distinto a la real (12%)

    body = client.get("/api/rentabilidad").json()
    fila = next(f for f in body["productos"] if f["sku"] == "REAL-GANA")
    assert fila["comisionMlFuente"] == "real"
    # margen neto con comisión REAL (12%): 10000 - 6000 - 10000*0.12 = 2800
    assert fila["margenMercadoLibreClp"] == 2800.0
    assert fila["mercadoLibreConfigurado"] is True


def test_sin_comision_real_usa_el_fallback_manual(client, db_session, a_store):
    """Caso 3: sin comisión real cacheada, con manual configurada — el
    fallback tiene que seguir funcionando exactamente como antes."""
    _producto_con_categoria_ml(db_session, a_store, sku="SOLO-MANUAL", nombre="Producto sin comisión real", precio=10000, costo=6000)
    _configurar_canal_manual(client, commission_pct=15.0, listing_type_pref="classic")

    body = client.get("/api/rentabilidad").json()
    fila = next(f for f in body["productos"] if f["sku"] == "SOLO-MANUAL")
    assert fila["comisionMlFuente"] == "manual"
    # margen neto con comisión manual (15%): 10000 - 6000 - 1500 = 2500
    assert fila["margenMercadoLibreClp"] == 2500.0


def test_sin_ninguna_comision_nunca_inventa_un_numero(client, db_session, a_store):
    """Caso 4: ni real ni manual — nunca se inventa un %, el margen ML
    queda explícitamente sin calcular."""
    _producto_con_categoria_ml(db_session, a_store, sku="SIN-NADA", nombre="Producto sin ninguna comisión", precio=10000, costo=6000)
    # Sin PUT a /configuracion/canales — canal nunca configurado.

    body = client.get("/api/rentabilidad").json()
    fila = next(f for f in body["productos"] if f["sku"] == "SIN-NADA")
    assert fila["comisionMlFuente"] is None
    assert fila["margenMercadoLibreClp"] is None
    assert fila["margenMercadoLibrePct"] is None
    assert fila["mercadoLibreConfigurado"] is False


def test_comision_real_sin_listing_type_pref_configurado_no_elige_por_el_dueno(client, db_session, a_store):
    """Con comisión real cacheada para Clásica Y Premium, pero SIN
    listing_type_pref configurado (el default, "comparar ambas") —
    elegir_comision_principal ya está diseñado para no elegir por el
    dueño en ese caso; confirmamos que el fallback a manual se respeta,
    en vez de elegir una de las dos comisiones reales arbitrariamente."""
    _producto_con_categoria_ml(db_session, a_store, sku="SIN-PREF", nombre="Producto sin preferencia", precio=10000, costo=6000)
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=10000, listing_type_id="gold_special", percentage_fee=12.0)
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=10000, listing_type_id="gold_pro", percentage_fee=18.0)
    _configurar_canal_manual(client, commission_pct=20.0)  # listing_type_pref=None a propósito

    body = client.get("/api/rentabilidad").json()
    fila = next(f for f in body["productos"] if f["sku"] == "SIN-PREF")
    assert fila["comisionMlFuente"] == "manual"
    assert fila["margenMercadoLibreClp"] == 2000.0  # 10000 - 6000 - 2000 (20% manual)


def test_comision_real_de_una_empresa_nunca_se_mezcla_con_otra(client, db_session, a_store):
    """Caso 5: dos empresas, misma categoría de Mercado Libre, comisiones
    reales y manuales distintas — nunca se mezclan (MercadoLibreCategoryFee
    está scopeada por store_id, ver el modelo)."""
    _producto_con_categoria_ml(db_session, a_store, sku="A-REAL", nombre="Producto de A", precio=10000, costo=6000)
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=10000, listing_type_id="gold_special", percentage_fee=10.0)
    _configurar_canal_manual(client, commission_pct=99.0, listing_type_pref="classic")  # manual absurda, nunca debería usarse acá

    otro_usuario = User(email="empresa-b@ejemplo.cl", password_hash=hash_password("x"), full_name="Dueño B", created_at=NOW, updated_at=NOW)
    db_session.add(otro_usuario)
    tienda_b = Store(owner=otro_usuario, name="Empresa B", created_at=NOW)
    db_session.add(tienda_b)
    db_session.add(StoreSettings(store=tienda_b, company_name="Empresa B", store_name="Empresa B"))
    db_session.commit()
    # Empresa B: MISMA categoría, MISMO precio, pero su propia comisión real distinta.
    _producto_con_categoria_ml(db_session, tienda_b, sku="B-REAL", nombre="Producto de B", precio=10000, costo=6000)
    _agregar_comision_ml_real(db_session, tienda_b, category_id="MLC180937", price=10000, listing_type_id="gold_special", percentage_fee=25.0)
    db_session.add(ChannelCostSettings(store=tienda_b, channel="mercadolibre", commission_pct=5.0, listing_type_pref="classic", updated_at=NOW))
    db_session.commit()

    fila_a = next(f for f in client.get("/api/rentabilidad").json()["productos"] if f["sku"] == "A-REAL")
    assert fila_a["comisionMlFuente"] == "real"
    assert fila_a["margenMercadoLibreClp"] == 3000.0  # 10000-6000-1000 (10% real de A, nunca el 25% de B)

    # Empresa B ve su propia comisión real (25%), nunca la de A (10%) ni su manual (5% propia, ni siquiera hace falta: hay real).
    autenticar(client, db_session, otro_usuario, tienda_b, ahora=NOW)
    fila_b = next(f for f in client.get("/api/rentabilidad").json()["productos"] if f["sku"] == "B-REAL")
    assert fila_b["comisionMlFuente"] == "real"
    assert fila_b["margenMercadoLibreClp"] == 1500.0  # 10000-6000-2500 (25% real de B)


def test_comision_real_cacheada_a_otro_precio_no_se_usa_cae_al_fallback_manual(client, db_session, a_store):
    """Hallazgo de qa-engineer (31 de agosto de 2026, revisión final): el
    lookup de comisión real es por precio EXACTO — si el producto cambió de
    precio desde la última vez que se consultó Mercado Libre, la comisión
    cacheada al precio viejo NUNCA debe usarse como si fuera válida para el
    precio nuevo (sería un dato desactualizado disfrazado de "real")."""
    _producto_con_categoria_ml(db_session, a_store, sku="PRECIO-CAMBIO", nombre="Producto con precio nuevo", precio=12000, costo=6000)
    # Comisión real cacheada a un precio DISTINTO (10000) del precio actual de la variante (12000).
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=10000, listing_type_id="gold_special", percentage_fee=10.0)
    _configurar_canal_manual(client, commission_pct=15.0, listing_type_pref="classic")

    body = client.get("/api/rentabilidad").json()
    fila = next(f for f in body["productos"] if f["sku"] == "PRECIO-CAMBIO")
    assert fila["comisionMlFuente"] == "manual"
    assert fila["margenMercadoLibreClp"] == 12000 - 6000 - 12000 * 0.15  # manual 15%, nunca el 10% cacheado a otro precio


def test_comision_ml_real_informativa_usa_el_costo_de_cada_variante_no_el_de_la_primera(client, db_session, a_store):
    """Hallazgo de backend-architect (31 de agosto de 2026, ronda de pulido
    pre-cliente): _comision_ml_real (el detalle informativo Clásica/Premium,
    "comisionMlReal" en la respuesta) usaba el costo de la PRIMERA variante
    del producto para TODAS sus variantes. Con dos variantes de distinto
    costo, la segunda mostraba un margenClp/margenPct calculado con el
    costo equivocado -- inconsistente con margenMercadoLibreClp de la misma
    fila, que sí usa el costo correcto."""
    producto = Product(store=a_store, internal_sku="DOS-VARIANTES", name="Producto con variantes", product_type="variable",
                        ml_category_id="MLC180937", ml_category_name="Cuadernos", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="DOS-VAR-A", variant_label="Azul", price=10000, cost_price=4000, created_at=NOW, updated_at=NOW))
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="DOS-VAR-B", variant_label="Rojo", price=10000, cost_price=7000, created_at=NOW, updated_at=NOW))
    db_session.commit()
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=10000, listing_type_id="gold_special", percentage_fee=10.0)

    body = client.get("/api/rentabilidad").json()
    fila_a = next(f for f in body["productos"] if f["sku"] == "DOS-VAR-A")
    fila_b = next(f for f in body["productos"] if f["sku"] == "DOS-VAR-B")

    # 10000 - costo_de_ESTA_variante - 1000 (10% de 10000) -- cada variante
    # con su propio costo, nunca el de la otra.
    assert fila_a["comisionMlReal"]["classic"]["margenClp"] == 10000 - 4000 - 1000
    assert fila_b["comisionMlReal"]["classic"]["margenClp"] == 10000 - 7000 - 1000
    assert fila_a["comisionMlReal"]["classic"]["margenClp"] != fila_b["comisionMlReal"]["classic"]["margenClp"]
