"""
Sincroniza el costo de envío REAL de Mercado Libre de las publicaciones de
una empresa (14 de septiembre de 2026). La interpretación de la API vive en
app/domain/ml_shipping.py; acá solo se orquesta (adaptador + base).

Se dispara al conectar Mercado Libre, al importar ventas, al actualizar
comisiones y apenas se crea una publicación. Siempre "best effort": un
problema acá nunca rompe el flujo que la llamó (ver
sincronizar_costos_envio_de_la_cuenta).
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.db.models import MarketplaceAccount, MarketplaceListing
from app.domain.ml_shipping import (
    MOTIVO_ITEM_INEXISTENTE,
    MOTIVO_SIN_ACCESO,
    MOTIVO_SIN_COSTO_VALIDO,
    CostoEnvioML,
    interpretar_costo_envio,
    motivo_sin_consulta_de_costo,
    no_disponible,
)

logger = logging.getLogger(__name__)

# Una publicación cerrada no se vende más: no tiene sentido consultarla.
ESTADOS_A_SINCRONIZAR = ("active", "paused")

OBTENIDO = "obtenido"
NO_DISPONIBLE = "no_disponible"
ERROR_TEMPORAL = "error_temporal"


def publicaciones_a_sincronizar(db: Session, account: MarketplaceAccount) -> list[MarketplaceListing]:
    return (
        db.query(MarketplaceListing)
        .filter(
            MarketplaceListing.account_id == account.id,
            MarketplaceListing.external_listing_id.isnot(None),
            MarketplaceListing.status.in_(ESTADOS_A_SINCRONIZAR),
        )
        .all()
    )


def _aplicar(listing: MarketplaceListing, resultado: CostoEnvioML, ahora: datetime) -> None:
    listing.shipping_cost = resultado.costo
    listing.shipping_currency_id = resultado.moneda
    listing.shipping_mode = resultado.modo
    listing.shipping_logistic_type = resultado.logistica
    listing.shipping_free_shipping = resultado.envio_gratis
    listing.shipping_cost_unavailable_reason = resultado.motivo_no_disponible
    listing.shipping_synced_at = ahora


async def actualizar_costo_envio(
    account: MarketplaceAccount, adapter: MercadoLibreAdapter, access_token: str, listing: MarketplaceListing
) -> str:
    """Consulta y guarda (sin commit) el envío de UNA publicación. Un 401 sube
    (es el token de la cuenta, no la publicación). Un error de red/5xx no
    toca lo guardado: no es una respuesta de Mercado Libre sobre el costo."""
    item = None
    try:
        item = await adapter.get_item(access_token, listing.external_listing_id)
    except MercadoLibreAuthError as err:
        if err.status == 401:
            raise
        resultado = no_disponible(MOTIVO_SIN_ACCESO)
    except MercadoLibreRequestError as err:
        if err.status != 404:
            return ERROR_TEMPORAL
        resultado = no_disponible(MOTIVO_ITEM_INEXISTENTE)
    else:
        # El estado local puede estar viejo (caso real: Nexo decía "active" y
        # Mercado Libre "closed"). Mismo criterio que
        # publicaciones.py::_consultar_estado_real_y_sincronizar.
        if item.get("status") and listing.status != item["status"]:
            listing.status = item["status"]
        motivo = motivo_sin_consulta_de_costo(item)
        if motivo is not None:
            resultado = no_disponible(motivo, item)
        elif not account.external_account_id:
            resultado = no_disponible(MOTIVO_SIN_COSTO_VALIDO, item)
        else:
            try:
                respuesta = await adapter.get_seller_shipping_cost(access_token, account.external_account_id, listing.external_listing_id)
            except MercadoLibreAuthError as err:
                if err.status == 401:
                    raise
                resultado = no_disponible(MOTIVO_SIN_COSTO_VALIDO, item)
            except MercadoLibreRequestError as err:
                if err.status is None or err.status >= 500:
                    return ERROR_TEMPORAL
                resultado = no_disponible(MOTIVO_SIN_COSTO_VALIDO, item)
            else:
                resultado = interpretar_costo_envio(item, respuesta)

    _aplicar(listing, resultado, datetime.now())
    return OBTENIDO if resultado.costo is not None else NO_DISPONIBLE


async def sincronizar_costos_envio(
    db: Session,
    account: MarketplaceAccount,
    adapter: MercadoLibreAdapter,
    access_token: str,
    listings: list[MarketplaceListing] | None = None,
) -> dict:
    listings = publicaciones_a_sincronizar(db, account) if listings is None else listings
    conteo = {OBTENIDO: 0, NO_DISPONIBLE: 0, ERROR_TEMPORAL: 0}
    for listing in listings:
        if not listing.external_listing_id:
            continue
        conteo[await actualizar_costo_envio(account, adapter, access_token, listing)] += 1
    db.commit()
    return {
        "publicacionesRevisadas": sum(conteo.values()),
        "conCostoReal": conteo[OBTENIDO],
        "sinCostoDisponible": conteo[NO_DISPONIBLE],
        "conErrorTemporal": conteo[ERROR_TEMPORAL],
    }


async def sincronizar_costos_envio_de_la_cuenta(
    db: Session, account: MarketplaceAccount, settings, listings: list[MarketplaceListing] | None = None
) -> dict | None:
    """Versión "best effort" para enchufar en otros flujos (conectar, importar
    ventas, comisiones, publicar): nunca levanta. None si no se pudo correr
    (sin credenciales, token inválido, error inesperado — queda en el log)."""
    # Import diferido: routes.mercadolibre importa este módulo.
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token

    if account is None or account.status != "connected":
        return None
    listings = publicaciones_a_sincronizar(db, account) if listings is None else listings
    if not listings:
        return {"publicacionesRevisadas": 0, "conCostoReal": 0, "sinCostoDisponible": 0, "conErrorTemporal": 0}

    cfg = _build_ml_config(settings)
    if not cfg.is_configured() or not settings.token_encryption_key:
        return None
    adapter = None
    try:
        access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
        adapter = MercadoLibreAdapter(cfg)
        return await sincronizar_costos_envio(db, account, adapter, access_token, listings)
    except Exception as err:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudo sincronizar el costo de envío de Mercado Libre (store_id=%s): %s", account.store_id, err)
        return None
    finally:
        if adapter is not None:
            await adapter.aclose()
