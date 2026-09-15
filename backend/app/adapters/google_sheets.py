"""
GoogleSheetsAdapter — OAuth 2.0 real + lectura de hojas de cálculo sobre la
API oficial de Google (Sheets API v4).

Mismo criterio que app/adapters/mercadolibre.py: nada acá se inventa, cada
método corresponde 1 a 1 a un endpoint real y documentado. Endpoints y
scope verificados contra la documentación oficial vigente el 5 de
septiembre de 2026:
  - Autorización: https://developers.google.com/identity/protocols/oauth2/web-server
  - API de Sheets: https://developers.google.com/sheets/api/reference/rest

Scope usado — EL MÍNIMO posible, a propósito (pedido explícito del dueño:
"no inventes scopes, documenta/configura únicamente los estrictamente
necesarios"): `https://www.googleapis.com/auth/spreadsheets.readonly`.
Con este único scope alcanza para leer cualquier spreadsheet al que la
cuenta de Google del dueño tenga acceso (propio o compartido) IDENTIFICADO
POR SU ID — no hace falta ningún scope de Google Drive. Por eso esta
primera versión no ofrece un selector visual "elige un archivo de tu
Drive" (eso exigiría drive.readonly, que Google somete a una revisión de
seguridad mucho más estricta, o el Picker API con drive.file, que agrega
una librería JS + API key adicionales): el dueño pega el link o el ID de
la hoja de cálculo, igual que ya hace con cualquier link de Google Sheets
que comparte hoy. Ver app/api/routes/google_sheets.py, extract_spreadsheet_id.

Flujo de OAuth (Authorization Code, sin PKCE): Google no lo exige ni lo
recomienda para clientes confidenciales tipo "Web application" (los que
pueden guardar un client_secret en el servidor) — a diferencia de Mercado
Libre, donde se manda igual "por las dudas", acá no se agrega porque
sumaría un parámetro que la documentación oficial no pide para este tipo
de cliente y el pedido explícito fue no inventar nada de más.
  1. build_authorization_url(state) -> el dueño abre esa URL, inicia sesión
     en Google y autoriza el acceso de solo lectura a Sheets.
  2. Google redirige a GOOGLE_REDIRECT_URI con ?code=...
  3. exchange_code_for_tokens(code) -> access_token + refresh_token reales.
     `access_type=offline` + `prompt=consent` en el paso 1 son los que
     garantizan que Google mande un refresh_token (si no se fuerza
     "consent", en un reintento de un mismo usuario Google puede omitirlo).
  4. refresh_tokens(refresh_token) cuando el access_token expira (~1 hora).
     A diferencia de Mercado Libre, Google normalmente NO devuelve un
     refresh_token nuevo al renovar — se sigue usando el mismo indefinida-
     mente (ver app/api/routes/google_sheets.py, que conserva el anterior
     si la respuesta no trae uno nuevo).
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# El único scope que esta integración necesita — ver docstring del módulo.
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Un link real de Google Sheets tiene la forma
# https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0 — el ID es la
# parte entre "/d/" y la siguiente "/". Si lo que llega no matchea esto, se
# asume que ya es el ID pelado (el dueño lo pegó directo).
_SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")


def extract_spreadsheet_id(url_o_id: str) -> str:
    """Acepta tanto el link completo que copia/pega el navegador como el ID
    solo — nunca le exige al dueño que sepa "cuál es el ID de una hoja"."""
    texto = url_o_id.strip()
    match = _SPREADSHEET_URL_RE.search(texto)
    if match:
        return match.group(1)
    return texto


class GoogleAuthError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class GoogleRequestError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, response_body: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.response_body = response_body


@dataclass
class GoogleSheetsConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass
class GoogleTokenResponse:
    access_token: str
    expires_in: int  # segundos — típicamente 3600 (1 hora)
    refresh_token: Optional[str] = None  # None en una renovación: ver docstring del módulo
    token_type: str = "Bearer"
    scope: str = ""


def _backoff_delay_s(attempt: int) -> float:
    base = min(8.0, 0.3 * (2**attempt))
    return base + random.random() * 0.2


class GoogleSheetsAdapter:
    def __init__(self, config: GoogleSheetsConfig, client: Optional[httpx.AsyncClient] = None):
        self._cfg = config
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def build_authorization_url(self, state: str) -> str:
        """URL a la que el dueño tiene que ir para autorizar el acceso de
        solo lectura a Google Sheets. `state` protege contra CSRF (se
        guarda antes de redirigir y se valida en el callback, igual que en
        Mercado Libre). `access_type=offline` pide un refresh_token;
        `prompt=consent` fuerza que Google lo mande SIEMPRE, incluso si el
        dueño ya había autorizado antes (si no, un reintento puede volver
        sin refresh_token y la conexión quedaría sin poder renovarse
        sola)."""
        params = {
            "client_id": self._cfg.client_id,
            "redirect_uri": self._cfg.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> GoogleTokenResponse:
        return await self._request_tokens(
            {
                "grant_type": "authorization_code",
                "client_id": self._cfg.client_id,
                "client_secret": self._cfg.client_secret,
                "code": code,
                "redirect_uri": self._cfg.redirect_uri,
            }
        )

    async def refresh_tokens(self, refresh_token: str) -> GoogleTokenResponse:
        return await self._request_tokens(
            {
                "grant_type": "refresh_token",
                "client_id": self._cfg.client_id,
                "client_secret": self._cfg.client_secret,
                "refresh_token": refresh_token,
            }
        )

    async def _request_tokens(self, form_data: dict[str, str]) -> GoogleTokenResponse:
        response = await self._request_with_retry("POST", TOKEN_URL, None, form_data=form_data)
        body = response.json()
        return GoogleTokenResponse(
            access_token=body["access_token"],
            expires_in=body["expires_in"],
            refresh_token=body.get("refresh_token"),
            token_type=body.get("token_type", "Bearer"),
            scope=body.get("scope", ""),
        )

    async def get_spreadsheet_metadata(self, access_token: str, spreadsheet_id: str) -> dict[str, Any]:
        """GET /v4/spreadsheets/{id} — título del archivo y nombre de cada
        hoja/pestaña que contiene, para que el dueño elija cuál usar como
        catálogo (un mismo archivo de Sheets puede tener varias pestañas)."""
        params = {"fields": "properties.title,sheets.properties(title,sheetId)"}
        url = f"{SHEETS_API_BASE}/{spreadsheet_id}?{urlencode(params)}"
        response = await self._request_with_retry("GET", url, access_token)
        body = response.json()
        return {
            "titulo": body.get("properties", {}).get("title", ""),
            "hojas": [s["properties"]["title"] for s in body.get("sheets", [])],
        }

    async def get_values(self, access_token: str, spreadsheet_id: str, hoja: str) -> tuple[list[str], list[dict[str, Any]]]:
        """GET /v4/spreadsheets/{id}/values/{range} — trae TODAS las celdas
        de la pestaña pedida y las convierte a la misma forma
        (encabezados, filas) que devuelve app/domain/spreadsheet_io.py para
        un Excel/CSV subido — así el resto del pipeline (detect_columns,
        build_rows) es exactamente el mismo código, sin importar de dónde
        vinieron los datos."""
        # UNFORMATTED_VALUE: números/precios como número real, no como texto
        # formateado ("$1.234,56") — mismo criterio que ya aplica
        # catalog_import._to_number sobre un Excel/CSV.
        params = {"valueRenderOption": "UNFORMATTED_VALUE", "majorDimension": "ROWS"}
        range_ = quote(hoja, safe="")  # nombre de hoja como segmento de URL (puede tener espacios/tildes)
        url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_}?{urlencode(params)}"
        response = await self._request_with_retry("GET", url, access_token)
        body = response.json()
        values: list[list[Any]] = body.get("values", [])
        if not values:
            return [], []

        raw_header = values[0]
        headers = [str(h).strip() if h is not None and str(h).strip() else f"columna_{i + 1}" for i, h in enumerate(raw_header)]

        rows: list[dict[str, Any]] = []
        for fila in values[1:]:
            if not any(str(v).strip() for v in fila if v is not None):
                continue
            row = {headers[i]: (fila[i] if i < len(fila) else "") for i in range(len(headers))}
            rows.append(row)
        return headers, rows

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        access_token: Optional[str],
        form_data: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        max_attempts = self._cfg.max_retries + 1
        last_error: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                if method == "GET":
                    response = await self._client.get(url, headers=headers, timeout=self._cfg.timeout_s)
                else:
                    response = await self._client.post(url, data=form_data, headers=headers, timeout=self._cfg.timeout_s)
            except httpx.HTTPError as err:
                last_error = err
                if attempt < max_attempts - 1:
                    await asyncio.sleep(_backoff_delay_s(attempt))
                    continue
                raise GoogleRequestError(f"No se pudo conectar con {url}: {err}") from err

            if response.status_code in (401, 403):
                body_detail = ""
                try:
                    if response.text:
                        body_detail = f" Respuesta de Google: {response.text[:500]}"
                except Exception:
                    pass
                raise GoogleAuthError(
                    f"Google rechazó la autenticación (HTTP {response.status_code}).{body_detail}",
                    response.status_code,
                )

            if response.status_code in RETRYABLE_STATUS and attempt < max_attempts - 1:
                await asyncio.sleep(_backoff_delay_s(attempt))
                continue

            if response.status_code >= 400:
                try:
                    response_body = response.json()
                except Exception:
                    response_body = None
                raise GoogleRequestError(
                    f"Google respondió HTTP {response.status_code} en {url}: {response.text[:500]}",
                    status=response.status_code,
                    response_body=response_body,
                )

            return response

        raise GoogleRequestError(str(last_error) if last_error else "Error desconocido")
