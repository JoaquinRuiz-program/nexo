"""Pruebas de app/domain/ml_error_messages.py — función pura, sin red ni
DB (1 de septiembre de 2026, mejora de mensajes de error de publicación)."""

from __future__ import annotations

from app.domain.ml_error_messages import MENSAJE_GENERICO, mensaje_amigable_error_publicacion


def test_error_de_categoria_da_mensaje_de_categoria():
    body = {"cause": [{"type": "error", "code": "item.category.invalid", "message": "..."}]}
    assert mensaje_amigable_error_publicacion(body) == "La categoría seleccionada no es válida para este producto."


def test_error_de_precio_da_mensaje_de_precio():
    body = {"cause": [{"type": "error", "code": "item.price.invalid", "message": "..."}]}
    assert mensaje_amigable_error_publicacion(body) == "El precio ingresado no es válido para esta publicación."


def test_error_de_atributo_da_mensaje_de_atributos():
    body = {"cause": [{"type": "error", "code": "item.attribute.product_identifier.invalid_format", "message": "..."}]}
    assert mensaje_amigable_error_publicacion(body) == "Faltan algunos datos obligatorios del producto. Revisá los atributos marcados."


def test_caso_real_mixto_warning_y_error_prioriza_el_error():
    """Caso real capturado en vivo (1 de septiembre de 2026): un "warning"
    de MODEL (no bloqueante) mezclado con un "error" real de GTIN -- el
    mensaje debe reflejar el error real, no el warning."""
    body = {
        "cause": [
            {"type": "warning", "code": "item.attribute.missing_catalog_required", "message": "El campo \"Modelo\" es obligatorio."},
            {"type": "error", "code": "item.attribute.product_identifier.invalid_format", "message": "Product Identifier [GTIN] contains values with invalid format."},
        ],
    }
    assert mensaje_amigable_error_publicacion(body) == "Faltan algunos datos obligatorios del producto. Revisá los atributos marcados."


def test_solo_warnings_sin_ningun_error_igual_da_un_mensaje_especifico():
    """Edge case: si por algún motivo Mercado Libre respondió 400 con solo
    warnings (sin type=error), se cae a mirar todos los códigos igual --
    nunca al genérico si hay algo identificable."""
    body = {"cause": [{"type": "warning", "code": "item.price.invalid", "message": "..."}]}
    assert mensaje_amigable_error_publicacion(body) == "El precio ingresado no es válido para esta publicación."


def test_error_desconocido_da_mensaje_generico():
    body = {"cause": [{"type": "error", "code": "item.shipping.invalid_mode", "message": "..."}]}
    assert mensaje_amigable_error_publicacion(body) == MENSAJE_GENERICO


def test_sin_response_body_da_mensaje_generico_nunca_falla():
    assert mensaje_amigable_error_publicacion(None) == MENSAJE_GENERICO


def test_response_body_sin_cause_da_mensaje_generico():
    assert mensaje_amigable_error_publicacion({"message": "Validation error"}) == MENSAJE_GENERICO


def test_cause_con_forma_inesperada_nunca_rompe():
    """Nunca se asume la forma exacta del JSON de Mercado Libre -- si algo
    viene distinto a lo documentado (ej. cause no es una lista), cae al
    genérico en vez de lanzar una excepción."""
    assert mensaje_amigable_error_publicacion({"cause": "no es una lista"}) == MENSAJE_GENERICO
    assert mensaje_amigable_error_publicacion({"cause": [{"sin_code": True}, "ni siquiera un dict"]}) == MENSAJE_GENERICO
