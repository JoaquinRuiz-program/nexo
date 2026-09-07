"""
MercadoPagoAdapter — cobro real de la mensualidad/anualidad de Nexo sobre
la API oficial de Mercado Pago (`https://api.mercadopago.com`).

Distinto de Mercado Libre/Google Sheets en una cosa fundamental: ahí cada
EMPRESA CLIENTE conecta su propia cuenta (OAuth, tokens por tienda). Acá es
al revés — Nexo es el vendedor (el SaaS que cobra), así que hay una única
cuenta de Mercado Pago (la del dueño de Nexo) y un único `access_token` de
servidor (nunca OAuth, nunca por tienda) para TODOS los clientes. Por eso
este adaptador no toca `MarketplaceAccount` — el estado de cobro vive en
`Subscription` (ver app/db/models/subscriptions.py y
app/api/routes/pagos.py).

Dos productos reales de Mercado Pago, uno por ciclo de facturación:

- **Mensual -> Suscripciones (`/preapproval`)**: cobro recurrente real,
  Mercado Pago vuelve a cobrar la tarjeta guardada cada mes solo. El
  dueño de la tarjeta la ingresa en el checkout hosteado de Mercado Pago
  (`init_point`) — Nexo nunca ve ni toca el número de tarjeta.
- **Anual -> Pago único (`/checkout/preferences`, "Checkout Pro")**: un
  cobro real por el total del año (con el descuento configurado, ver
  app/domain/plans.py::precio_anual_clp), no un cobro recurrente de
  Mercado Pago. Decisión deliberada, no un atajo: la documentación oficial
  de "Suscripciones" describe con precisión y ejemplos consistentes cobros
  recurrentes de periodicidad mensual (`frequency_type: "months"`,
  `frequency: 1`); no hay una confirmación igual de clara y consistente
  para "cobrar automáticamente una sola vez cada 12 meses" sin repetir el
  checkout. Antes que adivinar el comportamiento de un cobro real con
  dinero de por medio, se eligió el camino 100% documentado y sin ambigüedad:
  el ciclo anual se renueva con un nuevo pago único cuando se acerca la
  fecha de renovación (Nexo puede avisarle al cliente, pero nunca le vuelve
  a cobrar la tarjeta sin que él vuelva a confirmar el pago).

Nunca se cambia esto a "cobro automático anual real" sin volver a
verificar contra la documentación oficial vigente en ese momento.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import random
from dataclasses import dataclass
from typing import Any, Optional

import httpx

API_BASE_URL = "https://api.mercadopago.com"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

CURRENCY_ID = "CLP"


class MercadoPagoAuthError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class MercadoPagoRequestError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, response_body: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.response_body = response_body


@dataclass
class MercadoPagoConfig:
    access_token: str
    webhook_secret: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES

    def is_configured(self) -> bool:
        return bool(self.access_token)


def _backoff_delay_s(attempt: int) -> float:
    base = min(8.0, 0.3 * (2**attempt))
    return base + random.random() * 0.2


def validar_firma_webhook(*, x_signature: str, x_request_id: str, data_id: str, secret: str) -> bool:
    """Valida el header `X-Signature` de un webhook real de Mercado Pago —
    ver "Tus integraciones" -> Webhooks -> Configurar notificaciones, donde
    se genera `secret`. Documentación oficial (Mercado Pago Developers,
    "Additional information about notifications"): el header trae
    `ts=<timestamp>,v1=<hmac>`; el HMAC-SHA256 se calcula sobre el
    "manifest" `id:<data.id en minúscula>;request-id:<X-Request-Id>;ts:<ts>;`
    (cada parte se OMITE del todo, nunca se deja vacía, si el dato no está
    disponible) usando `secret` como clave.

    Sin esto, cualquiera podría mandar un POST fingiendo "este cliente ya
    pagó" — por eso app/api/routes/pagos.py rechaza (400) cualquier webhook
    si `MERCADOPAGO_WEBHOOK_SECRET` no está configurada, en vez de
    aceptarlo sin verificar."""
    partes = {}
    for trozo in x_signature.split(","):
        if "=" not in trozo:
            continue
        clave, _, valor = trozo.partition("=")
        partes[clave.strip()] = valor.strip()
    ts = partes.get("ts")
    v1_recibido = partes.get("v1")
    if not ts or not v1_recibido:
        return False

    # Orden fijo id -> request-id -> ts; un segmento se OMITE del todo
    # (nunca se deja vacío) si el dato correspondiente no está disponible.
    segmentos = []
    if data_id:
        segmentos.append(f"id:{data_id.lower()};")
    if x_request_id:
        segmentos.append(f"request-id:{x_request_id};")
    segmentos.append(f"ts:{ts};")
    manifest = "".join(segmentos)

    v1_calculado = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(v1_calculado, v1_recibido)


class MercadoPagoAdapter:
    def __init__(self, config: MercadoPagoConfig, client: Optional[httpx.AsyncClient] = None):
        self._cfg = config
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def crear_suscripcion_mensual(
        self, *, payer_email: str, reason: str, monto_clp: int, external_reference: str, back_url: str
    ) -> dict[str, Any]:
        """POST /preapproval SIN `card_token_id` ni `status` — Mercado Pago
        responde con `init_point`, la URL del checkout hosteado donde el
        dueño de la tarjeta la ingresa de verdad (Nexo nunca la ve). La
        suscripción queda "pending" hasta que complete ese checkout; el
        webhook (`subscription_preapproval`) avisa cuándo pasa a
        "authorized" — ver app/api/routes/pagos.py."""
        payload = {
            "reason": reason,
            "external_reference": external_reference,
            "payer_email": payer_email,
            "back_url": back_url,
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": monto_clp,
                "currency_id": CURRENCY_ID,
            },
        }
        # retry_on_failure=False: crear una suscripción NO es idempotente
        # (un reintento automático podría crear una segunda suscripción
        # real) — mismo criterio que create_item en adapters/mercadolibre.py.
        response = await self._request_with_retry("POST", f"{API_BASE_URL}/preapproval", json_body=payload, retry_on_failure=False)
        return response.json()

    async def crear_pago_unico(
        self, *, payer_email: str, reason: str, monto_clp: int, external_reference: str, back_url: str
    ) -> dict[str, Any]:
        """POST /checkout/preferences ("Checkout Pro") — un pago único real
        por `monto_clp` (usado para el ciclo anual, ver docstring del
        módulo). Devuelve `init_point`, la URL del checkout hosteado."""
        payload = {
            "items": [{"title": reason, "quantity": 1, "unit_price": monto_clp, "currency_id": CURRENCY_ID}],
            "payer": {"email": payer_email},
            "external_reference": external_reference,
            "back_urls": {"success": back_url, "pending": back_url, "failure": back_url},
            "auto_return": "approved",
        }
        response = await self._request_with_retry("POST", f"{API_BASE_URL}/checkout/preferences", json_body=payload, retry_on_failure=False)
        return response.json()

    async def obtener_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        """GET /preapproval/{id} — estado REAL actual de una suscripción.
        Nunca se confía en el cuerpo del webhook para saber "cuánto" o
        "qué estado" tiene un cobro — siempre se le vuelve a preguntar a
        Mercado Pago con esto (ver app/api/routes/pagos.py)."""
        response = await self._request_with_retry("GET", f"{API_BASE_URL}/preapproval/{preapproval_id}")
        return response.json()

    async def obtener_pago(self, payment_id: str) -> dict[str, Any]:
        """GET /v1/payments/{id} — estado REAL actual de un pago (único o
        de una suscripción). Mismo criterio que obtener_preapproval: la
        fuente de verdad es esta consulta, nunca el payload del webhook."""
        response = await self._request_with_retry("GET", f"{API_BASE_URL}/v1/payments/{payment_id}")
        return response.json()

    async def cancelar_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        """PUT /preapproval/{id} con status=cancelled — termina de verdad
        el cobro recurrente en Mercado Pago (no alcanza con borrar el dato
        local: si no se cancela allá, Mercado Pago sigue cobrando la
        tarjeta del cliente el mes que viene)."""
        response = await self._request_with_retry(
            "PUT", f"{API_BASE_URL}/preapproval/{preapproval_id}", json_body={"status": "cancelled"}
        )
        return response.json()

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        json_body: Optional[dict[str, Any]] = None,
        retry_on_failure: bool = True,
    ) -> httpx.Response:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self._cfg.access_token}"}
        max_attempts = (self._cfg.max_retries + 1) if retry_on_failure else 1

        last_error: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                if method == "GET":
                    response = await self._client.get(url, headers=headers, timeout=self._cfg.timeout_s)
                elif method == "PUT":
                    response = await self._client.put(url, json=json_body, headers=headers, timeout=self._cfg.timeout_s)
                else:
                    response = await self._client.post(url, json=json_body, headers=headers, timeout=self._cfg.timeout_s)
            except httpx.HTTPError as err:
                last_error = err
                if attempt < max_attempts - 1:
                    await asyncio.sleep(_backoff_delay_s(attempt))
                    continue
                raise MercadoPagoRequestError(f"No se pudo conectar con {url}: {err}") from err

            if response.status_code in (401, 403):
                body_detail = ""
                try:
                    if response.text:
                        body_detail = f" Respuesta de Mercado Pago: {response.text[:500]}"
                except Exception:
                    pass
                raise MercadoPagoAuthError(
                    f"Mercado Pago rechazó la autenticación (HTTP {response.status_code}).{body_detail}",
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
                raise MercadoPagoRequestError(
                    f"Mercado Pago respondió HTTP {response.status_code} en {url}: {response.text[:500]}",
                    status=response.status_code,
                    response_body=response_body,
                )

            return response

        raise MercadoPagoRequestError(str(last_error) if last_error else "Error desconocido")
