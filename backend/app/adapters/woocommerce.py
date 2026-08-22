"""
WooCommerceAdapter — capa de solo lectura sobre la API REST de
administración de WooCommerce (`/wp-json/wc/v3/`).

Puerto directo de scripts/woocommerce-audit/src/woocommerceAdapter.ts (ya
probado con 24 tests y verificado end-to-end contra un servidor mock) — este
es el "motor" que pidió el dueño del proyecto que fuera el núcleo de la app
real. Se mantiene el mismo comportamiento exacto:

- Auth por query string en http://, por cabecera Authorization Basic en
  https:// (salvo que se fuerce con WOOCOMMERCE_AUTH_METHOD).
- Reintentos con backoff exponencial ante 429/5xx; SIN reintentar 401/403
  (una clave inválida no se arregla reintentando).
- El cuerpo de la respuesta en 401/403 se incluye en el mensaje de error
  (reveló en su momento que el problema real era `woocommerce_rest_cannot_view`,
  no una clave inválida).
- getAllVariations: trae SKU/precio/stock reales por variante de color de un
  producto type:"variable" — la Store API pública no los expone, por eso
  esta app necesita la clave de administración wc/v3.

DELIBERADAMENTE sin ninguna operación de escritura (no hay create/update/
delete de productos ni de stock) — mismo alcance que el script de auditoría,
todavía no aprobado para escribir en WooCommerce.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class WooCommerceAuthError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class WooCommerceRequestError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, attempts: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.attempts = attempts


@dataclass
class WooCommerceConfig:
    base_url: str
    consumer_key: str
    consumer_secret: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    # "basic" | "query" | None (None = automático según el esquema de base_url)
    auth_method: Optional[str] = None


@dataclass
class PagedResult:
    items: list[dict[str, Any]]
    total: int
    total_pages: int
    page: int


def backoff_delay_s(attempt: int) -> float:
    base = min(8.0, 0.3 * (2**attempt))
    jitter = random.random() * 0.2
    return base + jitter


def _resolve_auth_method(cfg: WooCommerceConfig) -> str:
    if cfg.auth_method:
        return cfg.auth_method
    return "basic" if cfg.base_url.startswith("https://") else "query"


def _build_url(cfg: WooCommerceConfig, path: str, params: Optional[dict[str, Any]] = None) -> str:
    base = cfg.base_url.rstrip("/")
    query: dict[str, Any] = {k: v for k, v in (params or {}).items() if v is not None}
    if _resolve_auth_method(cfg) == "query":
        query["consumer_key"] = cfg.consumer_key
        query["consumer_secret"] = cfg.consumer_secret
    url = f"{base}/wp-json/wc/v3{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def _build_auth(cfg: WooCommerceConfig) -> Optional[httpx.Auth]:
    if _resolve_auth_method(cfg) == "basic":
        return httpx.BasicAuth(cfg.consumer_key, cfg.consumer_secret)
    return None


async def _request_with_retry(
    client: httpx.AsyncClient,
    cfg: WooCommerceConfig,
    url: str,
) -> httpx.Response:
    last_error: Optional[Exception] = None
    for attempt in range(cfg.max_retries + 1):
        try:
            response = await client.get(
                url,
                auth=_build_auth(cfg),
                headers={"Accept": "application/json"},
                timeout=cfg.timeout_s,
            )
        except httpx.TimeoutException as err:
            last_error = err
            if attempt < cfg.max_retries:
                await asyncio.sleep(backoff_delay_s(attempt))
                continue
            raise WooCommerceRequestError(
                f"Timeout después de {cfg.timeout_s}s contactando {url} ({attempt + 1} intentos)",
                attempts=attempt + 1,
            ) from err
        except httpx.HTTPError as err:
            last_error = err
            if attempt < cfg.max_retries:
                await asyncio.sleep(backoff_delay_s(attempt))
                continue
            # Antes de este fix, esto hacía "raise" (re-lanzaba el error crudo
            # de httpx, ej. ConnectError) en vez de envolverlo en
            # WooCommerceRequestError. El endpoint /api/productos/reporte solo
            # atrapa WooCommerceAuthError/WooCommerceRequestError, así que un
            # WooCommerce real caído o inalcanzable terminaba en un 500 con
            # traceback crudo en vez del 502 claro que ya existe para estos
            # casos. Detectado al probar el frontend contra un backend con la
            # URL de WooCommerce mal configurada.
            raise WooCommerceRequestError(
                f"No se pudo conectar con {url}: {err}",
                attempts=attempt + 1,
            ) from err

        if response.status_code in (401, 403):
            # El cuerpo trae el código real de WooCommerce (ej.
            # "woocommerce_rest_cannot_view") — no son credenciales inválidas
            # en todos los casos, a veces es un problema de capacidades del
            # usuario de WordPress. Se muestra tal cual (respuesta pública
            # del servidor, no algo que nosotros enviamos).
            body_detail = ""
            try:
                body_text = response.text
                if body_text:
                    body_detail = f" Respuesta del servidor: {body_text[:500]}"
            except Exception:
                pass
            raise WooCommerceAuthError(
                f"Autenticación rechazada (HTTP {response.status_code}).{body_detail}",
                response.status_code,
            )

        if response.status_code in RETRYABLE_STATUS and attempt < cfg.max_retries:
            await asyncio.sleep(backoff_delay_s(attempt))
            continue

        if response.status_code >= 400:
            raise WooCommerceRequestError(
                f"WooCommerce respondió HTTP {response.status_code} en {url}",
                status=response.status_code,
                attempts=attempt + 1,
            )

        return response

    raise WooCommerceRequestError(str(last_error) if last_error else "Error desconocido")


class WooCommerceAdapter:
    def __init__(self, config: WooCommerceConfig, client: Optional[httpx.AsyncClient] = None):
        self._cfg = config
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_product(self, product_id: int) -> dict[str, Any]:
        url = _build_url(self._cfg, f"/products/{product_id}")
        res = await _request_with_retry(self._client, self._cfg, url)
        return res.json()

    async def get_products_page(self, page: int, per_page: int = 100) -> PagedResult:
        url = _build_url(self._cfg, "/products", {"page": page, "per_page": per_page, "status": "any"})
        res = await _request_with_retry(self._client, self._cfg, url)
        items = res.json()
        total = int(res.headers.get("X-WP-Total", len(items)))
        total_pages = int(res.headers.get("X-WP-TotalPages", 1))
        return PagedResult(items=items, total=total, total_pages=total_pages, page=page)

    async def get_all_products(
        self, on_progress: Optional[Callable[[int, int], None]] = None
    ) -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        page = 1
        total_pages = 1
        while True:
            result = await self.get_products_page(page, 100)
            all_items.extend(result.items)
            total_pages = result.total_pages or 1
            if on_progress:
                on_progress(page, total_pages)
            page += 1
            if page <= total_pages:
                await asyncio.sleep(0.3)
            else:
                break
        return all_items

    async def get_variations_page(self, product_id: int, page: int, per_page: int = 100) -> PagedResult:
        url = _build_url(self._cfg, f"/products/{product_id}/variations", {"page": page, "per_page": per_page})
        res = await _request_with_retry(self._client, self._cfg, url)
        items = res.json()
        total = int(res.headers.get("X-WP-Total", len(items)))
        total_pages = int(res.headers.get("X-WP-TotalPages", 1))
        return PagedResult(items=items, total=total, total_pages=total_pages, page=page)

    async def get_all_variations(
        self, product_id: int, on_progress: Optional[Callable[[int, int], None]] = None
    ) -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        page = 1
        total_pages = 1
        while True:
            result = await self.get_variations_page(product_id, page, 100)
            all_items.extend(result.items)
            total_pages = result.total_pages or 1
            if on_progress:
                on_progress(page, total_pages)
            page += 1
            if page <= total_pages:
                await asyncio.sleep(0.3)
            else:
                break
        return all_items

    async def get_categories(self) -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        page = 1
        while True:
            url = _build_url(self._cfg, "/products/categories", {"page": page, "per_page": 100})
            res = await _request_with_retry(self._client, self._cfg, url)
            items = res.json()
            all_items.extend(items)
            total_pages = int(res.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages or not items:
                break
            page += 1
            await asyncio.sleep(0.3)
        return all_items

    # ------------------------------------------------------------------
    # NO IMPLEMENTADO A PROPÓSITO (mismo alcance que el script de auditoría):
    # get_orders / create_product / update_product / delete_product /
    # update_stock requieren permisos de escritura, no aprobados todavía.
    # ------------------------------------------------------------------
