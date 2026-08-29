"""
Pruebas de app/domain/ml_fees.py — funciones puras, sin red ni DB, igual
que test_profitability.py. Datos de ejemplo tomados de una respuesta REAL
de GET /listing_prices verificada en vivo el 29 de agosto de 2026 (precio
$5.000 CLP, categoría "Cuadernos").
"""

from __future__ import annotations

from app.domain.ml_fees import elegir_comision_principal, parse_listing_fees

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
