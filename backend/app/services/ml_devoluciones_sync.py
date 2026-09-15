"""
Devoluciones reales de Mercado Libre (14 de septiembre de 2026), sincronizadas
cada vez que se importan las ventas. Docs oficiales verificadas: reclamos en
GET /post-purchase/v1/claims/search y su devolución en
GET /post-purchase/v2/claims/{id}/returns (status, status_money,
date_closed, resource_id = pedido). Nunca se guarda nada del comprador.

Se revisan los reclamos de tipo "return" y las mediaciones: una mediación
solo se guarda si Mercado Libre informa una devolución asociada.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreRequestError
from app.db.models import MarketplaceAccount, Order, OrderReturn
from app.services.sync_registro import DIRECCION_ML_DEVOLUCIONES, registrar_fallo, registrar_sincronizacion

logger = logging.getLogger(__name__)

TIPOS_DE_RECLAMO = ("return", "mediations")
LIMITE_POR_PAGINA = 50
MAX_PAGINAS = 10


def _fecha(valor) -> datetime | None:
    if not valor:
        return None
    try:
        fecha = datetime.fromisoformat(str(valor))
    except ValueError:
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


def fila_devolucion(devolucion: OrderReturn) -> dict:
    return {
        "reclamoId": devolucion.external_claim_id,
        "pedidoId": devolucion.external_order_id,
        "ventaImportada": devolucion.order_id is not None,
        "tipoReclamo": devolucion.claim_type,
        "estadoReclamo": devolucion.claim_status,
        "estadoDevolucion": devolucion.return_status,
        "estadoDinero": devolucion.money_status,
        "fechaReclamo": devolucion.claim_created_at.isoformat() if devolucion.claim_created_at else None,
        "fechaCierre": devolucion.return_closed_at.isoformat() if devolucion.return_closed_at else None,
    }


async def sincronizar_devoluciones(
    db: Session, account: MarketplaceAccount, adapter: MercadoLibreAdapter, access_token: str
) -> dict:
    inicio = datetime.now()
    nuevas = 0
    actualizadas = 0
    errores: list[tuple[str | None, str]] = []

    for tipo in TIPOS_DE_RECLAMO:
        offset = 0
        for _ in range(MAX_PAGINAS):
            datos = await adapter.search_claims(
                access_token, account.external_account_id, claim_type=tipo, offset=offset, limit=LIMITE_POR_PAGINA
            )
            reclamos = datos.get("data") or []
            for reclamo in reclamos:
                claim_id = str(reclamo.get("id") or "")
                if not claim_id:
                    continue
                try:
                    devolucion = await adapter.get_claim_return(access_token, claim_id)
                except MercadoLibreRequestError as fallo:
                    errores.append((None, f"No se pudo leer la devolución del reclamo {claim_id} (HTTP {fallo.status})."))
                    continue
                if devolucion is None and tipo != "return":
                    continue

                resource_id = reclamo.get("resource_id") or (devolucion or {}).get("resource_id")
                external_order_id = str(resource_id) if resource_id else None
                orden = (
                    db.query(Order).filter_by(store_id=account.store_id, channel="mercadolibre", external_order_id=external_order_id).first()
                    if external_order_id
                    else None
                )
                fila = db.query(OrderReturn).filter_by(store_id=account.store_id, external_claim_id=claim_id).first()
                if fila is None:
                    fila = OrderReturn(store_id=account.store_id, external_claim_id=claim_id)
                    db.add(fila)
                    nuevas += 1
                else:
                    actualizadas += 1
                fila.order_id = orden.id if orden is not None else None
                fila.external_order_id = external_order_id
                fila.claim_type = tipo
                fila.claim_status = reclamo.get("status")
                fila.return_status = (devolucion or {}).get("status")
                fila.money_status = (devolucion or {}).get("status_money")
                fila.claim_created_at = _fecha(reclamo.get("date_created"))
                fila.return_closed_at = _fecha((devolucion or {}).get("date_closed"))
                fila.fetched_at = inicio

            total = (datos.get("paging") or {}).get("total") or 0
            offset += LIMITE_POR_PAGINA
            if not reclamos or offset >= total:
                break

    registrar_sincronizacion(
        db, account.store_id, direccion=DIRECCION_ML_DEVOLUCIONES, productos_afectados=nuevas + actualizadas,
        inicio=inicio, errores=errores,
    )
    db.commit()
    return {"nuevas": nuevas, "actualizadas": actualizadas, "conError": len(errores)}


async def sincronizar_devoluciones_de_la_cuenta(db: Session, account: MarketplaceAccount, settings) -> dict | None:
    """Best effort: nunca levanta. None si no se pudo correr (queda en el log
    y en el historial de sincronizaciones)."""
    # Import diferido: routes.mercadolibre importa este módulo.
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token

    if account is None or account.status != "connected":
        return None
    cfg = _build_ml_config(settings)
    if not cfg.is_configured() or not settings.token_encryption_key:
        return None
    adapter = None
    try:
        access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
        adapter = MercadoLibreAdapter(cfg)
        return await sincronizar_devoluciones(db, account, adapter, access_token)
    except Exception as fallo:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudieron sincronizar las devoluciones de Mercado Libre (store_id=%s): %s", account.store_id, fallo)
        registrar_fallo(db, account.store_id, DIRECCION_ML_DEVOLUCIONES, f"No se pudieron consultar las devoluciones de Mercado Libre ({fallo.__class__.__name__}).")
        return None
    finally:
        if adapter is not None:
            await adapter.aclose()
