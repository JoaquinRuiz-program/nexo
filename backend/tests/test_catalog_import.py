"""
Pruebas de app/domain/catalog_import.py — en particular, que la detección
de columnas funciona con nombres distintos a los de cualquier cliente en
particular (el pedido central de "catálogo universal", 24 de agosto de 2026).
"""

from __future__ import annotations

import pytest

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


def test_precio_de_compra_es_costo_y_precio_de_venta_recomendado_es_precio():
    """Caso real (Inventario_200_Productos_V2.xlsx, 14/09/2026): antes el
    precio de COMPRA quedaba como precio de venta y el costo vacío, así que
    no se podía calcular ningún margen."""
    from app.domain.catalog_import import build_rows, detect_columns

    headers = ["Nombre", "SKU", "Precio de Compra", "Precio de Venta Recomendado"]
    filas = [{"Nombre": "Zapatilla adidas F50 Club Suela IN/Sala", "SKU": "DEP-001", "Precio de Compra": 45000.0, "Precio de Venta Recomendado": 74990.0}]

    mapping = detect_columns(headers, filas)

    assert mapping.get("costo") == "Precio de Compra"
    assert mapping.get("precio") == "Precio de Venta Recomendado"
    fila = build_rows(filas, mapping)[0]
    assert (fila.costo, fila.precio) == (45000.0, 74990.0)
    assert "Falta costo de compra" not in fila.problemas


def test_encabezados_simples_de_venta_y_compra():
    from app.domain.catalog_import import detect_columns

    mapping = detect_columns(["Producto", "Código", "Valor venta", "Valor compra"])
    assert mapping.get("precio") == "Valor venta"
    assert mapping.get("costo") == "Valor compra"


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


def test_excel_real_minimo_no_se_queja_de_lo_que_nexo_resuelve_solo():
    """13 de septiembre de 2026 — el Excel tipico de una tienda trae solo
    codigo, nombre, costo y precio. La categoria la predice Mercado Libre a
    partir del nombre y la descripcion la arma domain/ai_content.py, asi que
    ninguna de las dos debe ensuciar el resumen de importacion: solo se avisa
    de lo que necesita que una persona haga algo."""
    mapping = detect_columns(["Codigo", "Nombre", "Precio compra", "Precio venta"])
    rows = build_rows(
        [{"Codigo": "A-100", "Nombre": "Hervidor electrico 1.7L", "Precio compra": "14.900", "Precio venta": "32.990"}],
        mapping,
    )
    # 15/09/2026 — sin imagen ni stock la fila igual está lista: esos avisos son informativos.
    assert rows[0].estado == "valido"
    assert rows[0].costo == 14900
    assert rows[0].precio == 32990
    assert "Falta categoría" not in rows[0].problemas
    assert "Falta descripción" not in rows[0].problemas
    # Lo que si requiere accion humana
    assert "Falta imagen" in rows[0].problemas
    assert "Completa el stock al revisar" in rows[0].problemas


def test_stock_cero_no_es_un_stock_faltante():
    mapping = detect_columns(["Nombre", "Precio", "Stock"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "1000", "Stock": "0"}], mapping)
    assert rows[0].stock == 0
    assert "Completa el stock al revisar" not in rows[0].problemas


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


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        # El caso que originó el bug (13 de septiembre de 2026): un precio
        # chileno SIN decimales, exportado como texto. `float("3.990")` no
        # falla — devuelve 3.99 — así que antes entraba mil veces más bajo,
        # en silencio y sin marcar la fila como error.
        ("3.990", 3990),
        ("3.900", 3900),
        ("1.234.567", 1234567),
        ("12.345", 12345),
        # Sin separadores.
        ("3990", 3990),
        # Punto decimal de verdad: NO son grupos de tres dígitos.
        ("3990.50", 3990.50),
        ("3.14", 3.14),
        # Coma decimal sola.
        ("0,5", 0.5),
        ("18500,50", 18500.50),
        # Los dos símbolos: manda el que aparece último.
        ("3.990,50", 3990.50),   # chileno
        ("3,990.50", 3990.50),   # inglés
        ("1.234.567,89", 1234567.89),
        # Con símbolo de moneda y espacios alrededor.
        ("$ 3.990", 3990),
        # Negativos.
        ("-3.990", -3990),
    ],
)
def test_separador_de_miles_vs_decimal(crudo, esperado):
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows([{"Nombre": "Producto", "Precio": crudo}], mapping)
    assert rows[0].precio == esperado
    assert rows[0].estado != "error"


def test_numero_ilegible_sigue_siendo_bloqueante():
    """El arreglo del separador no puede hacer que basura entre como válida."""
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "1.000.00"}], mapping)
    assert rows[0].precio is None
    assert rows[0].estado == "error"


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


# ------------------------------------------------------------------
# El stock NUNCA bloquea la importación — 13 de septiembre de 2026.
# ------------------------------------------------------------------


def test_sin_columna_de_stock_el_producto_se_importa_igual():
    mapping = detect_columns(["Nombre", "Precio"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "2000"}], mapping)
    assert rows[0].estado != "error"
    assert rows[0].stock is None
    assert "Completa el stock al revisar" in rows[0].problemas


def test_stock_no_numerico_no_bloquea_se_ignora():
    mapping = detect_columns(["Nombre", "Precio", "Stock"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "2000", "Stock": "no-es-numero"}], mapping)
    assert rows[0].estado != "error"     # antes era "error"
    assert rows[0].stock is None         # el valor basura se ignora


def test_stock_cero_sigue_siendo_cero_no_falta():
    mapping = detect_columns(["Nombre", "Precio", "Stock"])
    rows = build_rows([{"Nombre": "Producto", "Precio": "2000", "Stock": "0"}], mapping)
    assert rows[0].stock == 0
    assert "Completa el stock al revisar" not in rows[0].problemas


# ------------------------------------------------------------------
# Detección de columnas por CONTENIDO — 13 de septiembre de 2026.
# ------------------------------------------------------------------


def test_detecta_imagen_y_codigo_de_barras_por_contenido_con_encabezados_cripticos():
    headers = ["A", "B", "C", "D"]
    rows = [
        {"A": "Cuaderno universitario 100 hojas", "B": "2990", "C": "https://cdn.x/a.jpg", "D": "7801234567890"},
        {"A": "Lápiz grafito HB caja x12", "B": "990", "C": "https://cdn.x/b.jpg", "D": "7801234567891"},
        {"A": "Goma de borrar blanca", "B": "690", "C": "https://cdn.x/c.jpg", "D": "7801234567892"},
    ]
    m = detect_columns(headers, rows)
    assert m.get("imagen_url") == "C"       # URLs
    assert m.get("codigo_barras") == "D"    # 13 dígitos
    assert m.get("nombre") == "A"           # texto largo con letras


def test_precio_y_costo_NO_se_adivinan_por_contenido():
    """Confundir cuál columna numérica es el precio corrompería el catálogo:
    esas quedan sin mapear (se preguntan en la revisión)."""
    headers = ["X", "Y"]
    rows = [{"X": "1000", "Y": "2500"}, {"X": "1200", "Y": "3000"}]
    m = detect_columns(headers, rows)
    assert m.get("precio") is None
    assert m.get("costo") is None


def test_el_nombre_por_sinonimo_gana_sobre_el_contenido():
    m = detect_columns(["Producto", "Foto"], [{"Producto": "Algo", "Foto": "https://x/a.jpg"}])
    assert m.get("nombre") == "Producto"
    assert m.get("imagen_url") == "Foto"


def test_sin_filas_la_deteccion_por_contenido_no_corre():
    # Solo por nombre; un encabezado críptico queda sin mapear.
    m = detect_columns(["A", "B"])
    assert m.get("nombre") is None
