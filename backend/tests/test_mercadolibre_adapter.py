"""
Pruebas de app/adapters/mercadolibre.py — contra un servidor mock (respx),
igual patrón que test_woocommerce_adapter.py. Ninguna de estas pruebas
llama a la API real de Mercado Libre ni necesita credenciales reales.
"""

import base64
import hashlib

import httpx
import pytest
import respx

from app.adapters.mercadolibre import (
    MercadoLibreAdapter,
    MercadoLibreAuthError,
    MercadoLibreConfig,
    MercadoLibreRequestError,
    generate_pkce_pair,
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
    # Sin code_challenge no se manda ningún parámetro de PKCE — Mercado
    # Libre documenta que solo son válidos si la app lo tiene activado.
    assert "code_challenge" not in url


def test_build_authorization_url_con_pkce_agrega_code_challenge_s256():
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    url = adapter.build_authorization_url(state="abc123", code_challenge="el-challenge")

    assert "code_challenge=el-challenge" in url
    assert "code_challenge_method=S256" in url


def test_generate_pkce_pair_el_challenge_es_sha256_base64url_del_verifier():
    code_verifier, code_challenge = generate_pkce_pair()

    assert 43 <= len(code_verifier) <= 128  # rango que exige RFC 7636
    esperado = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    assert code_challenge == esperado
    assert "=" not in code_challenge  # base64url sin padding, como exige PKCE


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_manda_code_verifier_si_se_pasa():
    route = respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "a", "refresh_token": "r", "expires_in": 21600, "user_id": 1}
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    await adapter.exchange_code_for_tokens("un-codigo", code_verifier="el-verifier")
    await adapter.aclose()

    enviado = route.calls[0].request.content.decode()
    assert "code_verifier=el-verifier" in enviado


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_sin_code_verifier_no_lo_manda():
    route = respx.post("https://api.mercadolibre.com/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "a", "refresh_token": "r", "expires_in": 21600, "user_id": 1}
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    await adapter.exchange_code_for_tokens("un-codigo")
    await adapter.aclose()

    enviado = route.calls[0].request.content.decode()
    assert "code_verifier" not in enviado


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


@pytest.mark.asyncio
@respx.mock
async def test_sin_internet_agota_reintentos_y_lanza_request_error():
    # No hay caída al 429/5xx acá — httpx no puede ni conectar (DNS caído,
    # sin red, etc.). Nunca debe devolver un token/pedido falso: agota los
    # reintentos configurados y avisa con un error claro.
    route = respx.get("https://api.mercadolibre.com/users/me")
    route.side_effect = httpx.ConnectError("Connection refused")

    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    with pytest.raises(MercadoLibreRequestError):
        await adapter.get_user_info("token")
    await adapter.aclose()

    assert route.calls.call_count == BASE_CONFIG["max_retries"] + 1


# ------------------------------------------------------------------
# Comisión REAL de Mercado Libre por producto (29 de agosto de 2026,
# segunda ronda del mismo día — "la comisión varía por producto").
# ------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_predict_category_no_manda_authorization_header():
    # Confirmado en vivo el 29 de agosto de 2026: /domain_discovery es
    # público — mandar un token no es necesario, y si algún día se manda
    # por error no debería importar. Acá se confirma que NO lo manda.
    route = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[{"category_id": "MLC180937", "category_name": "Cuadernos"}])
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    resultado = await adapter.predict_category("Cuaderno universitario 100 hojas", "MLC")
    await adapter.aclose()

    assert resultado == {"categoryId": "MLC180937", "categoryName": "Cuadernos"}
    assert "authorization" not in route.calls[0].request.headers


@pytest.mark.asyncio
@respx.mock
async def test_predict_category_sin_resultados_devuelve_none():
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    resultado = await adapter.predict_category("asdf", "MLC")
    await adapter.aclose()

    assert resultado is None


@pytest.mark.asyncio
@respx.mock
async def test_get_listing_fees_manda_precio_categoria_y_bearer_token():
    route = respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(200, json=[{"listing_type_id": "gold_special", "sale_fee_amount": 750}])
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    resultado = await adapter.get_listing_fees("mi-token", "MLC", "MLC180937", 5000)
    await adapter.aclose()

    sent_url = str(route.calls[0].request.url)
    assert "price=5000" in sent_url
    assert "category_id=MLC180937" in sent_url
    assert route.calls[0].request.headers["authorization"] == "Bearer mi-token"
    assert resultado[0]["sale_fee_amount"] == 750


@pytest.mark.asyncio
@respx.mock
async def test_get_listing_fees_sin_permiso_lanza_auth_error():
    # Confirmado en vivo: sin el permiso "Publicación y sincronización"
    # habilitado en la app, Mercado Libre responde 403 aunque el token sea
    # válido — mismo tratamiento que cualquier 401/403 (MercadoLibreAuthError).
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(403, json={"code": "PA_UNAUTHORIZED_RESULT_FROM_POLICIES"})
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    with pytest.raises(MercadoLibreAuthError):
        await adapter.get_listing_fees("mi-token", "MLC", "MLC180937", 5000)
    await adapter.aclose()


# ------------------------------------------------------------------
# Publicación real (29 de agosto de 2026, commit 1/N — solo adapter,
# nada de esto está wireado a ningún endpoint todavía).
# ------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_search_catalog_products_manda_bearer_y_product_identifier():
    # Forma real capturada en vivo el 30 de agosto de 2026 contra
    # GET https://api.mercadolibre.com/products/search?site_id=MLC&q=cuaderno+moleskine
    # (recortada — solo lo necesario para el test).
    route = respx.get(url__regex=r"https://api\.mercadolibre\.com/products/search\?.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "keywords": "cuaderno moleskine", "paging": {"total": 3269, "limit": 10, "offset": 0},
                "results": [{"id": "MLC44481022", "catalog_product_id": "MLC44481022", "name": "Cuaderno Moleskine Clásico Rayado Rojo Escarlata"}],
            },
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    resultado = await adapter.search_catalog_products("mi-token", "MLC", product_identifier="8058647628160")
    await adapter.aclose()

    assert resultado["results"][0]["id"] == "MLC44481022"
    assert route.calls[0].request.headers["authorization"] == "Bearer mi-token"
    assert "product_identifier=8058647628160" in str(route.calls[0].request.url)


@pytest.mark.asyncio
async def test_search_catalog_products_sin_gtin_ni_q_lanza_value_error():
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    with pytest.raises(ValueError):
        await adapter.search_catalog_products("mi-token", "MLC")
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_catalog_product_devuelve_buy_box_winner_real():
    # Forma real capturada en vivo el 30 de agosto de 2026 contra
    # GET https://api.mercadolibre.com/products/MLC44481022 — en este caso
    # real puntual buy_box_winner vino null (sin competencia activa en ese
    # momento), forma documentada oficialmente para el caso "con ganador".
    route = respx.get("https://api.mercadolibre.com/products/MLC44481022").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MLC44481022", "name": "Cuaderno Moleskine Clásico Rayado Rojo Escarlata",
                "buy_box_winner": {"item_id": "MLC123", "price": 22990, "currency_id": "CLP", "condition": "new", "shipping": {"free_shipping": True, "logistic_type": "fulfillment"}, "seller": {"reputation_level_id": "5_green"}},
                "buy_box_winner_price_range": {"min": {"price": 19990}, "max": {"price": 25990}},
            },
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    detalle = await adapter.get_catalog_product("mi-token", "MLC44481022")
    await adapter.aclose()

    assert detalle["buy_box_winner"]["price"] == 22990
    assert route.calls[0].request.headers["authorization"] == "Bearer mi-token"


@pytest.mark.asyncio
@respx.mock
async def test_get_category_devuelve_max_title_length_real_sin_authorization_header():
    # 30 de agosto de 2026, soporte User Products: subconjunto REAL
    # capturado en vivo contra GET https://api.mercadolibre.com/categories/MLC180937
    # (categoría "Cuadernos") — mismo criterio público que
    # get_category_attributes/predict_category, sin token.
    route = respx.get("https://api.mercadolibre.com/categories/MLC180937").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MLC180937", "name": "Cuadernos",
                "settings": {"max_title_length": 60, "max_sub_title_length": 70},
            },
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    categoria = await adapter.get_category("MLC180937")
    await adapter.aclose()

    assert categoria["settings"]["max_title_length"] == 60
    assert "authorization" not in route.calls[0].request.headers


@pytest.mark.asyncio
@respx.mock
async def test_get_category_attributes_no_manda_authorization_header():
    # Confirmado en vivo el 29 de agosto de 2026 con
    # GET https://api.mercadolibre.com/categories/MLC180937/attributes:
    # es público, igual que /domain_discovery.
    route = respx.get("https://api.mercadolibre.com/categories/MLC180937/attributes").mock(
        return_value=httpx.Response(200, json=[{"id": "BRAND", "name": "Marca", "tags": {"required": True}, "value_type": "string"}])
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    atributos = await adapter.get_category_attributes("MLC180937")
    await adapter.aclose()

    assert atributos[0]["id"] == "BRAND"
    assert "authorization" not in route.calls[0].request.headers


@pytest.mark.asyncio
@respx.mock
async def test_create_item_manda_bearer_token_y_json_body():
    route = respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(
            201,
            json={"id": "MLC123456789", "user_product_id": "MLCU1234567", "site_id": "MLC", "title": "Cuaderno universitario"},
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    payload = {
        "title": "Cuaderno universitario",
        "category_id": "MLC180937",
        "price": 5000,
        "currency_id": "CLP",
        "available_quantity": 3,
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_special",
        "pictures": [{"source": "https://ejemplo.cl/foto.jpg"}],
        "attributes": [
            {"id": "BRAND", "value_name": "Torre"},
            {"id": "ITEM_CONDITION", "value_id": "2230284", "value_name": "Nuevo"},
        ],
    }
    resultado = await adapter.create_item("mi-token", payload)
    await adapter.aclose()

    assert resultado["id"] == "MLC123456789"
    assert resultado["user_product_id"] == "MLCU1234567"
    enviado = route.calls[0].request
    assert enviado.headers["authorization"] == "Bearer mi-token"
    import json as _json

    cuerpo_enviado = _json.loads(enviado.content)
    assert cuerpo_enviado == payload
    # Nunca un campo "condition" a nivel raíz — ver domain/listing_validation.py.
    assert "condition" not in cuerpo_enviado


@pytest.mark.asyncio
@respx.mock
async def test_create_item_con_categoria_invalida_lanza_request_error_no_auth_error():
    # Un 400 de validación de Mercado Libre (categoría cerrada, atributo
    # inválido, etc.) es un MercadoLibreRequestError, nunca AuthError — no
    # tiene nada que ver con el token, y nunca se debe reintentar solo
    # (ver RETRYABLE_STATUS: 400 no está ahí a propósito).
    route = respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(
            400,
            json={
                "message": "attribute value_name invalid",
                "error": "bad_request",
                "cause": [
                    {"code": "item.attributes.invalid_type", "message": "Invalid attribute type", "references": ["item.attributes.BRAND"]}
                ],
            },
        )
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    with pytest.raises(MercadoLibreRequestError):
        await adapter.create_item("mi-token", {"title": "x"})
    await adapter.aclose()
    assert route.calls.call_count == 1  # nunca reintenta un 400


@pytest.mark.asyncio
@respx.mock
async def test_create_item_sin_permiso_lanza_auth_error():
    respx.post("https://api.mercadolibre.com/items").mock(
        return_value=httpx.Response(403, json={"code": "PA_UNAUTHORIZED_RESULT_FROM_POLICIES"})
    )
    adapter = MercadoLibreAdapter(MercadoLibreConfig(**BASE_CONFIG))
    with pytest.raises(MercadoLibreAuthError):
        await adapter.create_item("mi-token", {"title": "x"})
    await adapter.aclose()
