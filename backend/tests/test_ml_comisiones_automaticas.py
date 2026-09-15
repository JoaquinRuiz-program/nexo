"""
"Que siempre sean comisiones reales" (14 de septiembre de 2026): al
confirmar una importación de catálogo, la comisión real de Mercado Libre se
consulta sola en segundo plano (services/ml_comisiones.py). Mercado Libre
mockeado con respx.
"""

from __future__ import annotations

import io
import json

import httpx
import respx

from app.db.models import MercadoLibreCategoryFee, Product
from tests.test_mercadolibre_endpoints import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    a_store,
    client,
    cuenta_conectada,
    db_session,
)

CSV = "SKU,Nombre,Precio,Costo\nLIB-900,Cuaderno universitario,5000,2000\n"
MAPEO = {"sku": "SKU", "nombre": "Nombre", "precio": "Precio", "costo": "Costo"}
FEES = [
    {"listing_type_id": "gold_special", "listing_type_name": "Clásica", "sale_fee_amount": 750, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 15}},
    {"listing_type_id": "gold_pro", "listing_type_name": "Premium", "sale_fee_amount": 950, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 19}},
]


def _importar(client):
    return client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("catalogo.csv", io.BytesIO(CSV.encode("utf-8")), "text/csv")},
        data={"mapeo": json.dumps(MAPEO)},
    )


@respx.mock
def test_importar_catalogo_con_ml_conectado_guarda_la_comision_real(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.catalogo.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES))

    res = _importar(client)

    assert res.status_code == 200
    assert res.json()["creados"] == 1
    db_session.expire_all()
    producto = db_session.query(Product).filter_by(internal_sku="LIB-900").one()
    assert producto.ml_category_id == "MLC180937"
    filas = db_session.query(MercadoLibreCategoryFee).filter_by(store_id=a_store.id, category_id="MLC180937", price=5000).all()
    assert {f.listing_type_id: float(f.percentage_fee) for f in filas} == {"gold_special": 15.0, "gold_pro": 19.0}


@respx.mock
def test_importar_catalogo_no_falla_si_ml_rechaza_las_comisiones(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.catalogo.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(403, json={"message": "forbidden"})
    )

    res = _importar(client)

    assert res.status_code == 200
    assert res.json()["creados"] == 1
    assert db_session.query(MercadoLibreCategoryFee).count() == 0


def test_importar_catalogo_sin_ml_conectado_no_consulta_comisiones(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.catalogo.get_settings", lambda: CONFIGURED_SETTINGS)
    with respx.mock(assert_all_called=False) as ml:
        res = _importar(client)
    assert res.status_code == 200
    assert ml.calls.call_count == 0
