"""
Críticos 4 a 7 de REVISION_EXPERIENCIA.md (15 de septiembre de 2026):
detección de columnas del importador, revisión con mapeo corregido y aviso
del límite del plan.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime

from app.db.models import Plan, Product, Subscription
from app.domain.catalog_import import detect_columns
from tests.test_catalogo_endpoints import a_store, client, db_session  # noqa: F401 — fixtures

NOW = datetime(2026, 9, 15, 12, 0, 0)


# ------------------------------------------------------------------
# Detección de columnas (pura)
# ------------------------------------------------------------------


def test_descripcion_con_textos_cortos_es_el_nombre_si_no_hay_columna_nombre():
    headers = ["Código", "Descripción", "Marca", "Costo unitario neto", "Precio retail"]
    filas = [{"Código": f"IMP{i}", "Descripción": f"Audífonos bluetooth modelo {i}", "Marca": "Xtech", "Costo unitario neto": "3000", "Precio retail": "9990"} for i in range(5)]
    mapeo = detect_columns(headers, filas)
    assert mapeo.get("nombre") == "Descripción"
    assert mapeo.get("descripcion") is None


def test_descripcion_larga_sigue_siendo_descripcion():
    headers = ["SKU", "Descripción", "Precio"]
    texto_largo = "Audífonos inalámbricos con cancelación de ruido, 30 horas de batería, estuche de carga y micrófono incluido para llamadas."
    filas = [{"SKU": f"A{i}", "Descripción": texto_largo, "Precio": "9990"} for i in range(5)]
    mapeo = detect_columns(headers, filas)
    assert mapeo.get("nombre") is None
    assert mapeo.get("descripcion") == "Descripción"


def test_con_precio_mayorista_y_retail_elige_el_retail():
    mapeo = detect_columns(["Código", "Producto", "Costo unitario neto", "Precio mayorista", "Precio retail", "Unidades"])
    assert mapeo.get("precio") == "Precio retail"
    assert mapeo.get("costo") == "Costo unitario neto"
    assert mapeo.get("stock") == "Unidades"


def test_precio_de_venta_gana_aunque_el_mayorista_venga_primero():
    assert detect_columns(["Nombre", "Precio mayorista", "Precio venta público"]).get("precio") == "Precio venta público"


def test_un_solo_precio_mayorista_igual_se_propone():
    assert detect_columns(["Nombre", "Precio mayorista"]).get("precio") == "Precio mayorista"


def test_encabezados_informales_de_un_revendedor():
    mapeo = detect_columns(["Producto", "Lo compré a", "Lo vendo a", "Cuántos tengo"])
    assert mapeo.get("nombre") == "Producto"
    assert mapeo.get("costo") == "Lo compré a"
    assert mapeo.get("precio") == "Lo vendo a"
    assert mapeo.get("stock") == "Cuántos tengo"


# ------------------------------------------------------------------
# /analizar con mapeo corregido y límite del plan (endpoints)
# ------------------------------------------------------------------

CSV_REVENDEDOR = "Producto,Compra,Venta final,Tengo\nLámpara luna 3D,6500,14990,5\nBotella térmica,5200,8990,10\n"


def test_analizar_con_mapeo_corregido_recalcula_las_filas(client, a_store):
    archivo = CSV_REVENDEDOR.encode("utf-8")
    sin_costo = {"nombre": "Producto", "costo": None, "precio": None, "stock": None}
    corregido = {"nombre": "Producto", "costo": "Compra", "precio": "Venta final", "stock": "Tengo"}

    antes = client.post("/api/catalogo/importar/analizar", files={"file": ("r.csv", io.BytesIO(archivo), "text/csv")}, data={"mapeo": json.dumps(sin_costo)}).json()
    despues = client.post("/api/catalogo/importar/analizar", files={"file": ("r.csv", io.BytesIO(archivo), "text/csv")}, data={"mapeo": json.dumps(corregido)}).json()

    assert "Sin costo de compra: se calcula con costo $0" in antes["filas"][0]["problemas"]
    assert despues["mapeoPropuesto"] == corregido
    assert despues["filas"][0]["costo"] == 6500
    assert despues["filas"][0]["precio"] == 14990
    assert "Sin costo de compra: se calcula con costo $0" not in despues["filas"][0]["problemas"]


def test_analizar_con_mapeo_invalido_da_400(client, a_store):
    res = client.post("/api/catalogo/importar/analizar", files={"file": ("r.csv", io.BytesIO(CSV_REVENDEDOR.encode("utf-8")), "text/csv")}, data={"mapeo": "{no es json"})
    assert res.status_code == 400


def test_confirmar_informa_los_productos_omitidos_por_el_limite_del_plan(client, db_session, a_store):
    plan = Plan(code="mini-prueba", name="Mini", product_limit=1, price_demo_label="$0", features=[])
    db_session.add(plan)
    db_session.flush()
    sub = db_session.query(Subscription).filter_by(store_id=a_store.id).first()
    if sub is None:
        db_session.add(Subscription(store_id=a_store.id, plan_id=plan.id, status="active", started_at=NOW, current_period_end=date(2026, 10, 15)))
    else:
        sub.plan_id = plan.id
    db_session.commit()
    csv = "SKU,Nombre,Precio,Costo\nA1,Uno,1000,500\nA2,Dos,1000,500\nA3,Tres,1000,500\n"
    mapeo = {"sku": "SKU", "nombre": "Nombre", "precio": "Precio", "costo": "Costo"}

    res = client.post("/api/catalogo/importar/confirmar", files={"file": ("p.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}, data={"mapeo": json.dumps(mapeo)})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["creados"] == 1
    assert body["limitePlan"] == {"limite": 1, "omitidosPorLimite": 2}
    assert db_session.query(Product).filter_by(store_id=a_store.id).count() == 1


def test_confirmar_sin_limite_alcanzado_no_trae_aviso(client, a_store):
    csv = "SKU,Nombre,Precio,Costo\nB1,Uno,1000,500\n"
    mapeo = {"sku": "SKU", "nombre": "Nombre", "precio": "Precio", "costo": "Costo"}
    body = client.post("/api/catalogo/importar/confirmar", files={"file": ("p.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}, data={"mapeo": json.dumps(mapeo)}).json()
    assert body["limitePlan"] is None
