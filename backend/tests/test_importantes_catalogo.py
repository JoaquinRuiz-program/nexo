"""
Importantes 15 y 16 de REVISION_EXPERIENCIA.md (15 de septiembre de 2026):
stock del catálogo como stock para Mercado Libre y reimportar sin SKU sin
duplicar productos.
"""

from __future__ import annotations

import io
import json

from app.db.models import Product, ProductVariant
from tests.test_catalogo_endpoints import a_store, client, db_session  # noqa: F401 — fixtures

CSV_SIN_SKU = "Producto,Costo,Precio,Stock\nLámpara luna 3D,6500,14990,5\nBotella térmica,5200,8990,10\n"
MAPEO_SIN_SKU = {"nombre": "Producto", "costo": "Costo", "precio": "Precio", "stock": "Stock"}


def _importar(client, csv, mapeo):
    return client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("catalogo.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")},
        data={"mapeo": json.dumps(mapeo)},
    )


def test_reimportar_sin_sku_actualiza_por_nombre_en_vez_de_duplicar(client, db_session, a_store):
    primera = _importar(client, CSV_SIN_SKU, MAPEO_SIN_SKU).json()
    segunda = _importar(client, CSV_SIN_SKU.replace("14990", "15990"), MAPEO_SIN_SKU).json()

    assert primera["creados"] == 2
    assert segunda["creados"] == 0
    assert segunda["actualizados"] == 2
    assert db_session.query(Product).filter_by(store_id=a_store.id).count() == 2
    lampara = db_session.query(ProductVariant).join(Product).filter(Product.name == "Lámpara luna 3D").one()
    assert float(lampara.price) == 15990


def test_sin_sku_con_nombre_repetido_en_la_tienda_no_adivina(client, db_session, a_store):
    _importar(client, "Producto,Precio\nTaza,1000\n", {"nombre": "Producto", "precio": "Precio"})
    _importar(client, "Producto,Precio\nTaza,1000\n", {"nombre": "Producto", "precio": "Precio"})  # actualiza (hay una sola)
    producto = db_session.query(Product).filter_by(store_id=a_store.id, name="Taza").one()
    # Se crea a mano una segunda "Taza" sin SKU: ya no hay forma segura de elegir.
    otra = Product(store=a_store, name="Taza", product_type="simple", created_at=producto.created_at, updated_at=producto.updated_at)
    db_session.add(otra)
    db_session.flush()
    db_session.add(ProductVariant(product=otra, store_id=a_store.id, price=1000, created_at=producto.created_at, updated_at=producto.updated_at))
    db_session.commit()

    body = _importar(client, "Producto,Precio\nTaza,2000\n", {"nombre": "Producto", "precio": "Precio"}).json()

    assert body["creados"] == 1
    assert db_session.query(Product).filter_by(store_id=a_store.id, name="Taza").count() == 3


def test_usar_el_stock_de_cada_producto_para_mercado_libre(client, db_session, a_store):
    _importar(client, CSV_SIN_SKU + "Sin stock,1000,2000,\n", MAPEO_SIN_SKU)

    res = client.put("/api/productos/stock-mercadolibre/lote", json={"usarStock": True})

    assert res.status_code == 200, res.text
    assert res.json()["actualizados"] == 2
    por_nombre = {
        v.product.name: v.marketplace_stock
        for v in db_session.query(ProductVariant).filter_by(store_id=a_store.id).all()
    }
    assert por_nombre == {"Lámpara luna 3D": 5, "Botella térmica": 10, "Sin stock": None}


def test_aplicar_una_cantidad_a_todos_sigue_funcionando(client, db_session, a_store):
    _importar(client, CSV_SIN_SKU, MAPEO_SIN_SKU)
    res = client.put("/api/productos/stock-mercadolibre/lote", json={"cantidad": 3})
    assert res.json()["actualizados"] == 2
    assert {v.marketplace_stock for v in db_session.query(ProductVariant).filter_by(store_id=a_store.id).all()} == {3}
