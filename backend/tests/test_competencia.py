"""Pruebas de app/domain/competencia.py — función pura, sin red ni DB.
Datos con la misma forma REAL que devuelve GET /products/{id}, capturada
en vivo el 30 de agosto de 2026 (ver PUBLICACION_MERCADOLIBRE.md / FASE 4)."""

from __future__ import annotations

from app.domain.competencia import analizar_competencia

PRODUCTO_CON_GANADOR = {
    "id": "MLC44481022",
    "name": "Cuaderno Moleskine Clásico Rayado Rojo Escarlata",
    "buy_box_winner": {
        "item_id": "MLC123456789", "price": 22990, "currency_id": "CLP", "condition": "new",
        "shipping": {"free_shipping": True, "logistic_type": "fulfillment"},
        "seller": {"reputation_level_id": "5_green"},
    },
    "buy_box_winner_price_range": {"min": {"price": 19990}, "max": {"price": 25990}},
}

PRODUCTO_SIN_GANADOR = {
    "id": "MLC44481022", "name": "Producto sin competencia activa",
    "buy_box_winner": None, "buy_box_winner_price_range": None,
}


def test_sin_ganador_hay_competencia_es_false():
    resultado = analizar_competencia(PRODUCTO_SIN_GANADOR)
    assert resultado.hay_competencia is False
    assert resultado.precio_ganador is None
    assert resultado.posicion_precio_propio is None


def test_con_ganador_extrae_los_datos_reales():
    resultado = analizar_competencia(PRODUCTO_CON_GANADOR)
    assert resultado.hay_competencia is True
    assert resultado.precio_ganador == 22990
    assert resultado.moneda_ganador == "CLP"
    assert resultado.condicion_ganador == "new"
    assert resultado.envio_gratis_ganador is True
    assert resultado.logistica_ganador == "fulfillment"
    assert resultado.reputacion_ganador == "5_green"
    assert resultado.rango_precio_minimo == 19990
    assert resultado.rango_precio_maximo == 25990


def test_posicion_por_debajo_del_rango():
    resultado = analizar_competencia(PRODUCTO_CON_GANADOR, precio_propio=15000)
    assert resultado.posicion_precio_propio == "por_debajo"


def test_posicion_en_rango():
    resultado = analizar_competencia(PRODUCTO_CON_GANADOR, precio_propio=22000)
    assert resultado.posicion_precio_propio == "en_rango"


def test_posicion_por_encima_del_rango():
    resultado = analizar_competencia(PRODUCTO_CON_GANADOR, precio_propio=30000)
    assert resultado.posicion_precio_propio == "por_encima"


def test_sin_precio_propio_no_calcula_posicion():
    resultado = analizar_competencia(PRODUCTO_CON_GANADOR, precio_propio=None)
    assert resultado.posicion_precio_propio is None


def test_sin_rango_real_no_calcula_posicion_aunque_haya_ganador():
    """Nunca se inventa un rango — si Mercado Libre no lo trajo, no hay
    posición que calcular."""
    producto = {**PRODUCTO_CON_GANADOR, "buy_box_winner_price_range": None}
    resultado = analizar_competencia(producto, precio_propio=22000)
    assert resultado.posicion_precio_propio is None
