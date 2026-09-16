"""Importación de ventas de Mercado Libre: se piden TODAS las páginas de
pedidos, no solo la primera (revisión del sistema, 16 de septiembre de 2026).
Antes, un vendedor con más de 50 pedidos nuevos entre dos importaciones perdía
el resto en silencio."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import respx

from app.db.models import Order
from tests.test_mercadolibre_endpoints import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    a_store,
    client,
    cuenta_conectada,
    db_session,
)

TOTAL_PEDIDOS = 60
POR_PAGINA = 50


def _pedido(n: int) -> dict:
    return {
        "id": 900000 + n,
        "date_created": "2026-09-10T10:00:00.000-04:00",
        "status": "paid",
        "total_amount": 1000 + n,
        "order_items": [{
            "item": {"id": f"MLC{n}", "seller_sku": f"SKU-{n}", "title": f"Producto {n}"},
            "quantity": 1, "unit_price": 1000 + n, "sale_fee": 100,
        }],
    }


def _responder_paginado(request: httpx.Request) -> httpx.Response:
    params = parse_qs(urlparse(str(request.url)).query)
    offset = int(params.get("offset", ["0"])[0])
    resultados = [_pedido(n) for n in range(offset, min(offset + POR_PAGINA, TOTAL_PEDIDOS))]
    return httpx.Response(200, json={"results": resultados, "paging": {"total": TOTAL_PEDIDOS, "offset": offset, "limit": POR_PAGINA}})


@respx.mock
def test_importar_ventas_trae_todas_las_paginas(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(side_effect=_responder_paginado)

    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.status_code == 200, res.text
    assert len(res.json()["ordenesNuevas"]) == TOTAL_PEDIDOS
    assert db_session.query(Order).filter_by(store_id=a_store.id).count() == TOTAL_PEDIDOS

    llamadas = [str(c.request.url) for c in respx.calls if "/orders/search" in str(c.request.url)]
    assert len(llamadas) == 2  # 50 + 10, y corta al llegar al total
    # Los más nuevos primero: con un historial largo, cada corrida trae lo último.
    assert all("sort=date_desc" in url for url in llamadas)


@respx.mock
def test_una_segunda_importacion_no_duplica_los_pedidos_ya_importados(client, db_session, a_store, cuenta_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(side_effect=_responder_paginado)

    client.post("/api/mercadolibre/importar-ventas")
    res = client.post("/api/mercadolibre/importar-ventas")

    assert res.json()["ordenesNuevas"] == []
    assert len(res.json()["ordenesYaExistian"]) == TOTAL_PEDIDOS
    assert db_session.query(Order).filter_by(store_id=a_store.id).count() == TOTAL_PEDIDOS
