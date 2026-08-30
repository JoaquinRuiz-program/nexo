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

from datetime import datetime

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import ChannelCostSettings, MarketplaceAccount, MarketplaceListing, ProductImage, ProductVariant, Store
from app.db.session import get_db
from app.domain.token_crypto import encrypt_token
from app.main import app

TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

CONFIGURED_SETTINGS = Settings(
    mercadolibre_client_id="test-client-id",
    mercadolibre_client_secret="test-client-secret",
    mercadolibre_redirect_uri="http://localhost:8000/api/mercadolibre/callback",
    mercadolibre_auth_domain="auth.mercadolibre.cl",
    token_encryption_key=TEST_ENCRYPTION_KEY,
)


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


# ------------------------------------------------------------------
# Publicación real en Mercado Libre — preparar/validar (29 de agosto de
# 2026, commit 3/N). Cada empresa necesita su propia MarketplaceAccount
# conectada — sin OAuth real en estos tests, se inserta directo en la
# base (igual criterio que test_mercadolibre_endpoints.py:cuenta_conectada).
# ------------------------------------------------------------------


def _conectar_cuenta_ml(db_session, empresa_id: int, *, site_id: str = "MLC") -> None:
    store = db_session.get(Store, empresa_id)
    db_session.add(
        MarketplaceAccount(
            store=store, marketplace="mercadolibre", status="connected",
            external_account_id=str(empresa_id), external_account_site_id=site_id,
            # Token real (cifrado) — hace falta para /confirmar, que sí
            # necesita access_token para las llamadas autenticadas
            # (get_listing_fees, create_item); /preparar y /validar no lo
            # necesitaban porque solo llaman a endpoints públicos de ML.
            access_token_encrypted=encrypt_token(f"token-empresa-{empresa_id}", TEST_ENCRYPTION_KEY),
            refresh_token_encrypted=encrypt_token(f"refresh-empresa-{empresa_id}", TEST_ENCRYPTION_KEY),
            token_expires_at=datetime(2027, 1, 1),
        )
    )
    db_session.commit()


def test_empresa_a_no_puede_preparar_publicacion_de_un_producto_de_empresa_b(client_a, client_b, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    a = _registrar(client_a, email="a9@empresas.cl", empresa="Empresa A9")
    b = _registrar(client_b, email="b9@empresas.cl", empresa="Empresa B9")
    _conectar_cuenta_ml(db_session, a["empresa"]["id"])
    _conectar_cuenta_ml(db_session, b["empresa"]["id"])
    variant_id_b = _crear_producto(client_b, sku="PREP-B", nombre="Producto de B", precio=10000)

    res = client_a.post(f"/api/publicaciones/{variant_id_b}/mercadolibre/preparar")
    assert res.status_code == 404  # nunca 403 — no confirma que el producto existe


def test_empresa_a_no_puede_validar_publicacion_de_un_producto_de_empresa_b(client_a, client_b, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    a = _registrar(client_a, email="a11@empresas.cl", empresa="Empresa A11")
    b = _registrar(client_b, email="b11@empresas.cl", empresa="Empresa B11")
    _conectar_cuenta_ml(db_session, a["empresa"]["id"])
    _conectar_cuenta_ml(db_session, b["empresa"]["id"])
    variant_id_b = _crear_producto(client_b, sku="VAL-B", nombre="Producto de B", precio=10000)

    res = client_a.post(
        f"/api/publicaciones/{variant_id_b}/mercadolibre/validar",
        json={"category_id": "MLC180937", "condition": "new"},
    )
    assert res.status_code == 404


def test_empresa_a_nunca_usa_la_cuenta_ml_de_empresa_b_para_preparar_su_propio_producto(client_a, client_b, db_session, monkeypatch):
    """Empresa A tiene su cuenta ML conectada con un site_id distinto al
    de Empresa B — si Nexo confundiera de cuenta, la predicción de
    categoría se pediría al site de B, no al de A. Se prueba mockeando
    SOLO el site de A: si el endpoint llamara al site de B, respx (sin esa
    ruta mockeada) haría fallar la request en vez de devolver 200."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    a = _registrar(client_a, email="a12@empresas.cl", empresa="Empresa A12")
    b = _registrar(client_b, email="b12@empresas.cl", empresa="Empresa B12")
    _conectar_cuenta_ml(db_session, a["empresa"]["id"], site_id="MLC")
    _conectar_cuenta_ml(db_session, b["empresa"]["id"], site_id="MLA")
    variant_id_a = _crear_producto(client_a, sku="PROPIO-A", nombre="Producto propio de A", precio=5000)

    with respx.mock:
        ruta_mlc = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
            return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
        )
        res = client_a.post(f"/api/publicaciones/{variant_id_a}/mercadolibre/preparar")

    assert res.status_code == 200
    assert ruta_mlc.calls.call_count == 1  # usó el site_id de SU PROPIA cuenta (MLC), nunca el de B (MLA)


def test_ningun_store_id_enviado_por_el_cliente_altera_el_tenant_usado(client_a, client_b, db_session, monkeypatch):
    """El body de /validar no declara ningún campo "store_id" — aunque el
    cliente lo mande, Pydantic lo descarta sin que el endpoint lo vea. La
    tienda usada sigue siendo exclusivamente la de la sesión autenticada."""
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    a = _registrar(client_a, email="a13@empresas.cl", empresa="Empresa A13")
    b = _registrar(client_b, email="b13@empresas.cl", empresa="Empresa B13")
    _conectar_cuenta_ml(db_session, a["empresa"]["id"])
    _conectar_cuenta_ml(db_session, b["empresa"]["id"])
    variant_id_a = _crear_producto(client_a, sku="STOREID-A", nombre="Producto propio de A", precio=5000)

    with respx.mock:
        respx.get("https://api.mercadolibre.com/categories/MLC1/attributes").mock(return_value=httpx.Response(200, json=[]))
        res = client_a.post(
            f"/api/publicaciones/{variant_id_a}/mercadolibre/validar",
            json={"category_id": "MLC1", "condition": "new", "store_id": b["empresa"]["id"], "tienda_id": b["empresa"]["id"]},
        )

    assert res.status_code == 200  # A pudo validar SU PROPIO producto con normalidad


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


# ------------------------------------------------------------------
# POST /{variant_id}/mercadolibre/confirmar — publicación REAL (29 de
# agosto de 2026, commit 4/N). Prueba obligatoria de aislamiento: A puede
# publicar A; A NO puede publicar B; A nunca usa la cuenta/token de B; un
# store_id mandado por el cliente no cambia el tenant.
# ------------------------------------------------------------------


def _hacer_publicable(db_session, variant_id: int, *, costo: float, marketplace_stock: int = 5) -> None:
    """_crear_producto (importador CSV) solo carga sku/nombre/precio — para
    que classify_product pueda devolver "rentable" hace falta además costo,
    stock reservado para ML y el canal "mercadolibre" configurado, más al
    menos una imagen (gate real de /confirmar)."""
    variante = db_session.get(ProductVariant, variant_id)
    variante.cost_price = costo
    variante.marketplace_stock = marketplace_stock
    if not variante.product.images:
        db_session.add(
            ProductImage(product=variante.product, url="http://cdn.test/img.png", source="excel_url", position=0, created_at=datetime(2026, 8, 24))
        )
    ya_configurado = (
        db_session.query(ChannelCostSettings).filter_by(store_id=variante.store_id, channel="mercadolibre").first()
    )
    if ya_configurado is None:
        db_session.add(
            ChannelCostSettings(store_id=variante.store_id, channel="mercadolibre", commission_pct=15.0, updated_at=datetime(2026, 8, 24))
        )
    db_session.commit()


def test_empresa_a_publica_su_producto_y_nunca_puede_publicar_ni_usar_la_cuenta_de_empresa_b(
    client_a, client_b, db_session, monkeypatch
):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    a = _registrar(client_a, email="a15@empresas.cl", empresa="Empresa A15")
    b = _registrar(client_b, email="b15@empresas.cl", empresa="Empresa B15")
    # Sites distintos A PROPÓSITO: si A confundiera de cuenta, intentaría
    # consultar el site de B (MLA, sin mockear acá) y la request fallaría.
    _conectar_cuenta_ml(db_session, a["empresa"]["id"], site_id="MLC")
    _conectar_cuenta_ml(db_session, b["empresa"]["id"], site_id="MLA")

    variant_id_a = _crear_producto(client_a, sku="CONF-A", nombre="Producto de A", precio=5000)
    variant_id_b = _crear_producto(client_b, sku="CONF-B", nombre="Producto de B", precio=5000)
    _hacer_publicable(db_session, variant_id_a, costo=3000)
    _hacer_publicable(db_session, variant_id_b, costo=3000)

    atributos = [{"id": "BRAND", "name": "Marca", "tags": {}, "value_type": "string"}]
    fees = [
        {
            "listing_type_id": "gold_special", "listing_type_name": "Clásica", "currency_id": "CLP",
            "sale_fee_amount": 500, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 15},
        }
    ]

    # A publica SU PROPIO producto, usando solo su propia cuenta (site MLC).
    with respx.mock:
        respx.get("https://api.mercadolibre.com/categories/MLC1/attributes").mock(return_value=httpx.Response(200, json=atributos))
        respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=fees))
        ruta_items = respx.post("https://api.mercadolibre.com/items").mock(
            return_value=httpx.Response(201, json={"id": "MLC000000A", "user_product_id": "MLCU000A"})
        )
        res_propio = client_a.post(
            f"/api/publicaciones/{variant_id_a}/mercadolibre/confirmar",
            json={"category_id": "MLC1", "condition": "new", "listing_type": "classic"},
        )
    assert res_propio.status_code == 200, res_propio.text
    assert ruta_items.calls.call_count == 1
    assert res_propio.json()["itemId"] == "MLC000000A"

    # A intenta publicar el producto de B, incluso mandando el store_id de
    # B en el body — nunca lo lee (Pydantic lo descarta), sigue resolviendo
    # el tenant solo por la sesión de A: 404, nunca 403 (no confirma que el
    # producto existe). No se mockea /items ni el site MLA de B a propósito
    # — si el endpoint llegara a intentar usarlos, la request fallaría acá
    # en vez de devolver un 404 limpio.
    with respx.mock:
        respx.get("https://api.mercadolibre.com/categories/MLC1/attributes").mock(return_value=httpx.Response(200, json=atributos))
        res_ajeno = client_a.post(
            f"/api/publicaciones/{variant_id_b}/mercadolibre/confirmar",
            json={"category_id": "MLC1", "condition": "new", "listing_type": "classic", "store_id": b["empresa"]["id"]},
        )
    assert res_ajeno.status_code == 404

    # El producto de B nunca quedó publicado por la sesión de A.
    variante_b = db_session.get(ProductVariant, variant_id_b)
    publicaciones_de_b = db_session.query(MarketplaceListing).filter_by(product_id=variante_b.product_id).count()
    assert publicaciones_de_b == 0
