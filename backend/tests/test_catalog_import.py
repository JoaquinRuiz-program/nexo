"""
Pruebas de app/domain/catalog_import.py — en particular, que la detección
de columnas funciona con nombres distintos a los de cualquier cliente en
particular (el pedido central de "catálogo universal", 24 de agosto de 2026).
"""

from __future__ import annotations

from app.domain.catalog_import import build_rows, detect_columns, summarize_rows


def test_detecta_columnas_con_los_nombres_exactos_del_excel_original():
    mapping = detect_columns(["SKU", "Nombre", "Marca", "Categoría", "Precio", "Costo", "Stock", "Descripción", "Imagen", "Código de barras"])
    assert mapping.get("sku") == "SKU"
    assert mapping.get("nombre") == "Nombre"
    assert mapping.get("precio") == "Precio"
    assert mapping.get("costo") == "Costo"
    assert mapping.get("codigo_barras") == "Código de barras"


def test_detecta_columnas_con_sinonimos_distintos():
    mapping = detect_columns(["Codigo", "Producto", "Precio venta", "Existencias", "Fabricante"])
    assert mapping.get("sku") == "Codigo"
    assert mapping.get("nombre") == "Producto"
    assert mapping.get("precio") == "Precio venta"
    assert mapping.get("stock") == "Existencias"
    assert mapping.get("marca") == "Fabricante"


def test_detecta_columnas_del_excel_desordenado_del_dueno():
    # Exactamente el ejemplo que dio el dueño: "Producto | Codigo | Precio venta | Existencia | Marca | costo compra"
    mapping = detect_columns(["Producto", "Codigo", "Precio venta", "Existencia", "Marca", "costo compra"])
    assert mapping.get("nombre") == "Producto"
    assert mapping.get("sku") == "Codigo"
    assert mapping.get("precio") == "Precio venta"
    assert mapping.get("stock") == "Existencia"
    assert mapping.get("marca") == "Marca"
    assert mapping.get("costo") == "costo compra"
    # Sin columna de categoría/descripción/imagen -> no se inventa un match
    assert mapping.get("categoria") is None
    assert mapping.get("descripcion") is None


def test_cuando_hay_dos_columnas_candidatas_gana_el_sinonimo_mas_especifico():
    """Caso real de prueba: una planilla puede traer "Código" (código
    interno de bodega) Y "SKU" a la vez. "SKU" tiene que ganar para el
    campo sku porque matchea el sinónimo exacto más específico — "Código"
    debería quedar libre para otro uso, no perderlo por orden de columnas."""
    mapping = detect_columns(["Código", "SKU", "Producto", "Marca", "Precio compra", "Precio venta", "Cantidad", "Descripción", "EAN", "Imagen"])
    assert mapping.get("sku") == "SKU"
    assert mapping.get("costo") == "Precio compra"
    assert mapping.get("precio") == "Precio venta"
    assert mapping.get("stock") == "Cantidad"
    assert mapping.get("codigo_barras") == "EAN"


def test_columna_ya_usada_no_se_reutiliza_para_otro_campo():
    # "id" podría matchear sku, pero si ya hay una columna "SKU" explícita,
    # "id" no debería robarle el lugar a otro campo por casualidad.
    mapping = detect_columns(["SKU", "id_interno_para_otra_cosa"])
    assert mapping.get("sku") == "SKU"


def test_producto_valido_no_tiene_problemas():
    rows = build_rows(
        [{"SKU": "LIB-001", "Nombre": "Cuaderno", "Precio": "3990", "Costo": "2000", "Stock": "10",
          "Categoría": "Cuadernos", "Descripción": "Cuaderno universitario", "Imagen": "http://x.test/a.png"}],
        detect_columns(["SKU", "Nombre", "Precio", "Costo", "Stock", "Categoría", "Descripción", "Imagen"]),
    )
    assert rows[0].estado == "valido"
    assert rows[0].problemas == []
    assert rows[0].precio == 3990
    assert rows[0].costo == 2000
    assert rows[0].stock == 10


def test_falta_nombre_es_bloqueante():
    mapping = detect_columns(["SKU", "Nombre", "Precio"])
    rows = build_rows([{"SKU": "A", "Nombre": "", "Precio": "1000"}], mapping)
    assert rows[0].estado == "error"
    assert "Falta nombre" in rows[0].problemas


def test_falta_sku_no_es_bloqueante_solo_revision():
    """El modelo de datos ya acepta productos sin SKU (WooCommerce real los
    trae así) — no debería bloquear la importación."""
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows([{"Nombre": "Producto sin SKU", "Precio": "1000"}], mapping)
    assert rows[0].estado == "revision"
    assert "Falta SKU" in rows[0].problemas


def test_precio_no_numerico_es_bloqueante():
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "no-es-un-numero"}], mapping)
    assert rows[0].estado == "error"
    assert any("Precio no válido" in p for p in rows[0].problemas)


def test_acepta_formato_chileno_de_numero():
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "18.500,50"}], mapping)
    assert rows[0].precio == 18500.50


def test_sku_duplicado_se_marca_en_ambas_filas():
    mapping = detect_columns(["SKU", "Nombre"])
    rows = build_rows(
        [{"SKU": "LIB-001", "Nombre": "Producto A"}, {"SKU": "lib-001", "Nombre": "Producto B"}],
        mapping,
    )
    assert rows[0].duplicado is True
    assert rows[1].duplicado is True
    assert rows[0].estado == "error"
    assert rows[1].estado == "error"


def test_nombre_duplicado_sin_sku_es_revision_no_error():
    mapping = detect_columns(["Nombre"])
    rows = build_rows([{"Nombre": "Cuaderno"}, {"Nombre": "Cuaderno"}], mapping)
    assert rows[0].duplicado is True
    assert rows[0].estado == "revision"  # no es "error" porque no hay SKU duplicado, solo nombre


def test_resumen_cuenta_por_estado():
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows(
        [
            {"Nombre": "Producto A", "Precio": "1000"},  # revision (falta sku/categoria/etc)
            {"Nombre": "", "Precio": "1000"},  # error (falta nombre)
        ],
        mapping,
    )
    resumen = summarize_rows(rows)
    assert resumen["totalFilas"] == 2
    assert resumen["errores"] == 1
    assert resumen["revision"] == 1
