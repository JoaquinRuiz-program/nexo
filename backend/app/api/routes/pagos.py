"""
Cobro real de la mensualidad/anualidad de Nexo con Mercado Pago — 6 de
septiembre de 2026.

Flujo (mensual o anual, ver app/adapters/mercadopago.py para por qué son
mecanismos distintos):

1. Frontend: pantalla "Mi plan" -> elegir plan + ciclo -> POST /iniciar
2. Acá se arma un `external_reference` que codifica QUÉ tienda, QUÉ plan y
   QUÉ ciclo eligió — nunca se escribe nada en la Subscription todavía
   (elegir un plan y pagarlo de verdad son cosas distintas; si el dueño
   cierra el checkout de Mercado Pago sin pagar, la suscripción actual
   sigue exactamente igual que antes).
3. El navegador va de verdad a la URL de Mercado Pago (`init_point`) —
   ahí es donde se ingresa la tarjeta, Nexo nunca la ve.
4. Mercado Pago redirige de vuelta a GET /callback (una URL de ESTE
   backend, nunca del frontend directo — mismo motivo que
   app/api/routes/mercadolibre.py::_frontend_redirect: evita mezclar los
   parámetros que agrega Mercado Pago con el router de hash del frontend),
   que a su vez redirige al frontend con un aviso genérico ("estamos
   confirmando tu pago"). Esta redirección es SOLO para la experiencia del
   navegador — nunca decide nada por sí sola.
5. POST /webhook es la ÚNICA fuente de verdad de "se pagó de verdad":
   Mercado Pago lo llama server-a-server, con una firma verificable
   (X-Signature) que acá se valida contra `MERCADOPAGO_WEBHOOK_SECRET`.
   Al recibir uno, se le vuelve a preguntar a la propia API de Mercado
   Pago (GET /preapproval/{id} o GET /v1/payments/{id}) el estado real —
   nunca se confía en los datos que trae el cuerpo del webhook a ciegas.

Aislamiento: cada acción de este router que actúa sobre "mi suscripción"
cuelga de `get_current_store` (nunca un `store_id` que mande el cliente).
La única excepción es `/webhook` (server-a-server, sin sesión posible,
protegido en cambio por la firma) y `/callback` (mismo criterio que los
callbacks de OAuth: el navegador puede llegar sin cookie de Nexo).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.mercadopago import (
    MercadoPagoAdapter,
    MercadoPagoAuthError,
    MercadoPagoConfig,
    MercadoPagoRequestError,
    validar_firma_webhook,
)
from app.api.deps import get_current_store
from app.config import Settings, get_settings
from app.db.models import Store, Subscription
from app.db.session import get_db
from app.domain.plans import DESCUENTO_ANUAL_PCT, ensure_default_plans, precio_anual_clp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pagos", tags=["pagos"])

CICLOS_VALIDOS = ("mensual", "anual")
_REFERENCIA_PREFIJO = "nexo"


def _build_mp_config(settings: Settings) -> MercadoPagoConfig:
    return MercadoPagoConfig(access_token=settings.mercadopago_access_token, webhook_secret=settings.mercadopago_webhook_secret)


def _require_configured(cfg: MercadoPagoConfig, settings: Settings) -> None:
    faltantes = []
    if not cfg.access_token:
        faltantes.append("MERCADOPAGO_ACCESS_TOKEN")
    if not settings.mercadopago_webhook_secret:
        faltantes.append("MERCADOPAGO_WEBHOOK_SECRET")
    if faltantes:
        # El detalle operativo va al log del servidor, nunca al cliente
        # (mismo criterio que mercadolibre.py y google_sheets.py).
        print(
            f"AVISO: no se puede cobrar — faltan en backend/.env: {', '.join(faltantes)}. "
            "Son las credenciales de la cuenta de Mercado Pago de NEXO "
            "(https://www.mercadopago.cl/developers/panel, una sola vez para toda la plataforma)."
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "El pago en línea todavía no está habilitado en Nexo. "
                "Escríbenos desde Ayuda y soporte y coordinamos el pago contigo."
            ),
        )


def _armar_referencia(store_id: int, plan_code: str, ciclo: str) -> str:
    return f"{_REFERENCIA_PREFIJO}:{store_id}:{plan_code}:{ciclo}"


def _leer_referencia(referencia: str) -> tuple[int, str, str] | None:
    partes = (referencia or "").split(":")
    if len(partes) != 4 or partes[0] != _REFERENCIA_PREFIJO:
        return None
    try:
        store_id = int(partes[1])
    except ValueError:
        return None
    plan_code, ciclo = partes[2], partes[3]
    if ciclo not in CICLOS_VALIDOS:
        return None
    return store_id, plan_code, ciclo


@router.get("/planes")
def listar_planes_disponibles(db: Session = Depends(get_db), _store: Store = Depends(get_current_store)) -> list[dict]:
    """Planes reales que un cliente puede elegir y pagar — precio mensual y
    el anual ya calculado con el descuento vigente, para que el frontend
    nunca tenga que hacer la cuenta (una sola fuente de verdad del
    descuento: app/domain/plans.py::precio_anual_clp)."""
    planes = ensure_default_plans(db)
    db.commit()
    return [
        {
            "codigo": p.code,
            "nombre": p.name,
            "limiteProductos": p.product_limit,
            "limitePublicaciones": p.publication_limit,
            "precioMensualClp": p.monthly_price_clp,
            "precioAnualClp": precio_anual_clp(p.monthly_price_clp) if p.monthly_price_clp is not None else None,
            "descuentoAnualPct": DESCUENTO_ANUAL_PCT,
            "features": p.features,
        }
        for p in sorted(planes.values(), key=lambda p: p.id)
        if p.is_active
    ]


class IniciarPagoRequest(BaseModel):
    planCode: str
    ciclo: str


@router.post("/iniciar")
async def iniciar_pago(
    body: IniciarPagoRequest, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    if body.ciclo not in CICLOS_VALIDOS:
        raise HTTPException(status_code=400, detail="El ciclo de facturación tiene que ser 'mensual' o 'anual'.")

    settings = get_settings()
    cfg = _build_mp_config(settings)
    _require_configured(cfg, settings)

    planes = ensure_default_plans(db)
    plan = planes.get(body.planCode)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=404, detail="Plan no encontrado.")
    if plan.monthly_price_clp is None:
        raise HTTPException(status_code=400, detail="Este plan todavía no tiene un precio configurado para cobro automático — escríbenos desde Ayuda y soporte.")
    db.commit()

    monto_clp = plan.monthly_price_clp if body.ciclo == "mensual" else precio_anual_clp(plan.monthly_price_clp)
    referencia = _armar_referencia(store.id, plan.code, body.ciclo)
    razon = f"Nexo {plan.name} — {'mensual' if body.ciclo == 'mensual' else 'anual'}"
    back_url = f"{settings.backend_public_base_url}/api/pagos/callback"

    adapter = MercadoPagoAdapter(cfg)
    try:
        if body.ciclo == "mensual":
            resultado = await adapter.crear_suscripcion_mensual(
                payer_email=store.owner.email, reason=razon, monto_clp=monto_clp, external_reference=referencia, back_url=back_url
            )
        else:
            resultado = await adapter.crear_pago_unico(
                payer_email=store.owner.email, reason=razon, monto_clp=monto_clp, external_reference=referencia, back_url=back_url
            )
    except MercadoPagoAuthError as err:
        logger.error("Mercado Pago rechazó la autenticación al iniciar un pago para store_id=%s: %s", store.id, err)
        raise HTTPException(status_code=502, detail="Mercado Pago rechazó la solicitud. Avísale a soporte.") from err
    except MercadoPagoRequestError as err:
        logger.error("No se pudo iniciar el pago en Mercado Pago para store_id=%s: %s", store.id, err)
        raise HTTPException(status_code=502, detail="No pudimos iniciar el pago con Mercado Pago en este momento. Intenta de nuevo más tarde.") from err
    finally:
        await adapter.aclose()

    checkout_url = resultado.get("init_point")
    if not checkout_url:
        logger.error("Mercado Pago no devolvió init_point para store_id=%s: %s", store.id, resultado)
        raise HTTPException(status_code=502, detail="Mercado Pago no devolvió una URL de pago válida.")

    return {"checkoutUrl": checkout_url}


def _frontend_redirect(settings: Settings, *, pago: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_base_url}/?pago={pago}#/suscripcion", status_code=303)


@router.get("/callback")
async def callback(request: Request) -> RedirectResponse:
    """A dónde vuelve el navegador después de pasar por el checkout de
    Mercado Pago — SIEMPRE redirige al frontend (nunca JSON), y NUNCA
    decide nada por sí sola: quien confirma que el pago fue real es
    /webhook. Acá solo se le avisa al dueño "ya estamos procesando tu
    pago" (o "no se completó", si Mercado Pago mandó `status=rejected`),
    en lenguaje simple."""
    settings = get_settings()
    estado_mp = (request.query_params.get("status") or request.query_params.get("collection_status") or "").lower()
    if estado_mp in ("rejected", "cancelled"):
        return _frontend_redirect(settings, pago="rechazado")
    return _frontend_redirect(settings, pago="procesando")


async def _aplicar_pago_confirmado(db: Session, *, store_id: int, plan_code: str, ciclo: str, mercadopago_id: str, es_pago_unico: bool) -> None:
    store = db.get(Store, store_id)
    if store is None:
        logger.error("Webhook de Mercado Pago referencia una tienda inexistente: store_id=%s", store_id)
        return
    planes = ensure_default_plans(db)
    plan = planes.get(plan_code)
    if plan is None:
        logger.error("Webhook de Mercado Pago referencia un plan inexistente: %s", plan_code)
        return

    sub = store.subscription
    if sub is None:
        sub = Subscription(store=store, plan=plan, status="active", started_at=datetime.now(), current_period_end=datetime.now().date())
        db.add(sub)

    ahora = datetime.now()
    dias_periodo = 365 if ciclo == "anual" else 30
    sub.plan = plan
    sub.billing_cycle = ciclo
    sub.status = "active"
    sub.current_period_end = (ahora + timedelta(days=dias_periodo)).date()
    sub.last_payment_at = ahora
    sub.canceled_at = None
    if es_pago_unico:
        sub.mercadopago_last_payment_id = mercadopago_id
    else:
        sub.mercadopago_preapproval_id = mercadopago_id
        sub.mercadopago_last_payment_id = mercadopago_id
    # 13 de septiembre de 2026 — al pagar, el ciclo de vida empieza limpio:
    # se olvida el ultimo recordatorio y la marca de pausa, para que si
    # vuelve a vencer mas adelante los recordatorios arranquen de cero.
    sub.ultimo_hito_recordatorio = None
    sub.publicaciones_pausadas_por_vencimiento = False
    db.commit()

    # Reactivar las publicaciones que Nexo habia pausado por vencimiento
    # (solo esas, ver app/services/lifecycle.py). Tolerante: si Mercado
    # Libre falla ahora, el pago ya quedo aplicado igual.
    try:
        from app.services.lifecycle import reactivar_publicaciones_por_pago
        reactivadas = await reactivar_publicaciones_por_pago(db, store, get_settings())
        if reactivadas:
            db.commit()
            logger.info("Reactivadas %s publicaciones de store_id=%s tras el pago", reactivadas, store_id)
    except Exception as err:  # noqa: BLE001
        logger.error("Pago aplicado pero no se pudieron reactivar las publicaciones de store_id=%s: %r", store_id, err)


async def _aplicar_cancelacion(db: Session, *, store_id: int) -> None:
    store = db.get(Store, store_id)
    if store is None or store.subscription is None:
        return
    sub = store.subscription
    sub.status = "canceled"
    sub.canceled_at = datetime.now()
    db.commit()


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    cfg = _build_mp_config(settings)
    if not cfg.is_configured() or not settings.mercadopago_webhook_secret:
        # Sin credenciales/secreto configurados no hay nada que verificar de
        # forma segura — se rechaza en vez de aceptar un aviso de pago sin
        # poder confirmar que sea realmente de Mercado Pago.
        raise HTTPException(status_code=400, detail="Mercado Pago no está configurado.")

    try:
        body = await request.json()
    except Exception:
        body = {}
    tipo = body.get("type") or request.query_params.get("topic") or ""
    data_id = str((body.get("data") or {}).get("id") or request.query_params.get("id") or "")
    if not tipo or not data_id:
        raise HTTPException(status_code=400, detail="Notificación con formato inesperado.")

    firma_valida = validar_firma_webhook(
        x_signature=request.headers.get("x-signature", ""),
        x_request_id=request.headers.get("x-request-id", ""),
        data_id=data_id,
        secret=settings.mercadopago_webhook_secret,
    )
    if not firma_valida:
        logger.error("Webhook de Mercado Pago con firma inválida (tipo=%s, data_id=%s)", tipo, data_id)
        raise HTTPException(status_code=401, detail="Firma inválida.")

    adapter = MercadoPagoAdapter(cfg)
    try:
        if tipo == "subscription_preapproval":
            recurso = await adapter.obtener_preapproval(data_id)
            referencia = _leer_referencia(recurso.get("external_reference", ""))
            if referencia is None:
                logger.error("Preapproval de Mercado Pago con external_reference no reconocible: %s", recurso.get("external_reference"))
                return {"ok": False}
            store_id, plan_code, ciclo = referencia
            estado_mp = recurso.get("status")
            if estado_mp == "authorized":
                await _aplicar_pago_confirmado(db, store_id=store_id, plan_code=plan_code, ciclo=ciclo, mercadopago_id=data_id, es_pago_unico=False)
            elif estado_mp == "cancelled":
                await _aplicar_cancelacion(db, store_id=store_id)
        elif tipo == "payment":
            recurso = await adapter.obtener_pago(data_id)
            referencia = _leer_referencia(recurso.get("external_reference", ""))
            if referencia is None:
                logger.error("Pago de Mercado Pago con external_reference no reconocible: %s", recurso.get("external_reference"))
                return {"ok": False}
            store_id, plan_code, ciclo = referencia
            if recurso.get("status") == "approved":
                await _aplicar_pago_confirmado(db, store_id=store_id, plan_code=plan_code, ciclo=ciclo, mercadopago_id=data_id, es_pago_unico=True)
        # Otros topics (ej. subscription_authorized_payment, el cobro
        # recurrente MES A MES de una suscripción ya activa) no se procesan
        # todavía en esta primera versión — limitación conocida, ver
        # docstring de app/adapters/mercadopago.py: activar el plan la
        # primera vez está cubierto; detectar que un cobro del mes 2 en
        # adelante falló (para marcar "past_due") queda pendiente.
    except (MercadoPagoAuthError, MercadoPagoRequestError) as err:
        logger.error("No se pudo confirmar contra la API de Mercado Pago el webhook tipo=%s data_id=%s: %s", tipo, data_id, err)
        raise HTTPException(status_code=502, detail="No pudimos confirmar este pago con Mercado Pago en este momento.") from err
    finally:
        await adapter.aclose()

    return {"ok": True}


@router.post("/cancelar")
async def cancelar_suscripcion(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    """Cancela de verdad el cobro recurrente en Mercado Pago (ciclo
    mensual) — nunca alcanza con borrar el dato local, si no se cancela
    allá Mercado Pago sigue cobrando la tarjeta el mes que viene. Un ciclo
    anual (pago único, sin suscripción recurrente de Mercado Pago) no tiene
    nada que cancelar allá — simplemente no se le vuelve a cobrar cuando
    venza, a menos que el dueño confirme un nuevo pago."""
    sub = store.subscription
    if sub is None:
        raise HTTPException(status_code=400, detail="Esta empresa no tiene ninguna suscripción activa.")

    if sub.mercadopago_preapproval_id and sub.billing_cycle == "mensual":
        settings = get_settings()
        cfg = _build_mp_config(settings)
        _require_configured(cfg, settings)
        adapter = MercadoPagoAdapter(cfg)
        try:
            await adapter.cancelar_preapproval(sub.mercadopago_preapproval_id)
        except MercadoPagoAuthError as err:
            raise HTTPException(status_code=502, detail="Mercado Pago rechazó la solicitud. Avísale a soporte.") from err
        except MercadoPagoRequestError as err:
            logger.error("No se pudo cancelar el preapproval %s de store_id=%s: %s", sub.mercadopago_preapproval_id, store.id, err)
            raise HTTPException(status_code=502, detail="No pudimos cancelar la suscripción en Mercado Pago en este momento. Intenta de nuevo más tarde.") from err
        finally:
            await adapter.aclose()

    sub.status = "canceled"
    sub.canceled_at = datetime.now()
    db.commit()
    return {"ok": True}
