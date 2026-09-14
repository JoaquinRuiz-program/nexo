"""
Pruebas de app/domain/catalog_selection.py — el motor de "¿qué conviene
publicar en Mercado Libre?" pedido el 24 de agosto de 2026.
"""

from __future__ import annotations

from app.domain.catalog_selection import SelectionCriteria, classify_product, select, summarize_selection


def _row(**overrides):
    base = {
        "id": 1,
        "sku": "LIB-001",
        "tieneCosto": True,
        "marketplaceStock": 5,
        "margenTiendaClp": 3000,
        "margenTiendaPct": 30.0,
        "mercadoLibreConfigurado": False,
        "margenMercadoLibreClp": None,
        "margenMercadoLibrePct": None,
    }
    base.update(overrides)
    return base


def test_producto_sin_costo_es_sin_datos():
    resultado = classify_product(_row(tieneCosto=False), SelectionCriteria())
    assert resultado["clasificacion"] == "sin_datos"


def test_producto_con_costo_pero_sin_precio_es_sin_datos_no_rentable():
    """Caso real encontrado probando con datos reales (24 de agosto de
    2026): tieneCosto=True no alcanza si falta el precio — sin él,
    gross_margin ya devuelve None, y antes de este fix el producto caía en
    "rentable" por descarte en vez de "sin_datos"."""
    resultado = classify_product(_row(margenTiendaClp=None, margenTiendaPct=None), SelectionCriteria())
    assert resultado["clasificacion"] == "sin_datos"


def test_sin_stock_NO_afecta_la_rentabilidad_por_defecto():
    """13 de septiembre de 2026 — pedido del dueño: rentable/no rentable se
    juzga SOLO por el margen monetario. Sin stock, un producto rentable
    sigue siendo rentable (el stock se completa aparte, en la revisión)."""
    resultado = classify_product(_row(marketplaceStock=0), SelectionCriteria())
    assert resultado["clasificacion"] == "rentable"

    resultado = classify_product(_row(marketplaceStock=None), SelectionCriteria())
    assert resultado["clasificacion"] == "rentable"


def test_el_requisito_de_stock_sigue_disponible_si_se_pide_explicito():
    """El gate de publicar NO lo usa más (chequea el stock aparte), pero la
    opción sigue existiendo para un caso especial."""
    resultado = classify_product(_row(marketplaceStock=0), SelectionCriteria(require_marketplace_stock=True))
    assert resultado["clasificacion"] == "sin_stock"


def test_margen_negativo_es_no_rentable_con_razon_explicita():
    resultado = classify_product(_row(margenTiendaClp=-1200), SelectionCriteria())
    assert resultado["clasificacion"] == "no_rentable"
    assert "-$1.200" in resultado["razon"] or "-1.200" in resultado["razon"]


def test_margen_por_debajo_del_minimo_pedido_es_margen_bajo():
    resultado = classify_product(_row(margenTiendaPct=4.2), SelectionCriteria(min_margin_pct=20))
    assert resultado["clasificacion"] == "margen_bajo"
    assert "4.2%" in resultado["razon"]


def test_margen_que_supera_el_minimo_es_rentable():
    resultado = classify_product(_row(margenTiendaClp=8000), SelectionCriteria(min_margin_clp=5000))
    assert resultado["clasificacion"] == "rentable"
    assert resultado["razon"] is None


def test_canal_mercadolibre_sin_configurar_es_sin_datos():
    resultado = classify_product(_row(mercadoLibreConfigurado=False), SelectionCriteria(channel="mercadolibre"))
    assert resultado["clasificacion"] == "sin_datos"


def test_canal_mercadolibre_configurado_usa_el_margen_neto():
    resultado = classify_product(
        _row(mercadoLibreConfigurado=True, margenMercadoLibreClp=300, margenMercadoLibrePct=3.0),
        SelectionCriteria(channel="mercadolibre"),
    )
    assert resultado["clasificacion"] == "rentable"


def test_top_n_deja_fuera_a_los_rentables_que_no_entran_en_el_cupo():
    rows = [
        _row(id=1, margenTiendaClp=9000),
        _row(id=2, margenTiendaClp=5000),
        _row(id=3, margenTiendaClp=1000),
    ]
    resultado = select(rows, SelectionCriteria(), top_n=2)
    por_id = {r["id"]: r["clasificacion"] for r in resultado}
    assert por_id[1] == "rentable"
    assert por_id[2] == "rentable"
    assert por_id[3] == "no_seleccionado"


def test_resumen_cuenta_cada_clasificacion():
    rows = select(
        [
            _row(id=1, margenTiendaClp=9000),
            _row(id=2, tieneCosto=False),
            _row(id=3, marketplaceStock=0),   # sin stock YA NO afecta: es rentable
            _row(id=4, margenTiendaClp=-500),
        ],
        SelectionCriteria(),
    )
    resumen = summarize_selection(rows)
    assert resumen == {
        "total": 4,
        "rentables": 2,          # el sin-stock (id 3) ahora cuenta como rentable
        "margenBajo": 0,
        "noRentables": 1,
        "sinStock": 0,
        "sinDatos": 1,
        "noSeleccionados": 0,
    }
