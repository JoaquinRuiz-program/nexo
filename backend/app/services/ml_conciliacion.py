"""
Conciliación de comisiones con la facturación real de Mercado Libre (14 de
septiembre de 2026). Corre al importar ventas (best effort). Buenas prácticas
de la doc oficial: hasta 60 pedidos por llamada, nunca volver a pedir un
pedido ya facturado (su facturación no cambia) y un pedido todavía sin
facturar se reintenta como mucho una vez por día.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter
from app.db.models import MarketplaceAccount, MercadoLibreCategoryFee, Order, OrderBilling, OrderItem
from app.domain.ml_billing import DIFERENCIA, SIN_FACTURAR, estado_conciliacion, resumir_cargos, tipo_de_publicacion
from app.services.sync_registro import DIRECCION_ML_CONCILIACION, registrar_fallo, registrar_sincronizacion

logger = logging.getLogger(__name__)

MAX_PEDIDOS_POR_LLAMADA = 60
MAX_PEDIDOS_POR_CORRIDA = 600


def _pedidos_a_conciliar(db: Session, store_id: int) -> list[Order]:
    inicio_de_hoy = datetime.combine(date.today(), time.min)
    ya_conciliados = {fila.order_id: fila for fila in db.query(OrderBilling).filter_by(store_id=store_id).all()}
    pendientes = []
    for orden in (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.channel == "mercadolibre", Order.status != "cancelado")
        .order_by(Order.order_date.desc())
        .all()
    ):
        fila = ya_conciliados.get(orden.id)
        if fila is None or (not fila.has_charges and fila.fetched_at < inicio_de_hoy):
            pendientes.append(orden)
    return pendientes[:MAX_PEDIDOS_POR_CORRIDA]


def _comision_estimada(db: Session, store_id: int, orden: Order, listing_type_id: str | None) -> float | None:
    """La comisión que calcula Nexo para esa venta: MercadoLibreCategoryFee de
    la categoría del producto, al tipo de publicación facturado y al precio
    EXACTO vendido. None si falta cualquier dato (nunca se inventa)."""
    if not listing_type_id:
        return None
    items = db.query(OrderItem).filter_by(order_id=orden.id).all()
    if not items:
        return None
    total = 0.0
    for item in items:
        producto = item.variant.product if item.variant is not None else None
        if producto is None or not producto.ml_category_id:
            return None
        fila = (
            db.query(MercadoLibreCategoryFee)
            .filter_by(store_id=store_id, category_id=producto.ml_category_id, listing_type_id=listing_type_id, price=float(item.unit_price))
            .first()
        )
        if fila is None:
            return None
        total += float(fila.sale_fee_amount) * item.quantity
    return round(total, 2)


async def conciliar_comisiones(db: Session, account: MarketplaceAccount, adapter: MercadoLibreAdapter, access_token: str) -> dict:
    inicio = datetime.now()
    pendientes = _pedidos_a_conciliar(db, account.store_id)
    con_facturacion = 0
    con_diferencia = 0

    for desde in range(0, len(pendientes), MAX_PEDIDOS_POR_LLAMADA):
        lote = pendientes[desde:desde + MAX_PEDIDOS_POR_LLAMADA]
        datos = await adapter.get_billing_order_details(access_token, account.external_account_id, [o.external_order_id for o in lote])
        por_pedido = {str(r.get("order_id")): r for r in (datos.get("results") or [])}
        for orden in lote:
            detalles = (por_pedido.get(orden.external_order_id) or {}).get("details") or []
            cargos = resumir_cargos(detalles)
            listing_type_id = tipo_de_publicacion(detalles)
            estimada = _comision_estimada(db, account.store_id, orden, listing_type_id) if cargos["hay_cargos"] else None
            fila = db.query(OrderBilling).filter_by(store_id=account.store_id, order_id=orden.id).first()
            if fila is None:
                fila = OrderBilling(store_id=account.store_id, order_id=orden.id)
                db.add(fila)
            fila.has_charges = cargos["hay_cargos"]
            fila.billed_sale_fee = cargos["cargo_venta"]
            fila.billed_shipping = cargos["cargo_envio"]
            fila.billed_other = cargos["otros_cargos"]
            fila.listing_type_id = listing_type_id
            fila.estimated_sale_fee = estimada
            fila.fetched_at = inicio
            if cargos["hay_cargos"]:
                con_facturacion += 1
                if estado_conciliacion(True, cargos["cargo_venta"], estimada) == DIFERENCIA:
                    con_diferencia += 1

    registrar_sincronizacion(
        db, account.store_id, direccion=DIRECCION_ML_CONCILIACION, productos_afectados=len(pendientes), inicio=inicio,
        advertencias=[(None, f"{con_diferencia} venta(s) con diferencia entre la comisión facturada y la calculada por Nexo")] if con_diferencia else None,
    )
    db.commit()
    return {"pedidosRevisados": len(pendientes), "conFacturacion": con_facturacion, "conDiferencia": con_diferencia}


async def conciliar_comisiones_de_la_cuenta(db: Session, account: MarketplaceAccount, settings) -> dict | None:
    """Best effort: nunca levanta. None si no se pudo correr (queda en el log
    y en el historial de sincronizaciones)."""
    # Import diferido: routes.mercadolibre importa este módulo.
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token

    if account is None or account.status != "connected":
        return None
    if not _pedidos_a_conciliar(db, account.store_id):
        return {"pedidosRevisados": 0, "conFacturacion": 0, "conDiferencia": 0}
    cfg = _build_ml_config(settings)
    if not cfg.is_configured() or not settings.token_encryption_key:
        return None
    adapter = None
    try:
        access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
        adapter = MercadoLibreAdapter(cfg)
        return await conciliar_comisiones(db, account, adapter, access_token)
    except Exception as fallo:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudo conciliar comisiones con la facturación de Mercado Libre (store_id=%s): %s", account.store_id, fallo)
        registrar_fallo(db, account.store_id, DIRECCION_ML_CONCILIACION, f"No se pudo consultar la facturación de Mercado Libre ({fallo.__class__.__name__}).")
        return None
    finally:
        if adapter is not None:
            await adapter.aclose()


def conciliacion_de_la_tienda(db: Session, store_id: int) -> dict:
    filas = (
        db.query(OrderBilling, Order)
        .join(Order, OrderBilling.order_id == Order.id)
        .filter(OrderBilling.store_id == store_id)
        .order_by(Order.order_date.desc(), Order.id.desc())
        .limit(200)
        .all()
    )
    pedidos = []
    cobrado = estimado = 0.0
    comparables = con_diferencia = sin_facturar = 0
    for billing, orden in filas:
        cargo_venta = float(billing.billed_sale_fee)
        estimada = float(billing.estimated_sale_fee) if billing.estimated_sale_fee is not None else None
        estado = estado_conciliacion(billing.has_charges, cargo_venta, estimada)
        if estado == SIN_FACTURAR:
            sin_facturar += 1
        elif estimada is not None:
            comparables += 1
            cobrado += cargo_venta
            estimado += estimada
            con_diferencia += 1 if estado == DIFERENCIA else 0
        pedidos.append({
            "pedidoId": orden.external_order_id,
            "fecha": orden.order_date.isoformat(),
            "comisionFacturada": cargo_venta if billing.has_charges else None,
            "envioFacturado": float(billing.billed_shipping) if billing.has_charges else None,
            "otrosCargos": float(billing.billed_other) if billing.has_charges else None,
            "comisionEstimada": estimada,
            "diferencia": round(cargo_venta - estimada, 2) if billing.has_charges and estimada is not None else None,
            "estado": estado,
        })
    return {
        "resumen": {
            # Solo ventas con facturación Y estimación de Nexo: comparar peras con peras.
            "ventasComparadas": comparables,
            "comisionFacturada": round(cobrado, 2),
            "comisionEstimada": round(estimado, 2),
            "diferencia": round(cobrado - estimado, 2),
            "ventasConDiferencia": con_diferencia,
            "ventasSinFacturar": sin_facturar,
        },
        "pedidos": pedidos,
    }
