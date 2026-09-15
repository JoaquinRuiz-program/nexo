"""
Importante 18 de REVISION_EXPERIENCIA.md (15 de septiembre de 2026): sin
Mercado Libre conectado igual se predice la categoría de cada producto con el
endpoint público. Mercado Libre mockeado con respx.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx

from app.config import Settings
from app.db.models import MercadoLibreCategoryFee, Product
from app.services.ml_comisiones import _solo_predecir_categorias as predecir_categorias  # la real, no la del conftest
from tests.test_catalogo_endpoints import a_store, client, db_session  # noqa: F401 — fixtures

NOW = datetime(2026, 9, 15, 12, 0, 0)
SETTINGS = Settings(mercadolibre_client_id="", mercadolibre_client_secret="", mercadolibre_redirect_uri="", token_encryption_key="")


def _producto(db_session, tienda, nombre, categoria=None):
    producto = Product(store=tienda, name=nombre, product_type="simple", ml_category_id=categoria, created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.commit()
    return producto


@pytest.mark.asyncio
@respx.mock
async def test_predice_la_categoria_sin_cuenta_conectada_y_no_consulta_comisiones(db_session, a_store):
    lampara = _producto(db_session, a_store, "Lámpara de noche luna 3D")
    ya_tenia = _producto(db_session, a_store, "Taza cerámica", categoria="MLC1234")
    ruta = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC5555", "category_name": "Lámparas"}])
    )
    comisiones = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*")

    resultado = await predecir_categorias(db_session, a_store.id, SETTINGS)

    assert resultado == {"productosConCategoriaNueva": 1, "productosSinCategoriaDetectada": []}
    assert ruta.call_count == 1  # el que ya tenía categoría no se vuelve a pedir
    assert comisiones.call_count == 0
    db_session.refresh(lampara)
    db_session.refresh(ya_tenia)
    assert (lampara.ml_category_id, lampara.ml_category_name) == ("MLC5555", "Lámparas")
    assert ya_tenia.ml_category_id == "MLC1234"
    assert db_session.query(MercadoLibreCategoryFee).count() == 0


@pytest.mark.asyncio
@respx.mock
async def test_si_mercado_libre_no_responde_no_rompe_nada(db_session, a_store):
    _producto(db_session, a_store, "Botella térmica")
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(return_value=httpx.Response(503))

    resultado = await predecir_categorias(db_session, a_store.id, SETTINGS)

    assert resultado == {"productosConCategoriaNueva": 0, "productosSinCategoriaDetectada": ["Botella térmica"]}
