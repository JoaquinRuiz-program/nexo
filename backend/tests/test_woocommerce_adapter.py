import pytest
import respx
import httpx

from app.adapters.woocommerce import (
    WooCommerceAdapter,
    WooCommerceAuthError,
    WooCommerceConfig,
    WooCommerceRequestError,
)

BASE_CONFIG = dict(
    base_url="http://libreria-central-test.local",
    consumer_key="ck_test",
    consumer_secret="cs_test",
    max_retries=2,
    timeout_s=1.0,
)


@pytest.mark.asyncio
@respx.mock
async def test_get_product_usa_query_string_en_http():
    route = respx.get("http://libreria-central-test.local/wp-json/wc/v3/products/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Cuaderno Torre", "sku": "LIB-0001"})
    )
    adapter = WooCommerceAdapter(WooCommerceConfig(**BASE_CONFIG))
    product = await adapter.get_product(42)
    await adapter.aclose()

    assert product["id"] == 42
    assert product["name"] == "Cuaderno Torre"
    sent_url = str(route.calls[0].request.url)
    assert "consumer_key=ck_test" in sent_url
    assert "consumer_secret=cs_test" in sent_url


@pytest.mark.asyncio
@respx.mock
async def test_https_usa_basic_auth_en_vez_de_query_params():
    route = respx.get("https://libreria-real.cl/wp-json/wc/v3/products/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "x"})
    )
    cfg = {**BASE_CONFIG, "base_url": "https://libreria-real.cl"}
    adapter = WooCommerceAdapter(WooCommerceConfig(**cfg))
    await adapter.get_product(1)
    await adapter.aclose()

    sent = route.calls[0].request
    assert "consumer_key" not in str(sent.url)
    assert sent.headers["authorization"].startswith("Basic ")


@pytest.mark.asyncio
@respx.mock
async def test_401_lanza_woocommerce_auth_error_sin_reintentar():
    route = respx.get("http://libreria-central-test.local/wp-json/wc/v3/products/1").mock(
        return_value=httpx.Response(401, json={"code": "woocommerce_rest_cannot_view", "message": "no autorizado"})
    )
    adapter = WooCommerceAdapter(WooCommerceConfig(**BASE_CONFIG))
    with pytest.raises(WooCommerceAuthError) as exc_info:
        await adapter.get_product(1)
    await adapter.aclose()

    assert route.calls.call_count == 1, "no debería reintentar un error de autenticación"
    assert "woocommerce_rest_cannot_view" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_catalogo_paginado_recorre_todas_las_paginas():
    pages = {
        1: [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        2: [{"id": 3, "name": "C"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages[page], headers={"X-WP-Total": "3", "X-WP-TotalPages": "2"})

    respx.get("http://libreria-central-test.local/wp-json/wc/v3/products").mock(side_effect=handler)

    adapter = WooCommerceAdapter(WooCommerceConfig(**BASE_CONFIG))
    progress_calls = []
    all_products = await adapter.get_all_products(lambda page, total: progress_calls.append((page, total)))
    await adapter.aclose()

    assert [p["id"] for p in all_products] == [1, 2, 3]
    assert progress_calls == [(1, 2), (2, 2)]


@pytest.mark.asyncio
@respx.mock
async def test_reintentos_ante_429_luego_funciona():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(429 if attempts["count"] == 1 else 503, json={})
        return httpx.Response(200, json={"id": 1, "name": "ok tras reintentos"})

    respx.get("http://libreria-central-test.local/wp-json/wc/v3/products/1").mock(side_effect=handler)

    adapter = WooCommerceAdapter(WooCommerceConfig(**{**BASE_CONFIG, "max_retries": 3}))
    product = await adapter.get_product(1)
    await adapter.aclose()

    assert product["name"] == "ok tras reintentos"
    assert attempts["count"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_5xx_persistente_agota_reintentos_y_lanza_request_error():
    respx.get("http://libreria-central-test.local/wp-json/wc/v3/products/1").mock(
        return_value=httpx.Response(500, json={})
    )
    adapter = WooCommerceAdapter(WooCommerceConfig(**{**BASE_CONFIG, "max_retries": 2}))
    with pytest.raises(WooCommerceRequestError):
        await adapter.get_product(1)
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_error_de_conexion_se_envuelve_en_woocommerce_request_error():
    """
    Regresión: un error de conexión (host caído, DNS, conexión rechazada) no
    debe escapar como httpx.ConnectError crudo — antes de este fix, agotar
    los reintentos volvía a lanzar el error original de httpx en vez de
    WooCommerceRequestError, y el endpoint no sabía atraparlo (terminaba en
    un 500 con traceback en vez del 502 ya preparado para esto).
    """
    respx.get("http://libreria-central-test.local/wp-json/wc/v3/products/1").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    adapter = WooCommerceAdapter(WooCommerceConfig(**{**BASE_CONFIG, "max_retries": 1}))
    with pytest.raises(WooCommerceRequestError):
        await adapter.get_product(1)
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_all_variations_pagina_variaciones_de_producto_variable():
    pages = {
        1: [{"id": 101, "sku": "LIB-ROJO", "attributes": [{"name": "Color", "option": "Rojo"}]}],
        2: [{"id": 102, "sku": "LIB-AZUL", "attributes": [{"name": "Color", "option": "Azul"}]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages[page], headers={"X-WP-Total": "2", "X-WP-TotalPages": "2"})

    route = respx.get("http://libreria-central-test.local/wp-json/wc/v3/products/3335/variations").mock(
        side_effect=handler
    )

    adapter = WooCommerceAdapter(WooCommerceConfig(**BASE_CONFIG))
    variations = await adapter.get_all_variations(3335)
    await adapter.aclose()

    assert [v["sku"] for v in variations] == ["LIB-ROJO", "LIB-AZUL"]
    assert route.calls.call_count == 2
