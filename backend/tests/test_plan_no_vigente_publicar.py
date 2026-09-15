"""Un plan que ya no está vigente nunca puede publicar ni reactivar en Mercado
Libre, aunque se llame directo al backend (QA fase 2, 15 de septiembre de
2026): la vista previa lo bloqueaba, pero /confirmar publicaba igual."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
import respx

from app.db.models import MarketplaceListing, Subscription
from app.domain.plans import ensure_default_plans
from tests.test_publicaciones_endpoint import (  # noqa: F401 — fixtures
    ATRIBUTOS_CUADERNOS,
    CONFIGURED_SETTINGS,
    FEES_CUADERNOS,
    NOW,
    _mock_users_me,
    _producto_publicable,
    a_store,
    client,
    cuenta_ml_conectada,
    db_session,
)

BODY = {"category_id": "MLC180937", "condition": "new", "listing_type": "classic", "attributes": {"COLOR": "Azul"}}


def _suscripcion(db_session, tienda, *, status, vence_hace_dias):
    planes = ensure_default_plans(db_session)
    db_session.add(Subscription(
        store=tienda, plan=planes["basico"], status=status, started_at=NOW,
        current_period_end=date.today() - timedelta(days=vence_hace_dias),
    ))
    db_session.commit()


def _mocks_publicacion():
    _mock_users_me()
    respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(return_value=httpx.Response(200, json=ATRIBUTOS_CUADERNOS))
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(return_value=httpx.Response(200, json=FEES_CUADERNOS))
    return respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(201, json={"id": "MLC1", "user_product_id": "MLCU1", "permalink": "https://x"})
    )


@pytest.mark.parametrize(
    "status, vence_hace_dias",
    [
        ("trialing", 10),  # prueba vencida y sin gracia
        ("past_due", 10),  # cobro fallido y sin gracia
        ("canceled", 1),   # canceló y ya terminó el período pagado
        ("expired", 0),    # marcada vencida (p. ej. por el administrador)
    ],
)
@respx.mock
def test_plan_no_vigente_no_publica_aunque_llame_directo_a_confirmar(client, db_session, a_store, cuenta_ml_conectada, monkeypatch, status, vence_hace_dias):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    _suscripcion(db_session, a_store, status=status, vence_hace_dias=vence_hace_dias)
    variant_id = _producto_publicable(db_session, a_store, sku=f"PLAN-{status}", barcode="7891234567895")
    items = _mocks_publicacion()

    for ruta in ("confirmar/preview", "confirmar"):
        res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/{ruta}", json=BODY)
        assert res.status_code == 403, (status, ruta, res.text)
    assert items.call_count == 0
    assert db_session.query(MarketplaceListing).count() == 0


@pytest.mark.parametrize(
    "status, vence_hace_dias",
    [
        ("active", 60),     # paga: current_period_end puede quedar viejo, nunca se bloquea por fecha
        ("canceled", -5),   # canceló pero el período pagado sigue corriendo
        ("trialing", -3),   # prueba vigente
    ],
)
@respx.mock
def test_plan_vigente_si_publica(client, db_session, a_store, cuenta_ml_conectada, monkeypatch, status, vence_hace_dias):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    _suscripcion(db_session, a_store, status=status, vence_hace_dias=vence_hace_dias)
    variant_id = _producto_publicable(db_session, a_store, sku=f"OK-{status}", barcode="7891234567895")
    items = _mocks_publicacion()

    res = client.post(f"/api/publicaciones/{variant_id}/mercadolibre/confirmar", json=BODY)
    assert res.status_code == 200, (status, res.text)
    assert items.call_count == 1
