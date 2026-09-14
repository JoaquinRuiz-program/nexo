"""
Stock de Mercado Libre de publicaciones YA creadas (14 de septiembre de 2026).

Caso real: el dueño cambiaba las unidades reservadas para Mercado Libre en
Nexo y la publicación seguía con el stock viejo — Nexo solo usaba ese número
al CREAR la publicación. Ahora, al cambiarlo, se manda también a Mercado Libre
(PUT /items/{id} available_quantity, ver
MercadoLibreAdapter.update_item_available_quantity). Best effort: un problema
acá nunca deshace el cambio ya guardado en Nexo; el resultado se informa.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.db.models import MarketplaceAccount, MarketplaceListing, MarketplaceListingVariant, ProductVariant, Store
from app.services.sync_registro import DIRECCION_ML_STOCK, registrar_fallo, registrar_sincronizacion

logger = logging.getLogger(__name__)

ESTADOS_PUBLICACION_VIVA = ("active", "paused")


def publicaciones_vivas_de(
    db: Session, store: Store, variantes: list[ProductVariant]
) -> list[tuple[MarketplaceListingVariant, MarketplaceListing, ProductVariant]]:
    """Publicaciones vivas de ESTA empresa para variantes con stock definido
    (None = "no configurado": no se manda nada, nunca se asume 0)."""
    por_id = {v.id: v for v in variantes if v.marketplace_stock is not None}
    if not por_id:
        return []
    filas = (
        db.query(MarketplaceListingVariant, MarketplaceListing)
        .join(MarketplaceListing, MarketplaceListing.id == MarketplaceListingVariant.listing_id)
        .join(MarketplaceAccount, MarketplaceAccount.id == MarketplaceListing.account_id)
        .filter(
            MarketplaceListingVariant.variant_id.in_(list(por_id)),
            MarketplaceAccount.store_id == store.id,
            MarketplaceListing.status.in_(ESTADOS_PUBLICACION_VIVA),
            MarketplaceListing.external_listing_id.isnot(None),
        )
        .all()
    )
    return [(lv, listing, por_id[lv.variant_id]) for lv, listing in filas]


async def sincronizar_stock_ml(db: Session, store: Store, variantes: list[ProductVariant], settings) -> dict | None:
    """Nunca levanta. None si no se pudo correr (sin conexión, sin
    credenciales, token inválido o error inesperado — queda en el log)."""
    # Import diferido: evita importar las rutas al cargar este módulo.
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token

    pendientes = publicaciones_vivas_de(db, store, variantes)
    if not pendientes:
        return {"publicacionesActualizadas": 0, "conError": 0}

    cuenta = db.query(MarketplaceAccount).filter_by(store_id=store.id, marketplace="mercadolibre").first()
    cfg = _build_ml_config(settings)
    if cuenta is None or cuenta.status != "connected" or not cfg.is_configured() or not settings.token_encryption_key:
        return None

    actualizadas = 0
    con_error = 0
    errores: list[tuple[int | None, str]] = []
    inicio = datetime.now()
    adapter = None
    try:
        access_token = await _get_valid_access_token(db, cuenta, cfg, settings.token_encryption_key)
        adapter = MercadoLibreAdapter(cfg)
        for listing_variante, listing, variante in pendientes:
            try:
                await adapter.update_item_available_quantity(access_token, listing.external_listing_id, variante.marketplace_stock)
            except MercadoLibreAuthError as err:
                if err.status == 401:
                    raise
                con_error += 1
                logger.error("Mercado Libre rechazó actualizar el stock de %s: %s", listing.external_listing_id, err)
                errores.append((variante.id, f"Mercado Libre no permitió actualizar el stock de {listing.external_listing_id} (HTTP {err.status})."))
            except MercadoLibreRequestError as err:
                con_error += 1
                logger.error("No se pudo actualizar el stock de %s en Mercado Libre: %s", listing.external_listing_id, err)
                mensaje_ml = str((err.response_body or {}).get("message") or "")[:200]
                errores.append((variante.id, f"Mercado Libre no aceptó el stock de {listing.external_listing_id} (HTTP {err.status}){': ' + mensaje_ml if mensaje_ml else ''}."))
            else:
                listing_variante.stock_quantity = variante.marketplace_stock
                listing_variante.last_synced_at = datetime.now()
                actualizadas += 1
        registrar_sincronizacion(db, store.id, direccion=DIRECCION_ML_STOCK, productos_afectados=actualizadas, inicio=inicio, errores=errores)
        db.commit()
    except Exception as err:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudo sincronizar el stock con Mercado Libre (store_id=%s): %s", store.id, err)
        registrar_fallo(db, store.id, DIRECCION_ML_STOCK, f"No se pudo actualizar el stock en Mercado Libre ({err.__class__.__name__}).")
        return None
    finally:
        if adapter is not None:
            await adapter.aclose()
    return {"publicacionesActualizadas": actualizadas, "conError": con_error}
