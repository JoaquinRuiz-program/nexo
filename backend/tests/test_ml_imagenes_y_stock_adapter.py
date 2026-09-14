"""
MercadoLibreAdapter: subida directa de imágenes y stock de publicaciones ya
creadas (14 de septiembre de 2026) — contra respx, nunca la API real.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreConfig


def _adapter() -> MercadoLibreAdapter:
    return MercadoLibreAdapter(MercadoLibreConfig(client_id="x", client_secret="y", redirect_uri="z", max_retries=0, timeout_s=1.0))


@pytest.mark.asyncio
@respx.mock
async def test_upload_picture_manda_multipart_con_el_campo_file():
    ruta = respx.post("https://api.mercadolibre.com/pictures/items/upload").mock(
        return_value=httpx.Response(201, json={"id": "959699-MLM43299127002_092020"})
    )
    adapter = _adapter()
    try:
        data = await adapter.upload_picture("token", b"PNGDATA", "foto.png", "image/png")
    finally:
        await adapter.aclose()

    request = ruta.calls[0].request
    assert data["id"] == "959699-MLM43299127002_092020"
    assert request.headers["Authorization"] == "Bearer token"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="file"; filename="foto.png"' in request.content
    assert b"PNGDATA" in request.content


@pytest.mark.asyncio
@respx.mock
async def test_update_item_available_quantity_solo_manda_el_stock():
    ruta = respx.put("https://api.mercadolibre.com/items/MLC1").mock(return_value=httpx.Response(200, json={"id": "MLC1"}))
    adapter = _adapter()
    try:
        await adapter.update_item_available_quantity("token", "MLC1", 7)
    finally:
        await adapter.aclose()

    assert json.loads(ruta.calls[0].request.content) == {"available_quantity": 7}
