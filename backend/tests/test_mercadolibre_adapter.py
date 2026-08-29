"""
Pruebas de app/adapters/mercadolibre.py — contra un servidor mock (respx),
igual patrón que test_woocommerce_adapter.py. Ninguna de estas pruebas
llama a la API real de Mercado Libre ni necesita credenciales reales.
"""

import httpx
import pytest
import respx

from app.adapters.mercadolibre import (
    MercadoLibreAdapter,
    MercadoLibreAuthError,
    MercadoLibreConfig,
    MercadoLibreRequestError,
)

BASE_CONFIG = dict(
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="http://localhost:8000/api/mercadolibre/callback",
    auth_domain="auth.mercadolibre.cl",
    max_retries=2,
    timeout_s=1.0,
)


def test_config_is_configured_solo_si_estan_los_tres_datos():
    assert MercadoLibreConfig(**BASE_CONFIG).is_configured() is True
    assert MercadoLibreConfig(client_id="", client_secret="x", redirect_uri="x").is_configured() is False
    assert MercadoLibreConfig(client_id="x", client_secret="", redirect_uri="x").is_configured() is False


def test_build_authorization_url_usa_el_dominio_del_pais_de_la_cuenta():
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    url = adapter.build_authorization_url(state="abc123")

    assert url.startswith("https://auth.mercadolibre.cl/authorization?")
    assert "client_id=test-client-id" in url
    assert "state=abc123" in url
    assert "redirect_uri=" in url


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_devuelve_los_tokens_reales():
    respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "APP_USR-real-access-token",
                "token_type": "bearer",
                "expires_in": 21600,
                "refresh_token": "TG-real-refresh-token",
                "user_id": 123456789,
            },
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    tokens = await adapter.exchange_code_for_tokens("un-codigo-real")
    await adapter.aclose()

    assert tokens.access_token == "APP_USR-real-access-token"
    assert tokens.refresh_token == "TG-real-refresh-token"
    assert tokens.user_id == 123456789
    assert tokens.expires_in == 21600


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_envia_client_secret_y_code_correctos():
    route = respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "a", "refresh_token": "r", "expires_in": 21600, "user_id": 1}
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    await adapter.exchange_code_for_tokens("codigo-xyz")
    await adapter.aclose()

    enviado = route.calls[0].request.content.decode()
    assert "client_secret=test-client-secret" in enviado
    assert "code=codigo-xyz" in enviado
    assert "grant_type=authorization_code" in enviado


@pytest.mark.asyncio
@respx.mock
async def test_refresh_tokens_usa_grant_type_refresh_token():
    route = respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "nuevo", "refresh_token": "nuevo-refresh", "expires_in": 21600, "user_id": 1}
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    tokens = await adapter.refresh_tokens("TG-viejo-refresh-token")
    await adapter.aclose()

    assert tokens.access_token == "nuevo"
    enviado = route.calls[0].request.content.decode()
    assert "grant_type=refresh_token" in enviado
    assert "refresh_token=TG-viejo-refresh-token" in enviado


@pytest.mark.asyncio
@respx.mock
async def test_credenciales_invalidas_lanzan_auth_error_sin_reintentar():
    route = respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "message": "código inválido o expirado"})
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    # 400 no es 401/403 -> no es un MercadoLibreAuthError, es un RequestError
    # normal (ML devuelve 400 para código de autorización inválido/expirado).
    with pytest.raises(MercadoLibreRequestError):
        await adapter.exchange_code_for_tokens("codigo-vencido")
    await adapter.aclose()
    assert route.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_token_expirado_lanza_auth_error_sin_reintentar():
    route = respx.get("https://api.mercadolibre.com/users/me").mock(
        return_value=httpx.Response(401, json={"message": "invalid_token", "error": "not_found"})
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    with pytest.raises(MercadoLibreAuthError):
        await adapter.get_user_info("token-vencido")
    await adapter.aclose()
    assert route.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_envia_el_access_token_como_bearer():
    route = respx.get("https://api.mercadolibre.com/users/me").mock(
        return_value=httpx.Response(200, json={"id": 123456789, "nickname": "LIBRERIA_TEST"})
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    info = await adapter.get_user_info("mi-access-token")
    await adapter.aclose()

    assert info["id"] == 123456789
    assert route.calls[0].request.headers["authorization"] == "Bearer mi-access-token"


@pytest.mark.asyncio
@respx.mock
async def test_search_orders_pagina_con_seller_offset_y_limit():
    route = respx.get(url__regex=r"https://api\.mercadolibre\.com/orders/search.*").mock(
        return_value=httpx.Response(200, json={"results": [], "paging": {"total": 0, "offset": 0, "limit": 50}})
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    await adapter.search_orders("mi-token", seller_id="123456789", offset=0, limit=50)
    await adapter.aclose()

    sent_url = str(route.calls[0].request.url)
    assert "seller=123456789" in sent_url
    assert "offset=0" in sent_url
    assert "limit=50" in sent_url


@pytest.mark.asyncio
@respx.mock
async def test_errores_5xx_se_reintentan_y_terminan_bien():
    route = respx.get("https://api.mercadolibre.com/users/me")
    route.side_effect = [
        httpx.Response(503, json={"message": "service unavailable"}),
        httpx.Response(200, json={"id": 1, "nickname": "OK"}),
    ]
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    info = await adapter.get_user_info("token")
    await adapter.aclose()

    assert info["nickname"] == "OK"
    assert route.calls.call_count == 2
