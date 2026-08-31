"""Pruebas de app/domain/ml_seller_capabilities.py — función pura, sin red
ni DB (30 de agosto de 2026, soporte User Products)."""

from __future__ import annotations

from app.domain.ml_seller_capabilities import es_user_product_seller


def test_detecta_el_tag_real_de_user_products():
    # Forma real capturada en vivo el 30 de agosto de 2026 contra
    # GET /users/{id} (autenticado, con el token de la cuenta de prueba).
    user_info = {"id": 3644237284, "nickname": "TESTUSER123", "tags": ["normal", "test_user", "user_product_seller"]}
    assert es_user_product_seller(user_info) is True


def test_cuenta_sin_el_tag_es_legacy():
    user_info = {"id": 555, "nickname": "VENDEDOR", "tags": ["normal"]}
    assert es_user_product_seller(user_info) is False


def test_sin_campo_tags_nunca_rompe_y_asume_legacy():
    # GET /users/{id} público (sin token, consultando a otra cuenta) no
    # trae "tags" en absoluto — nunca hay que asumir User Products sin
    # evidencia real.
    user_info = {"id": 555, "nickname": "VENDEDOR"}
    assert es_user_product_seller(user_info) is False


def test_lista_de_tags_vacia_es_legacy():
    user_info = {"id": 555, "nickname": "VENDEDOR", "tags": []}
    assert es_user_product_seller(user_info) is False


def test_tags_none_nunca_rompe():
    user_info = {"id": 555, "nickname": "VENDEDOR", "tags": None}
    assert es_user_product_seller(user_info) is False
