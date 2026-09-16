"""
Eliminar la cuenta de un cliente desde la aplicación (15 de septiembre de
2026, pedido del dueño). Borra para siempre al usuario y TODO lo de sus
empresas en Nexo: catálogo, imágenes (también los archivos en disco),
configuración, ventas importadas, devoluciones, facturación, integraciones,
suscripción, soporte e historial de sincronizaciones.

Antes de borrar nada se cancela el cobro mensual en Mercado Pago: si eso
falla, la cuenta NO se elimina (Mercado Pago seguiría cobrando una tarjeta
de una cuenta que ya no existe).

Las publicaciones en Mercado Libre NO se cierran: son del vendedor en su
cuenta de Mercado Libre y siguen ahí.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    AdminActionLog,
    AuthSession,
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingVariant,
    MercadoLibreCategoryFee,
    MercadoLibreShippingEstimate,
    Order,
    OrderBilling,
    OrderInvoice,
    OrderItem,
    OrderReturn,
    PasswordResetToken,
    Product,
    ProductImage,
    ProductVariant,
    StockMovement,
    Store,
    StoreSettings,
    Subscription,
    SupportTicket,
    SyncJob,
    SyncLog,
    User,
    UserPreferences,
    WooCommerceProduct,
    WooCommerceVariation,
)

logger = logging.getLogger(__name__)


async def _cancelar_preapproval(preapproval_id: str, settings) -> None:
    """Mismo flujo que POST /api/pagos/cancelar."""
    from app.adapters.mercadopago import MercadoPagoAdapter, MercadoPagoAuthError, MercadoPagoRequestError
    from app.api.routes.pagos import _build_mp_config, _require_configured

    cfg = _build_mp_config(settings)
    _require_configured(cfg, settings)
    adapter = MercadoPagoAdapter(cfg)
    try:
        await adapter.cancelar_preapproval(preapproval_id)
    except (MercadoPagoAuthError, MercadoPagoRequestError) as err:
        logger.error("No se pudo cancelar el preapproval %s al eliminar una cuenta: %s", preapproval_id, err)
        raise HTTPException(
            status_code=502,
            detail=(
                "No pudimos cancelar tu suscripción en Mercado Pago, así que no eliminamos la cuenta "
                "(seguiría cobrándose). Intenta de nuevo más tarde o escríbenos a soporte."
            ),
        ) from err
    finally:
        await adapter.aclose()


async def cancelar_cobros_recurrentes(db: Session, usuario: User, settings) -> None:
    for store in db.query(Store).filter_by(owner_user_id=usuario.id).all():
        sub = store.subscription
        if sub is None or not sub.mercadopago_preapproval_id or sub.billing_cycle != "mensual" or sub.status == "canceled":
            continue
        await _cancelar_preapproval(sub.mercadopago_preapproval_id, settings)


def eliminar_datos_de_la_cuenta(db: Session, usuario: User, uploads_dir: Path) -> None:
    store_ids = [sid for (sid,) in db.query(Store.id).filter(Store.owner_user_id == usuario.id).all()]

    def ids(columna, condicion) -> list[int]:
        return [valor for (valor,) in db.query(columna).filter(condicion).all()]

    def borrar(modelo, condicion) -> None:
        db.query(modelo).filter(condicion).delete(synchronize_session=False)

    if store_ids:
        product_ids = ids(Product.id, Product.store_id.in_(store_ids))
        variant_ids = ids(ProductVariant.id, ProductVariant.store_id.in_(store_ids))
        order_ids = ids(Order.id, Order.store_id.in_(store_ids))
        account_ids = ids(MarketplaceAccount.id, MarketplaceAccount.store_id.in_(store_ids))
        job_ids = ids(SyncJob.id, SyncJob.store_id.in_(store_ids))
        listing_ids = ids(
            MarketplaceListing.id,
            MarketplaceListing.account_id.in_(account_ids) | MarketplaceListing.product_id.in_(product_ids),
        )

        # Orden: primero lo que apunta a otras filas, después lo apuntado.
        borrar(SyncLog, SyncLog.sync_job_id.in_(job_ids))
        borrar(SyncJob, SyncJob.id.in_(job_ids))
        borrar(StockMovement, StockMovement.variant_id.in_(variant_ids))
        borrar(MarketplaceListingVariant, MarketplaceListingVariant.listing_id.in_(listing_ids) | MarketplaceListingVariant.variant_id.in_(variant_ids))
        borrar(MarketplaceListing, MarketplaceListing.id.in_(listing_ids))
        borrar(OrderBilling, OrderBilling.store_id.in_(store_ids))
        borrar(OrderInvoice, OrderInvoice.store_id.in_(store_ids))
        borrar(OrderReturn, OrderReturn.store_id.in_(store_ids))
        borrar(OrderItem, OrderItem.order_id.in_(order_ids))
        borrar(Order, Order.id.in_(order_ids))
        borrar(MercadoLibreCategoryFee, MercadoLibreCategoryFee.store_id.in_(store_ids))
        borrar(MercadoLibreShippingEstimate, MercadoLibreShippingEstimate.store_id.in_(store_ids))
        borrar(MarketplaceAccount, MarketplaceAccount.id.in_(account_ids))
        borrar(WooCommerceVariation, WooCommerceVariation.store_id.in_(store_ids))
        borrar(WooCommerceProduct, WooCommerceProduct.store_id.in_(store_ids))
        borrar(ProductImage, ProductImage.product_id.in_(product_ids))
        borrar(ProductVariant, ProductVariant.id.in_(variant_ids))
        borrar(Product, Product.id.in_(product_ids))
        borrar(ChannelCostSettings, ChannelCostSettings.store_id.in_(store_ids))
        borrar(SupportTicket, SupportTicket.store_id.in_(store_ids))
        borrar(Subscription, Subscription.store_id.in_(store_ids))
        borrar(StoreSettings, StoreSettings.store_id.in_(store_ids))
        # El registro de acciones de administradores se conserva, sin la empresa.
        db.query(AdminActionLog).filter(AdminActionLog.store_id.in_(store_ids)).update({AdminActionLog.store_id: None}, synchronize_session=False)
        # Un admin que estaba viendo esta empresa en modo soporte sale de ese modo.
        db.query(AuthSession).filter(AuthSession.viewing_store_id.in_(store_ids)).update({AuthSession.viewing_store_id: None}, synchronize_session=False)
        db.query(AuthSession).filter(AuthSession.active_store_id.in_(store_ids), AuthSession.user_id != usuario.id).update(
            {AuthSession.active_store_id: None}, synchronize_session=False
        )

    borrar(SupportTicket, SupportTicket.user_id == usuario.id)
    borrar(AuthSession, AuthSession.user_id == usuario.id)
    borrar(Store, Store.id.in_(store_ids))
    borrar(PasswordResetToken, PasswordResetToken.user_id == usuario.id)
    borrar(UserPreferences, UserPreferences.user_id == usuario.id)
    borrar(User, User.id == usuario.id)
    db.commit()

    for store_id in store_ids:
        shutil.rmtree(uploads_dir / "product_images" / str(store_id), ignore_errors=True)
