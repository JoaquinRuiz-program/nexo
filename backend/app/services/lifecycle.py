"""
Ciclo de vida de la suscripción — proceso que corre UNA vez por día.
13 de septiembre de 2026.

Junta lo que decide `app/domain/subscription_lifecycle.py` (funciones puras)
con los efectos reales: mandar el recordatorio y pausar las publicaciones en
Mercado Libre. La orquestación (`ejecutar_ciclo_de_vida`) recibe los efectos
como parámetros, así se prueba entera con dobles de prueba, sin tocar la red.

En producción lo dispara un cron diario (ver DEPLOY.md) corriendo
`python -m app.services.lifecycle` — un solo comando, sin endpoint HTTP ni
secreto que exponer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Awaitable, Callable

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import MarketplaceAccount, MarketplaceListing, Store, Subscription
from app.domain.reminder_email import armar_recordatorio, enviador_actual
from app.domain.subscription_lifecycle import (
    ESTADOS_SUJETOS_A_VENCIMIENTO,
    DatosVigencia,
    debe_pausar,
    recordatorio_pendiente,
)

logger = logging.getLogger("nexo.lifecycle")

# efecto "pausar todas las publicaciones activas de una tienda" -> nº pausadas
Pausador = Callable[[Store], Awaitable[int]]
# efecto "mandar un mail"
EnviarEmail = Callable[[str, str, str], None]


def _enviar_por_defecto(para: str, asunto: str, cuerpo: str) -> None:
    enviador_actual.enviar(para=para, asunto=asunto, cuerpo=cuerpo)


async def ejecutar_ciclo_de_vida(
    db: Session,
    hoy: date,
    *,
    pausar_publicaciones: Pausador,
    enviar_email: EnviarEmail | None = None,
) -> dict:
    """Recorre las suscripciones sujetas a vencimiento (trial/past_due),
    manda los recordatorios que toquen y pausa las que ya agotaron la gracia.

    Idempotente: un recordatorio no se repite (`ultimo_hito_recordatorio`) y
    la pausa no se vuelve a ejecutar (`publicaciones_pausadas_por_vencimiento`)."""
    enviar = enviar_email or _enviar_por_defecto
    res = {"recordatorios": 0, "empresas_pausadas": 0, "publicaciones_pausadas": 0}

    subs = (
        db.query(Subscription)
        .filter(Subscription.status.in_(ESTADOS_SUJETOS_A_VENCIMIENTO))
        .all()
    )
    for sub in subs:
        vig = DatosVigencia(
            status=sub.status,
            current_period_end=sub.current_period_end,
            ultimo_hito_recordatorio=sub.ultimo_hito_recordatorio,
        )

        hito = recordatorio_pendiente(vig, hoy)
        if hito is not None:
            asunto, cuerpo = armar_recordatorio(
                nombre_empresa=sub.store.name, hito=hito,
                nombre_plan=sub.plan.name if sub.plan else "tu plan",
            )
            try:
                enviar(sub.store.owner.email, asunto, cuerpo)
            except Exception as err:  # noqa: BLE001 - un mail no puede tumbar el proceso
                logger.error("No se pudo enviar el recordatorio a store_id=%s: %r", sub.store_id, err)
            else:
                sub.ultimo_hito_recordatorio = hito
                res["recordatorios"] += 1

        if debe_pausar(vig, hoy) and not sub.publicaciones_pausadas_por_vencimiento:
            try:
                n = await pausar_publicaciones(sub.store)
            except Exception as err:  # noqa: BLE001 - si falla, NO se marca; se reintenta mañana
                logger.error("No se pudieron pausar las publicaciones de store_id=%s: %r", sub.store_id, err)
            else:
                sub.publicaciones_pausadas_por_vencimiento = True
                res["empresas_pausadas"] += 1
                res["publicaciones_pausadas"] += n

    db.commit()
    return res


# ------------------------------------------------------------------
# Efectos reales sobre Mercado Libre. Se importan tarde (dentro de las
# funciones) para no arrastrar el router de publicaciones en los tests del
# orquestador, que usan un pausador de prueba.
# ------------------------------------------------------------------


def _cuenta_ml_conectada(db: Session, store: Store) -> MarketplaceAccount | None:
    return (
        db.query(MarketplaceAccount)
        .filter_by(store_id=store.id, marketplace="mercadolibre", status="connected")
        .first()
    )


def construir_pausador(db: Session, settings: Settings) -> Pausador:
    """Pausa en Mercado Libre TODAS las publicaciones activas de la tienda y
    las marca `paused_by_expiry` (para reactivar solo estas al pagar).
    Tolerante por publicación: si una falla, se registra y sigue. Si ni
    siquiera se puede obtener el token, propaga (el orquestador no marca la
    empresa como pausada y reintenta al otro día)."""
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token
    from app.adapters.mercadolibre import MercadoLibreAdapter

    async def pausar(store: Store) -> int:
        cuenta = _cuenta_ml_conectada(db, store)
        if cuenta is None:
            return 0  # nada que pausar: no tiene Mercado Libre conectado
        cfg = _build_ml_config(settings)
        token = await _get_valid_access_token(db, cuenta, cfg, settings.token_encryption_key)
        activas = (
            db.query(MarketplaceListing)
            .filter(MarketplaceListing.account_id == cuenta.id, MarketplaceListing.status == "active")
            .all()
        )
        adapter = MercadoLibreAdapter(cfg)
        pausadas = 0
        try:
            for listing in activas:
                if not listing.external_listing_id:
                    continue
                try:
                    await adapter.update_item_status(token, listing.external_listing_id, "paused")
                    listing.status = "paused"
                    listing.paused_by_expiry = True
                    pausadas += 1
                except Exception as err:  # noqa: BLE001
                    logger.error("No se pudo pausar la publicacion %s: %r", listing.external_listing_id, err)
        finally:
            await adapter.aclose()
        return pausadas

    return pausar


async def reactivar_publicaciones_por_pago(db: Session, store: Store, settings: Settings) -> int:
    """Al confirmarse un pago, reactiva SOLO las publicaciones que Nexo
    pausó por vencimiento (`paused_by_expiry`), nunca las que el cliente
    había pausado a mano. Se llama desde app/api/routes/pagos.py."""
    pausadas = (
        db.query(MarketplaceListing)
        .join(MarketplaceAccount)
        .filter(MarketplaceAccount.store_id == store.id, MarketplaceListing.paused_by_expiry.is_(True))
        .all()
    )
    if not pausadas:
        return 0
    cuenta = _cuenta_ml_conectada(db, store)
    if cuenta is None:
        # La cuenta se desconectó: se limpia la marca igual (no hay a qué
        # llamar) para no dejarlas trabadas.
        for listing in pausadas:
            listing.paused_by_expiry = False
        return 0

    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token
    from app.adapters.mercadolibre import MercadoLibreAdapter

    cfg = _build_ml_config(settings)
    token = await _get_valid_access_token(db, cuenta, cfg, settings.token_encryption_key)
    adapter = MercadoLibreAdapter(cfg)
    reactivadas = 0
    try:
        for listing in pausadas:
            try:
                if listing.external_listing_id:
                    await adapter.update_item_status(token, listing.external_listing_id, "active")
                    listing.status = "active"
                listing.paused_by_expiry = False
                reactivadas += 1
            except Exception as err:  # noqa: BLE001
                logger.error("No se pudo reactivar la publicacion %s: %r", listing.external_listing_id, err)
    finally:
        await adapter.aclose()
    return reactivadas


def _main() -> None:
    """Punto de entrada del cron diario (Render Cron Job):
    `python -m app.services.lifecycle`."""
    from app.db.session import SessionLocal

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = SessionLocal()
    try:
        pausador = construir_pausador(db, settings)
        res = asyncio.run(ejecutar_ciclo_de_vida(db, date.today(), pausar_publicaciones=pausador))
        logger.info("Ciclo de vida corrido: %s", res)
    finally:
        db.close()


if __name__ == "__main__":
    _main()
