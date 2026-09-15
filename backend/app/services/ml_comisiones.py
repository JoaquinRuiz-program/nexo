"""
Comisión REAL de Mercado Libre por producto (14 de septiembre de 2026, pedido
del dueño: "que siempre sean comisiones reales"). Antes solo se calculaba al
apretar "Actualizar comisiones reales"; ahora también corre sola, en segundo
plano, al importar el catálogo (Excel/CSV y Google Sheets) y al conectar
Mercado Libre. La comisión manual de Configuración queda solo como respaldo,
marcada como tal, para un producto cuya comisión real Mercado Libre todavía no
informó.

Categoría por producto: se predice UNA vez por título (GET /domain_discovery,
público) y se guarda en Product.ml_category_id. Comisión por (categoría,
precio exacto): GET /listing_prices, cacheada en MercadoLibreCategoryFee — un
par ya cacheado no se vuelve a pedir, así que correrlo de nuevo solo consulta
lo nuevo o lo que cambió de precio.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.db.models import MarketplaceAccount, MercadoLibreCategoryFee, Product
from app.domain.ml_fees import LISTING_TYPE_IDS, parse_listing_fees

logger = logging.getLogger(__name__)


async def actualizar_comisiones_reales(
    db: Session, store_id: int, adapter: MercadoLibreAdapter, access_token: str, site_id: str
) -> dict:
    """Levanta MercadoLibreAuthError si Mercado Libre rechaza /listing_prices
    (la app sin el permiso "Publicación y sincronización"): quien llama decide
    qué responder."""
    productos_con_precio = [
        p for p in db.query(Product).filter_by(store_id=store_id).all()
        if any(v.price is not None for v in p.variants)
    ]

    productos_sin_categoria: list[str] = []
    for producto in productos_con_precio:
        if producto.ml_category_id:
            continue
        try:
            prediccion = await adapter.predict_category(producto.name, site_id)
        except (MercadoLibreAuthError, MercadoLibreRequestError):
            prediccion = None
        if prediccion is None:
            productos_sin_categoria.append(producto.name)
            continue
        producto.ml_category_id = prediccion["categoryId"]
        producto.ml_category_name = prediccion["categoryName"]
    db.commit()

    # (categoría, precio) únicos a consultar — un mismo par se pide una sola
    # vez aunque varios productos/variantes lo compartan.
    pares_a_pedir: set[tuple[str, float]] = set()
    for producto in productos_con_precio:
        if not producto.ml_category_id:
            continue
        for variante in producto.variants:
            if variante.price is None:
                continue
            par = (producto.ml_category_id, float(variante.price))
            tipos_cacheados = {
                fila.listing_type_id
                for fila in db.query(MercadoLibreCategoryFee).filter_by(store_id=store_id, category_id=par[0], price=par[1]).all()
            }
            if not set(LISTING_TYPE_IDS.values()).issubset(tipos_cacheados):
                pares_a_pedir.add(par)

    combinaciones_actualizadas = 0
    combinaciones_con_error: list[str] = []
    ahora = datetime.now()
    for category_id, precio in pares_a_pedir:
        try:
            raw = await adapter.get_listing_fees(access_token, site_id, category_id, precio)
        except MercadoLibreRequestError:
            combinaciones_con_error.append(f"{category_id} @ ${precio:,.0f}")
            continue

        for clave, fee in parse_listing_fees(raw).items():
            listing_type_id = LISTING_TYPE_IDS[clave]
            fila = (
                db.query(MercadoLibreCategoryFee)
                .filter_by(store_id=store_id, category_id=category_id, listing_type_id=listing_type_id, price=precio)
                .first()
            )
            if fila is None:
                fila = MercadoLibreCategoryFee(store_id=store_id, category_id=category_id, listing_type_id=listing_type_id, price=precio)
                db.add(fila)
            fila.percentage_fee = fee.percentage_fee
            fila.fixed_fee = fee.fixed_fee
            fila.sale_fee_amount = fee.sale_fee_amount
            fila.fetched_at = ahora
        combinaciones_actualizadas += 1
    db.commit()

    return {
        "productosRevisados": len(productos_con_precio),
        "productosSinCategoriaDetectada": productos_sin_categoria,
        "combinacionesComisionActualizadas": combinaciones_actualizadas,
        "combinacionesConError": combinaciones_con_error,
    }


async def actualizar_comisiones_reales_de_la_tienda(db: Session, store_id: int, settings) -> dict | None:
    """Versión "best effort" (nunca levanta). None si no se pudo correr: sin
    Mercado Libre conectado, sin credenciales o por un error que queda en el log."""
    # Import diferido: routes.mercadolibre importa este módulo.
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token

    account = db.query(MarketplaceAccount).filter_by(store_id=store_id, marketplace="mercadolibre").first()
    if account is None or account.status != "connected":
        return None
    cfg = _build_ml_config(settings)
    if not cfg.is_configured() or not settings.token_encryption_key:
        return None
    adapter = None
    try:
        access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
        adapter = MercadoLibreAdapter(cfg)
        return await actualizar_comisiones_reales(db, store_id, adapter, access_token, account.external_account_site_id or "MLC")
    except Exception as err:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudieron actualizar las comisiones reales de Mercado Libre (store_id=%s): %s", store_id, err)
        return None
    finally:
        if adapter is not None:
            await adapter.aclose()


async def actualizar_comisiones_en_segundo_plano(bind, store_id: int, settings) -> None:
    """Para BackgroundTasks de FastAPI: abre su propia sesión sobre el MISMO
    motor de base de la request que la programó (la sesión de la request ya
    se cerró cuando esto corre)."""
    db = Session(bind=bind)
    try:
        resultado = await actualizar_comisiones_reales_de_la_tienda(db, store_id, settings)
        if resultado is not None:
            logger.info("Comisiones reales actualizadas en segundo plano (store_id=%s): %s", store_id, resultado)
    finally:
        db.close()
