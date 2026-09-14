"""
Pruebas de app/domain/ml_fees.py — funciones puras, sin red ni DB, igual
que test_profitability.py. Datos de ejemplo tomados de una respuesta REAL
de GET /listing_prices verificada en vivo el 29 de agosto de 2026 (precio
$5.000 CLP, categoría "Cuadernos").
"""

from __future__ import annotations

from app.domain.ml_fees import (
    ListingFee,
    elegir_comision_principal,
    parse_listing_fees,
    recomendar_tipo_publicacion,
)

RESPUESTA_REAL_ML = [
    {
        "listing_type_id": "gold_pro",
        "listing_type_name": "Premium",
        "sale_fee_amount": 950,
        "sale_fee_details": {"fixed_fee": 0, "gross_amount": 950, "percentage_fee": 19},
    },
    {
        "listing_type_id": "gold_premium",
        "listing_type_name": "Oro Premium",
        "sale_fee_amount": 0,
        "sale_fee_details": {"fixed_fee": 0, "gross_amount": 0, "percentage_fee": 0},
    },
    {
        "listing_type_id": "gold_special",
        "listing_type_name": "Clásica",
        "sale_fee_amount": 750,
        "sale_fee_details": {"fixed_fee": 0, "gross_amount": 750, "percentage_fee": 15},
    },
    {
        "listing_type_id": "silver",
        "listing_type_name": "Plata",
        "sale_fee_amount": 0,
        "sale_fee_details": {"fixed_fee": 0, "gross_amount": 0, "percentage_fee": 0},
    },
]


def test_parse_listing_fees_solo_se_queda_con_clasica_y_premium():
    resultado = parse_listing_fees(RESPUESTA_REAL_ML)

    assert set(resultado.keys()) == {"classic", "premium"}
    assert resultado["classic"].percentage_fee == 15
    assert resultado["classic"].sale_fee_amount == 750
    assert resultado["premium"].percentage_fee == 19
    assert resultado["premium"].sale_fee_amount == 950


def test_parse_listing_fees_ignora_tipos_no_relevantes():
    resultado = parse_listing_fees(RESPUESTA_REAL_ML)
    assert "gold_premium" not in resultado
    assert "silver" not in resultado


def test_parse_listing_fees_falta_un_tipo_no_se_inventa():
    solo_clasica = [item for item in RESPUESTA_REAL_ML if item["listing_type_id"] == "gold_special"]
    resultado = parse_listing_fees(solo_clasica)
    assert set(resultado.keys()) == {"classic"}


def test_parse_listing_fees_lista_vacia_devuelve_dict_vacio():
    assert parse_listing_fees([]) == {}


def test_elegir_comision_principal_respeta_la_preferencia():
    comisiones = parse_listing_fees(RESPUESTA_REAL_ML)

    assert elegir_comision_principal(comisiones, "classic").percentage_fee == 15
    assert elegir_comision_principal(comisiones, "premium").percentage_fee == 19


def test_elegir_comision_principal_sin_preferencia_no_elige_ninguna():
    # None = "comparar ambas" (default) — nunca se elige una por el dueño.
    comisiones = parse_listing_fees(RESPUESTA_REAL_ML)
    assert elegir_comision_principal(comisiones, None) is None
    assert elegir_comision_principal(comisiones, "algo-invalido") is None


# ------------------------------------------------------------------
# Recomendación AUTOMÁTICA de tipo de publicación (14 de septiembre de 2026)
# ------------------------------------------------------------------

# classic 13% / premium 17% — comisiones reales típicas de una categoría.
_COMIS = {
    "classic": ListingFee("Clásica", percentage_fee=13, fixed_fee=0, sale_fee_amount=0),
    "premium": ListingFee("Premium", percentage_fee=17, fixed_fee=0, sale_fee_amount=0),
}


def test_recomienda_clasica_cuando_el_margen_no_aguanta_premium():
    # precio 8000, costo 6000: neto premium = 2000 - 1360 = 640 (8%), lejos del 62% objetivo.
    r = recomendar_tipo_publicacion(8000, 6000, _COMIS, target_margin_pct=62)
    assert r.tipo == "classic"


def test_recomienda_premium_cuando_el_margen_alto_lo_aguanta():
    # precio 15000, costo 1500: neto premium = 13500 - 2550 = 10950 (73%) >= 62%.
    r = recomendar_tipo_publicacion(15000, 1500, _COMIS, target_margin_pct=62)
    assert r.tipo == "premium"


def test_sin_target_configurado_siempre_clasica():
    # Sin objetivo no hay contra qué medir "aguanta Premium" -> Clásica (más utilidad).
    r = recomendar_tipo_publicacion(15000, 1500, _COMIS, target_margin_pct=None)
    assert r.tipo == "classic"


def test_una_sola_comision_disponible_es_la_recomendada():
    solo_classic = {"classic": _COMIS["classic"]}
    r = recomendar_tipo_publicacion(10000, 5000, solo_classic, target_margin_pct=62)
    assert r.tipo == "classic"


def test_sin_datos_devuelve_none():
    assert recomendar_tipo_publicacion(None, 5000, _COMIS) is None
    assert recomendar_tipo_publicacion(10000, None, _COMIS) is None
    assert recomendar_tipo_publicacion(10000, 5000, {}) is None


def test_el_envio_se_descuenta_al_evaluar_si_aguanta_premium():
    # Mismo caso "alto margen" pero con un envío que lo hunde por debajo del objetivo.
    r = recomendar_tipo_publicacion(15000, 1500, _COMIS, shipping_cost=8000, target_margin_pct=62)
    assert r.tipo == "classic"
