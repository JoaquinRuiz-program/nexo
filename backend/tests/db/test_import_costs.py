"""
Pruebas de app/db/import_costs.py — CSV y XLSX, en particular que un SKU
desconocido o un costo inválido se reportan en vez de romper el import o
inventar un dato.
"""

from __future__ import annotations

import openpyxl
import pytest

from app.db.import_costs import import_costs_from_path
from app.db.models import Product, ProductVariant


def _crear_producto(db_session, a_store, now, *, sku, nombre):
    producto = Product(store=a_store, internal_sku=sku, name=nombre, product_type="simple", created_at=now, updated_at=now)
    db_session.add(producto)
    db_session.flush()
    variante = ProductVariant(
        product=producto, store_id=a_store.id, variant_sku=sku, price=10000, created_at=now, updated_at=now
    )
    db_session.add(variante)
    db_session.commit()
    return variante


def _crear_xlsx(path, filas: list[tuple[str, object]]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["sku", "costo"])
    for sku, costo in filas:
        ws.append([sku, costo])
    wb.save(path)


def test_actualiza_el_costo_de_un_sku_existente_desde_csv(db_session, a_store, now, tmp_path):
    variante = _crear_producto(db_session, a_store, now, sku="LIB-001", nombre="Cien años de soledad")
    csv_path = tmp_path / "costos.csv"
    csv_path.write_text("sku,costo\nLIB-001,8500\n", encoding="utf-8")

    resultado = import_costs_from_path(csv_path, db_session)

    db_session.refresh(variante)
    assert float(variante.cost_price) == 8500.0
    assert resultado.actualizados == ["LIB-001"]
    assert resultado.no_encontrados == []


def test_actualiza_el_costo_de_un_sku_existente_desde_xlsx(db_session, a_store, now, tmp_path):
    variante = _crear_producto(db_session, a_store, now, sku="LIB-004", nombre="1984")
    xlsx_path = tmp_path / "costos.xlsx"
    _crear_xlsx(xlsx_path, [("LIB-004", 9990)])

    resultado = import_costs_from_path(xlsx_path, db_session)

    db_session.refresh(variante)
    assert float(variante.cost_price) == 9990.0
    assert resultado.actualizados == ["LIB-004"]


def test_xlsx_ignora_filas_vacias_al_final_de_la_hoja(db_session, a_store, now, tmp_path):
    variante = _crear_producto(db_session, a_store, now, sku="LIB-005", nombre="El principito")
    xlsx_path = tmp_path / "costos.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["sku", "costo"])
    ws.append(["LIB-005", 4500])
    ws.append([None, None])  # fila en blanco, como suele quedar en un Excel real
    wb.save(xlsx_path)

    resultado = import_costs_from_path(xlsx_path, db_session)

    db_session.refresh(variante)
    assert float(variante.cost_price) == 4500.0
    assert resultado.actualizados == ["LIB-005"]
    assert resultado.filas_invalidas == []


def test_reporta_sku_no_encontrado_sin_crear_nada(db_session, a_store, now, tmp_path):
    csv_path = tmp_path / "costos.csv"
    csv_path.write_text("sku,costo\nNO-EXISTE,1000\n", encoding="utf-8")

    resultado = import_costs_from_path(csv_path, db_session)

    assert resultado.no_encontrados == ["NO-EXISTE"]
    assert resultado.actualizados == []
    assert db_session.query(Product).count() == 0


def test_reporta_costo_invalido_sin_aplicarlo(db_session, a_store, now, tmp_path):
    variante = _crear_producto(db_session, a_store, now, sku="LIB-002", nombre="Rayuela")
    csv_path = tmp_path / "costos.csv"
    csv_path.write_text("sku,costo\nLIB-002,no-es-un-numero\n", encoding="utf-8")

    resultado = import_costs_from_path(csv_path, db_session)

    db_session.refresh(variante)
    assert variante.cost_price is None
    assert resultado.filas_invalidas == ["LIB-002: costo inválido ('no-es-un-numero')"]


def test_acepta_formato_chileno_de_numero_en_csv(db_session, a_store, now, tmp_path):
    variante = _crear_producto(db_session, a_store, now, sku="MOC-001", nombre="Mochila")
    csv_path = tmp_path / "costos.csv"
    csv_path.write_text("sku,costo\nMOC-001,\"18.500,50\"\n", encoding="utf-8")

    import_costs_from_path(csv_path, db_session)

    db_session.refresh(variante)
    assert float(variante.cost_price) == 18500.50


def test_columnas_en_mayusculas_tambien_funcionan(db_session, a_store, now, tmp_path):
    variante = _crear_producto(db_session, a_store, now, sku="LIB-003", nombre="1984")
    csv_path = tmp_path / "costos.csv"
    csv_path.write_text("SKU,Costo\nLIB-003,5000\n", encoding="utf-8")

    import_costs_from_path(csv_path, db_session)

    db_session.refresh(variante)
    assert float(variante.cost_price) == 5000.0


def test_sku_numerico_en_excel_se_normaliza_a_texto(db_session, a_store, now, tmp_path):
    """Excel a veces guarda un SKU que parece número como float (12345 ->
    12345.0) — no debe dejar de matchear contra el SKU real guardado como texto."""
    variante = _crear_producto(db_session, a_store, now, sku="12345", nombre="Producto con SKU numérico")
    xlsx_path = tmp_path / "costos.xlsx"
    _crear_xlsx(xlsx_path, [(12345, 3000)])

    resultado = import_costs_from_path(xlsx_path, db_session)

    db_session.refresh(variante)
    assert float(variante.cost_price) == 3000.0
    assert resultado.actualizados == ["12345"]


def test_formato_no_soportado_se_reporta_como_error(db_session, a_store, now, tmp_path):
    txt_path = tmp_path / "costos.txt"
    txt_path.write_text("sku,costo\nLIB-001,8500\n", encoding="utf-8")

    with pytest.raises(ValueError):
        import_costs_from_path(txt_path, db_session)
