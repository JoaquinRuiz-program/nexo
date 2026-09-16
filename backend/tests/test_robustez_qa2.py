"""Robustez encontrada en la QA fase 2 (15 de septiembre de 2026): CSV de Excel
en Windows-1252, IDs fuera de rango, una sola tarea de comisiones por empresa y
nunca una conexión de la base tomada mientras se espera a Mercado Libre."""

from __future__ import annotations

import asyncio
import io

from app.db.models import Product, ProductVariant
from app.domain.spreadsheet_io import read_rows
from app.services import ml_comisiones
from tests.test_publicaciones_endpoint import FEES_CUADERNOS, NOW, _producto_publicable, a_store, client, db_session  # noqa: F401 — fixtures


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def test_subir_imagen_corrupta_o_disfrazada_no_da_500(client, db_session, a_store, monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.routes.productos_db.get_settings", lambda: type("S", (), {"uploads_dir": str(tmp_path), "backend_public_base_url": "http://test"})())
    variant_id = _producto_publicable(db_session, a_store, sku="IMG-RARA", con_imagen=False)
    archivos = [
        ("files", ("roto.png", PNG_1X1[:40] + b"<script>alert(1)</script>" + PNG_1X1[40:], "image/png")),
        ("files", ("dibujo.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>', "image/svg+xml")),
        ("files", ("falso.png", b"GIF89a" + b"0" * 100, "image/png")),
    ]
    res = client.post(f"/api/productos/{variant_id}/imagenes/upload", files=archivos)
    assert res.status_code == 200, res.text
    assert res.json()["subidas"]["guardadas"] == 0
    assert len(res.json()["subidas"]["rechazadas"]) == 3


def test_prediccion_de_categorias_respeta_el_tope_por_corrida(db_session, a_store, monkeypatch):
    monkeypatch.setattr(ml_comisiones, "MAX_PREDICCIONES_POR_CORRIDA", 2)
    for n in range(3):
        producto = Product(store=a_store, internal_sku=f"TOPE-{n}", name=f"Producto {n}", product_type="simple", created_at=NOW, updated_at=NOW)
        db_session.add(producto)
        db_session.flush()
        db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku=f"TOPE-{n}", price=5000, created_at=NOW, updated_at=NOW))
    db_session.commit()
    llamadas = []

    class AdapterFalso:
        async def predict_category(self, nombre, site_id):  # noqa: ARG002
            llamadas.append(nombre)
            return None

        async def get_listing_fees(self, *args):  # noqa: ARG002
            return []

    asyncio.run(ml_comisiones.actualizar_comisiones_reales(db_session, a_store.id, AdapterFalso(), "token", "MLC"))
    assert len(llamadas) == 2


def test_choque_de_restriccion_unica_por_operaciones_simultaneas_da_409_no_500(client, a_store, monkeypatch):
    """Dos importaciones realmente simultáneas en Postgres pueden chocar con la
    restricción única (empresa, SKU): la segunda recibe un 409 entendible, nunca
    un 500 ni un producto duplicado."""
    from sqlalchemy.exc import IntegrityError

    def choque(*args, **kwargs):  # noqa: ARG001
        raise IntegrityError("INSERT INTO product_variants", {}, Exception("uq_variant_store_sku"))

    monkeypatch.setattr("app.api.routes.catalogo.escribir_filas", choque)
    archivo = b"SKU,Nombre,Precio\nA-1,Producto,1000\n"
    res = client.post(
        "/api/catalogo/importar/confirmar", files={"file": ("c.csv", io.BytesIO(archivo), "text/csv")},
        data={"mapeo": '{"sku": "SKU", "nombre": "Nombre", "precio": "Precio"}'},
    )
    assert res.status_code == 409, res.text
    assert "al mismo tiempo" in res.json()["detail"]


def test_canal_inventado_no_se_puede_configurar(client, a_store):
    assert client.put("/api/configuracion/canales/chancho", json={"commission_pct": 10}).status_code == 404
    assert client.get("/api/configuracion/canales").json() == []


def test_stock_para_mercado_libre_gigante_se_rechaza(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="STOCK-GIGANTE")
    assert client.put(f"/api/productos/{variant_id}/stock-mercadolibre", json={"cantidad": 10 ** 12}).status_code == 400


def test_solicitud_de_soporte_larga_o_repetida(client, a_store):
    from app.db.models.support import CATEGORIAS_VALIDAS

    base = {"category": CATEGORIAS_VALIDAS[0], "subject": "No puedo importar", "description": "Me da un error"}
    assert client.post("/api/soporte/solicitudes", json={**base, "subject": "S" * 201}).status_code == 422
    primera = client.post("/api/soporte/solicitudes", json=base).json()
    segunda = client.post("/api/soporte/solicitudes", json=base).json()
    assert primera["id"] == segunda["id"]
    assert len(client.get("/api/soporte/solicitudes").json()) == 1


def test_preparar_con_ids_repetidos_no_duplica_borradores(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="PREP-DUP")
    res = client.post("/api/publicaciones/preparar", json={"variant_ids": [variant_id, variant_id, variant_id], "canal": "mercadolibre"})
    assert res.status_code == 200
    assert len(res.json()["borradores"]) == 1


def test_productos_sin_categoria_predecible_no_bloquean_a_los_demas(db_session, a_store, monkeypatch):
    import random

    monkeypatch.setattr(ml_comisiones, "MAX_PREDICCIONES_POR_CORRIDA", 1)
    random.seed(7)
    for sku, nombre in (("NO-PREDECIBLE", "zzzz"), ("PREDECIBLE", "Cuaderno universitario")):
        producto = Product(store=a_store, internal_sku=sku, name=nombre, product_type="simple", created_at=NOW, updated_at=NOW)
        db_session.add(producto)
        db_session.flush()
        db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku=sku, price=5000, created_at=NOW, updated_at=NOW))
    db_session.commit()

    class AdapterFalso:
        async def predict_category(self, nombre, site_id):  # noqa: ARG002
            return None if nombre == "zzzz" else {"categoryId": "MLC180937", "categoryName": "Cuadernos"}

        async def get_listing_fees(self, *args):  # noqa: ARG002
            return []

    for _ in range(20):
        asyncio.run(ml_comisiones.actualizar_comisiones_reales(db_session, a_store.id, AdapterFalso(), "token", "MLC"))
    predecible = db_session.query(Product).filter_by(store_id=a_store.id, internal_sku="PREDECIBLE").one()
    assert predecible.ml_category_id == "MLC180937"


def test_costo_absurdo_o_no_numerico_se_rechaza(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="COSTO-RARO", costo=3000)
    for cuerpo in ('{"costo": 1e308}', '{"costo": NaN}', '{"costo": Infinity}', '{"costo": 99999999999}'):
        res = client.put(f"/api/productos/{variant_id}/costo", content=cuerpo, headers={"content-type": "application/json"})
        assert res.status_code == 400, (cuerpo, res.status_code, res.text)
    assert client.get(f"/api/productos/{variant_id}").json()["costo"] == 3000


def test_configuracion_de_mercado_libre_fuera_de_rango_se_rechaza(client, a_store):
    for cuerpo in ({"commission_pct": -50}, {"commission_pct": 1000}, {"shipping_cost": -1}, {"shipping_cost": 1e308},
                   {"target_margin_pct": 150}, {"min_margin_pct": -10}, {"min_profit_clp": -5000}):
        res = client.put("/api/configuracion/canales/mercadolibre", json=cuerpo)
        assert res.status_code == 400, (cuerpo, res.status_code, res.text)
    valido = client.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 13, "shipping_cost": 3500, "target_margin_pct": 30, "min_margin_pct": 15, "min_profit_clp": 3000})
    assert valido.status_code == 200


def test_csv_guardado_desde_excel_en_windows_se_lee():
    contenido = "SKU,Nombre,Costo,Precio\nLAT-1,Camión ñandú,1000,2990\n".encode("cp1252")
    encabezados, filas = read_rows(io.BytesIO(contenido), "catalogo.csv")
    assert encabezados == ["SKU", "Nombre", "Costo", "Precio"]
    assert filas[0]["Nombre"] == "Camión ñandú"


def test_id_fuera_de_rango_no_da_500(client, a_store):
    for ruta in ("/api/productos/9223372036854775808", "/api/soporte/solicitudes/99999999999999999999"):
        res = client.get(ruta)
        assert res.status_code in (400, 404, 422), (ruta, res.status_code, res.text)


def test_una_sola_tarea_de_comisiones_por_empresa_a_la_vez(monkeypatch):
    llamadas = []
    liberar = asyncio.Event()

    async def falsa(db, store_id, settings):  # noqa: ARG001
        llamadas.append(store_id)
        await liberar.wait()

    monkeypatch.setattr(ml_comisiones, "actualizar_comisiones_reales_de_la_tienda", falsa)

    async def escenario():
        primera = asyncio.create_task(ml_comisiones.actualizar_comisiones_en_segundo_plano(None, 7, None))
        await asyncio.sleep(0)
        await ml_comisiones.actualizar_comisiones_en_segundo_plano(None, 7, None)  # se omite: ya hay una en curso
        assert llamadas == [7]
        liberar.set()
        await primera
        await ml_comisiones.actualizar_comisiones_en_segundo_plano(None, 7, None)  # terminada la primera, corre de nuevo
        assert llamadas == [7, 7]

    asyncio.run(escenario())


def test_actualizar_comisiones_no_mantiene_la_conexion_mientras_espera_a_mercado_libre(db_session, a_store):
    producto = Product(store=a_store, internal_sku="CONN-1", name="Cuaderno universitario", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    db_session.add(ProductVariant(product=producto, store_id=a_store.id, variant_sku="CONN-1", price=5000, cost_price=3000, created_at=NOW, updated_at=NOW))
    db_session.commit()

    class AdapterFalso:
        async def predict_category(self, nombre, site_id):  # noqa: ARG002
            assert not db_session.in_transaction(), "conexión tomada durante /domain_discovery"
            return {"categoryId": "MLC180937", "categoryName": "Cuadernos"}

        async def get_listing_fees(self, access_token, site_id, category_id, precio):  # noqa: ARG002
            assert not db_session.in_transaction(), "conexión tomada durante /listing_prices"
            return FEES_CUADERNOS

    resultado = asyncio.run(ml_comisiones.actualizar_comisiones_reales(db_session, a_store.id, AdapterFalso(), "token", "MLC"))

    assert resultado["combinacionesComisionActualizadas"] == 1
    db_session.expire_all()
    assert db_session.get(Product, producto.id).ml_category_id == "MLC180937"
