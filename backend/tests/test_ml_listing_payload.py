"""Pruebas de app/domain/ml_listing_payload.py — función pura, sin red ni
DB (30 de agosto de 2026, soporte User Products)."""

from __future__ import annotations

import pytest

from app.domain.ml_listing_payload import construir_payload_publicacion

_KWARGS_BASE = dict(
    titulo="Torre Cuaderno universitario",
    category_id="MLC180937",
    price=5000.0,
    currency_id="CLP",
    available_quantity=5,
    listing_type_id="gold_special",
    pictures=[{"source": "http://cdn.test/img.png"}],
    attributes=[{"id": "BRAND", "value_name": "Torre"}],
)


def test_legacy_manda_title_nunca_family_name():
    resultado = construir_payload_publicacion(**_KWARGS_BASE, es_user_product_seller=False)
    assert resultado.payload["title"] == "Torre Cuaderno universitario"
    assert "family_name" not in resultado.payload
    assert resultado.titulo_local == "Torre Cuaderno universitario"


def test_user_product_seller_manda_family_name_nunca_title():
    resultado = construir_payload_publicacion(
        **_KWARGS_BASE, es_user_product_seller=True, family_name="Torre Cuaderno universitario"
    )
    assert resultado.payload["family_name"] == "Torre Cuaderno universitario"
    assert "title" not in resultado.payload
    # El título local (para guardar en Nexo) se sigue calculando igual,
    # aunque no viaje en el payload real a Mercado Libre.
    assert resultado.titulo_local == "Torre Cuaderno universitario"


def test_user_product_seller_sin_family_name_es_un_error_de_programacion():
    """quien llama (publicaciones.py) tiene que resolver family_name ANTES
    de llegar acá (default o el que mandó el dueño) — esta función nunca
    inventa uno ni lo deja vacío en el payload real."""
    with pytest.raises(ValueError):
        construir_payload_publicacion(**_KWARGS_BASE, es_user_product_seller=True, family_name=None)


def test_resto_del_payload_es_identico_en_ambas_ramas():
    legacy = construir_payload_publicacion(**_KWARGS_BASE, es_user_product_seller=False).payload
    up = construir_payload_publicacion(**_KWARGS_BASE, es_user_product_seller=True, family_name="X").payload

    campos_comunes = {"category_id", "price", "currency_id", "available_quantity", "buying_mode", "listing_type_id", "pictures", "attributes", "shipping"}
    for campo in campos_comunes:
        assert legacy[campo] == up[campo]
    assert legacy["shipping"] == {"mode": "not_specified"}
