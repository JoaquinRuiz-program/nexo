"""
Pruebas de app/domain/listing_draft.py — el "borrador de publicación" en
modo simulación.
"""

from __future__ import annotations

from app.domain.listing_draft import build_draft


def _row(**overrides):
    base = {
        "id": 1,
        "sku": "TEST-001",
        "nombre": "Producto de prueba",
        "precio": 10000,
        "costo": 6000,
        "margenTiendaClp": 4000,
        "margenTiendaPct": 40.0,
        "margenMercadoLibreClp": None,
        "margenMercadoLibrePct": None,
        "clasificacion": "rentable",
        "razon": None,
    }
    base.update(overrides)
    return base


def test_producto_rentable_queda_listo_para_publicar():
    borrador = build_draft(
        _row(), categoria="Herramientas", descripcion="Descripción real",
        imagenes=["http://x.test/a.png"], codigo_barras="123", variant_label=None, marca="Bosch",
    )
    assert borrador["estado"] == "listo_para_publicar"
    assert borrador["advertencias"] == []
    assert borrador["tituloPropuesto"] == "Bosch Producto de prueba"
    assert borrador["contenidoSimulado"] is True


def test_producto_no_rentable_queda_no_recomendado_con_la_razon():
    fila = _row(clasificacion="no_rentable", razon="La utilidad estimada sería negativa (-$510).")
    borrador = build_draft(fila, categoria="Deportes", descripcion=None, imagenes=[], codigo_barras=None, variant_label=None, marca=None)
    assert borrador["estado"] == "no_recomendado"
    assert "La utilidad estimada sería negativa (-$510)." in borrador["advertencias"]


def test_sin_imagen_nunca_dice_listo_para_publicar():
    """13 de septiembre de 2026 — hallazgo de recorrer el producto como
    cliente: la tarjeta decia "Listo para publicar" y justo debajo "Sin
    imagen cargada". Mercado Libre no acepta una publicacion sin foto y el
    backend la rechaza, asi que ese estado era falso."""
    borrador = build_draft(_row(), categoria="Hogar", descripcion="algo", imagenes=[], codigo_barras=None, variant_label=None, marca=None)
    assert borrador["estado"] == "requiere_revision"
    assert any("Mercado Libre no permite publicar sin" in a for a in borrador["advertencias"])


def test_con_imagen_y_rentable_si_queda_listo_para_publicar():
    borrador = build_draft(_row(), categoria="Hogar", descripcion="algo", imagenes=["http://x/a.png"], codigo_barras=None, variant_label=None, marca=None)
    assert borrador["estado"] == "listo_para_publicar"
    assert borrador["advertencias"] == []


def test_sin_imagen_no_tapa_que_el_producto_no_es_rentable():
    """La falta de imagen solo degrada "listo para publicar" — nunca pisa
    "no recomendado", que es la senal mas util para el dueno."""
    fila = _row(clasificacion="no_rentable", razon="La utilidad estimada seria negativa.")
    borrador = build_draft(fila, categoria="Hogar", descripcion="algo", imagenes=[], codigo_barras=None, variant_label=None, marca=None)
    assert borrador["estado"] == "no_recomendado"


def test_categoria_nunca_se_marca_como_oficial_de_mercado_libre():
    borrador = build_draft(_row(), categoria="Lo que sea", descripcion=None, imagenes=[], codigo_barras=None, variant_label=None, marca=None)
    assert borrador["categoriaEsOficialDeMercadoLibre"] is False


def test_margen_bajo_requiere_revision_no_bloquea():
    fila = _row(clasificacion="margen_bajo", razon="Margen estimado (4.2%) por debajo del mínimo pedido (20.0%).")
    borrador = build_draft(fila, categoria="X", descripcion="d", imagenes=["http://x"], codigo_barras=None, variant_label=None, marca=None)
    assert borrador["estado"] == "requiere_revision"
