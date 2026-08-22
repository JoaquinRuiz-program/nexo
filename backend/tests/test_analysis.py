from app.domain.analysis import (
    build_productos_list,
    detect_duplicates,
    expand_variable_products,
    find_barcode_candidates,
    products_without_description,
    products_without_sku,
    summarize_catalog,
)


def product(**overrides) -> dict:
    base = {
        "id": 1,
        "sku": "LIB-0001",
        "name": "Producto de prueba",
        "type": "simple",
        "description": "Una descripción cualquiera.",
        "stock_quantity": 10,
        "manage_stock": True,
        "stock_status": "instock",
        "categories": [{"id": 1, "name": "Cuadernos"}],
        "images": [{"id": 1, "src": "http://example.test/a.png"}],
        "meta_data": [],
    }
    base.update(overrides)
    return base


def test_producto_sin_sku_se_detecta():
    products = [product(id=1, sku="LIB-0001"), product(id=2, sku="")]
    sin_sku = products_without_sku(products)
    assert len(sin_sku) == 1
    assert sin_sku[0]["id"] == 2


def test_descripcion_vacia_se_detecta():
    products = [product(id=1, description="algo"), product(id=2, description=""), product(id=3, description="   ")]
    assert len(products_without_description(products)) == 2


def test_sku_duplicado_se_agrupa():
    products = [
        product(id=3, sku="LIB-0003", name="Mochila Head"),
        product(id=4, sku="LIB-0003", name="Mochila Head"),
        product(id=5, sku="LIB-0005", name="Carpeta Oficio"),
    ]
    dup = detect_duplicates(products)
    assert len(dup) == 1
    assert dup[0]["criterio"] == "sku"
    assert sorted(p["woocommerce_id"] for p in dup[0]["productos"]) == [3, 4]


def test_find_barcode_candidates_sin_asumir_cual_es_correcta():
    products = [
        product(id=1, meta_data=[{"key": "codigo_prod", "value": "7801234560012"}]),
        product(id=2, meta_data=[{"key": "_lc_test_case", "value": "control"}]),
        product(id=3, meta_data=[{"key": "color", "value": "azul"}]),
    ]
    keys = sorted(c["key"] for c in find_barcode_candidates(products))
    assert keys == ["codigo_prod"]


def test_resumen_cuenta_categorias_distintas():
    products = [
        product(id=1, categories=[{"id": 1, "name": "Cuadernos"}]),
        product(id=2, categories=[{"id": 2, "name": "Arte"}]),
    ]
    summary = summarize_catalog(products)
    assert summary["cantidadCategorias"] == 2
    assert summary["categorias"] == ["Arte", "Cuadernos"]


def test_expand_variable_products_simple_pasa_sin_cambios():
    products = [product(id=1, type="simple")]
    expanded = expand_variable_products(products, {})
    assert len(expanded) == 1
    assert expanded[0]["esVariante"] is False


def test_expand_variable_products_variable_se_reemplaza_por_una_fila_por_color():
    products = [product(id=50, type="variable", sku="", name="ARCHIVADOR PLASTIFICADO", manage_stock=False, stock_quantity=None)]
    variations_by_id = {
        50: [
            {"id": 501, "sku": "ARCH-ROJO", "manage_stock": True, "stock_quantity": 12, "attributes": [{"name": "Colores disponibles", "option": "Rojo"}]},
            {"id": 502, "sku": "ARCH-AZUL", "manage_stock": True, "stock_quantity": 7, "attributes": [{"name": "Colores disponibles", "option": "Azul"}]},
        ]
    }
    expanded = expand_variable_products(products, variations_by_id)

    assert len(expanded) == 2
    assert sorted(p["id"] for p in expanded) == [501, 502]
    assert sorted(p["sku"] for p in expanded) == ["ARCH-AZUL", "ARCH-ROJO"]
    assert all(p["esVariante"] for p in expanded)
    assert all(p["woocommerceParentId"] == 50 for p in expanded)
    rojo = next(p for p in expanded if p["colorVariante"] == "Rojo")
    assert rojo["name"] == "ARCHIVADOR PLASTIFICADO - Rojo"


def test_expand_variable_products_sin_variaciones_conserva_el_padre():
    products = [product(id=60, type="variable")]
    expanded = expand_variable_products(products, {})
    assert len(expanded) == 1
    assert expanded[0]["id"] == 60
    assert expanded[0]["esVariante"] is False


def test_build_productos_list_incluye_los_campos_que_necesita_la_tabla():
    products = [
        product(id=1, sku="LIB-0001", name="Cuaderno Torre", type="simple", stock_quantity=10, manage_stock=True),
        product(id=2, sku="", name="Producto sin sku", type="simple", stock_quantity=None, manage_stock=False),
    ]
    products[0]["price"] = "3500"
    products[0]["stock_status"] = "instock"
    products[1]["price"] = ""
    products[1]["stock_status"] = "instock"

    filas = build_productos_list(products)

    assert len(filas) == 2
    assert filas[0] == {
        "id": 1,
        "sku": "LIB-0001",
        "nombre": "Cuaderno Torre",
        "tipo": "simple",
        "precio": "3500",
        "stockQuantity": 10,
        "gestionaStock": True,
        "estadoStock": "instock",
        "esVariante": False,
        "colorVariante": None,
        "woocommerceParentId": None,
    }
    # Sin sku ni gestión de stock: no se inventa nada, se pasa vacío/None tal cual.
    assert filas[1]["sku"] == ""
    assert filas[1]["precio"] == ""
    assert filas[1]["stockQuantity"] is None
    assert filas[1]["gestionaStock"] is False


def test_build_productos_list_conserva_datos_de_color_en_filas_expandidas():
    products = [product(id=50, type="variable", sku="", name="ARCHIVADOR PLASTIFICADO", manage_stock=False, stock_quantity=None)]
    variations_by_id = {
        50: [
            {"id": 501, "sku": "ARCH-ROJO", "manage_stock": True, "stock_quantity": 12, "price": "2990", "attributes": [{"name": "Colores disponibles", "option": "Rojo"}]},
        ]
    }
    expanded = expand_variable_products(products, variations_by_id)
    filas = build_productos_list(expanded)

    assert len(filas) == 1
    assert filas[0]["id"] == 501
    assert filas[0]["sku"] == "ARCH-ROJO"
    assert filas[0]["nombre"] == "ARCHIVADOR PLASTIFICADO - Rojo"
    assert filas[0]["precio"] == "2990"
    assert filas[0]["esVariante"] is True
    assert filas[0]["colorVariante"] == "Rojo"
    assert filas[0]["woocommerceParentId"] == 50
