"""
MercadoLibreAdapter — OAuth 2.0 real + lectura de pedidos sobre la API de
Mercado Libre (`https://api.mercadolibre.com`).

Ningún dato de acá se inventa: cada método corresponde 1 a 1 a un endpoint
real y documentado de la API de Mercado Libre. Sin credenciales
configuradas (MERCADOLIBRE_CLIENT_ID/SECRET/REDIRECT_URI en .env), este
adaptador simplemente no se puede usar — ver app/api/routes/mercadolibre.py,
que valida eso antes de instanciarlo y explica exactamente qué falta.

Flujo de OAuth (Authorization Code + PKCE, la misma que ML documenta para
aplicaciones de servidor con client_secret — PKCE es opcional según la
documentación oficial, pero se manda siempre; ver generate_pkce_pair()):
  1. build_authorization_url(state, code_challenge) -> el dueño abre esa
     URL, inicia sesión en Mercado Libre y autoriza la app.
  2. Mercado Libre redirige a MERCADOLIBRE_REDIRECT_URI con ?code=...
  3. exchange_code_for_tokens(code, code_verifier) -> access_token +
     refresh_token reales.
  4. refresh_tokens(refresh_token) cuando el access_token expira (6 horas)
     — Mercado Libre devuelve un refresh_token NUEVO en cada renovación
     (de un solo uso): siempre hay que guardar el que llega, nunca reusar
     el anterior (ver app/api/routes/mercadolibre.py).

El dominio de autorización (paso 1) es específico por país
(auth.mercadolibre.cl para Chile, .com.ar para Argentina, etc.) — el de
intercambio de tokens y el resto de la API (pasos 2 en adelante) es el
mismo para todos los países: api.mercadolibre.com.

DELIBERADAMENTE sin ninguna operación de escritura (no crea/edita
publicaciones, no actualiza stock/precio en Mercado Libre) — mismo alcance
inicial que el adaptador de WooCommerce cuando se construyó: solo lectura.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import random
import secrets
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

API_BASE_URL = "https://api.mercadolibre.com"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class MercadoLibreAuthError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class MercadoLibreRequestError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass
class MercadoLibreConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    auth_domain: str = "auth.mercadolibre.cl"
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int  # segundos — típicamente 21600 (6 horas)
    user_id: int
    token_type: str = "bearer"


def _backoff_delay_s(attempt: int) -> float:
    base = min(8.0, 0.3 * (2**attempt))
    return base + random.random() * 0.2


def generate_pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) — PKCE (RFC 7636), documentado por
    Mercado Libre como opcional (solo obligatorio si la app lo activa en el
    DevCenter), pero se envía siempre acá: es una capa extra de protección
    contra interceptación del código de autorización, sin costo si la app
    no lo exige (ML simplemente ignora el parámetro). code_challenge_method
    S256, el único recomendado por la documentación oficial (junto a
    "plain", que ML desaconseja)."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class MercadoLibreAdapter:
    def __init__(self, config: MercadoLibreConfig, client: Optional[httpx.AsyncClient] = None):
        self._cfg = config
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def build_authorization_url(self, state: str, code_challenge: Optional[str] = None) -> str:
        """URL a la que el dueño tiene que ir para conectar su cuenta real
        de Mercado Libre — inicia el flujo de OAuth. `state` protege contra
        CSRF: se guarda antes de redirigir y se valida en el callback.
        `code_challenge` (PKCE, opcional) va emparejado con el
        `code_verifier` que se manda en exchange_code_for_tokens."""
        params = {
            "response_type": "code",
            "client_id": self._cfg.client_id,
            "redirect_uri": self._cfg.redirect_uri,
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"https://{self._cfg.auth_domain}/authorization?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str, code_verifier: Optional[str] = None) -> TokenResponse:
        form_data = {
            "grant_type": "authorization_code",
            "client_id": self._cfg.client_id,
            "client_secret": self._cfg.client_secret,
            "code": code,
            "redirect_uri": self._cfg.redirect_uri,
        }
        if code_verifier:
            form_data["code_verifier"] = code_verifier
        return await self._request_tokens(form_data)

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        return await self._request_tokens(
            {
                "grant_type": "refresh_token",
                "client_id": self._cfg.client_id,
                "client_secret": self._cfg.client_secret,
                "refresh_token": refresh_token,
            }
        )

    async def _request_tokens(self, form_data: dict[str, str]) -> TokenResponse:
        url = f"{API_BASE_URL}/oauth/token"
        response = await self._post_with_retry(url, form_data)
        body = response.json()
        return TokenResponse(
            access_token=body["access_token"],
            refresh_token=body["refresh_token"],
            expires_in=body["expires_in"],
            user_id=body["user_id"],
            token_type=body.get("token_type", "bearer"),
        )

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """GET /users/me — confirma que el token funciona y trae el user_id
        real del vendedor (necesario para pedir sus pedidos)."""
        return await self._get_with_retry("/users/me", access_token)

    async def search_orders(
        self,
        access_token: str,
        seller_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
        order_date_from: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET /orders/search — pedidos reales del vendedor, paginado.
        `order_date_from` (ISO 8601) permite pedir solo pedidos nuevos desde
        la última importación en vez de traer todo el historial cada vez."""
        params: dict[str, Any] = {"seller": seller_id, "offset": offset, "limit": limit}
        if order_date_from:
            params["order.date_created.from"] = order_date_from
        query = urlencode(params)
        return await self._get_with_retry(f"/orders/search?{query}", access_token)

    async def get_order(self, access_token: str, order_id: str) -> dict[str, Any]:
        """GET /orders/{id} — detalle completo de un pedido puntual (incluye
        order_items con sale_fee real por ítem, la comisión que ML cobró de
        verdad en esa venta)."""
        return await self._get_with_retry(f"/orders/{order_id}", access_token)

    async def _get_with_retry(self, path: str, access_token: str) -> dict[str, Any]:
        url = f"{API_BASE_URL}{path}"
        response = await self._request_with_retry("GET", url, access_token)
        return response.json()

    async def _post_with_retry(self, url: str, form_data: dict[str, str]) -> httpx.Response:
        return await self._request_with_retry("POST", url, None, form_data=form_data)

    async def _request_with_retry(
        self, method: str, url: str, access_token: Optional[str], form_data: Optional[dict[str, str]] = None
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        last_error: Optional[Exception] = None
        for attempt in range(self._cfg.max_retries + 1):
            try:
                if method == "GET":
                    response = await self._client.get(url, headers=headers, timeout=self._cfg.timeout_s)
                else:
                    response = await self._client.post(url, data=form_data, headers=headers, timeout=self._cfg.timeout_s)
            except httpx.HTTPError as err:
                last_error = err
                if attempt < self._cfg.max_retries:
                    await asyncio.sleep(_backoff_delay_s(attempt))
                    continue
                raise MercadoLibreRequestError(f"No se pudo conectar con {url}: {err}") from err

            if response.status_code in (401, 403):
                body_detail = ""
                try:
                    if response.text:
                        body_detail = f" Respuesta de Mercado Libre: {response.text[:500]}"
                except Exception:
                    pass
                raise MercadoLibreAuthError(
                    f"Mercado Libre rechazó la autenticación (HTTP {response.status_code}).{body_detail}",
                    response.status_code,
                )

            if response.status_code in RETRYABLE_STATUS and attempt < self._cfg.max_retries:
                await asyncio.sleep(_backoff_delay_s(attempt))
                continue

            if response.status_code >= 400:
                raise MercadoLibreRequestError(
                    f"Mercado Libre respondió HTTP {response.status_code} en {url}: {response.text[:500]}",
                    status=response.status_code,
                )

            return response

        raise MercadoLibreRequestError(str(last_error) if last_error else "Error desconocido")
