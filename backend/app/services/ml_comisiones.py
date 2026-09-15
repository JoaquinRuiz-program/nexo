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
import random
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.db.models import MarketplaceAccount, MercadoLibreCategoryFee, Product
from app.domain.ml_fees import LISTING_TYPE_IDS, parse_listing_fees

logger = logging.getLogger(__name__)

# 15 de septiembre de 2026 (QA fase 2): tope de predicciones de categoría por
# corrida. Con 10.000 productos cada importación lanzaba 10.000 llamadas
# seguidas a Mercado Libre (horas de trabajo, riesgo de bloqueo por exceso de
# pedidos) y un reinicio del servidor quedaba esperando a que terminaran. Los
# productos que queden sin categoría se predicen en la siguiente corrida.
MAX_PREDICCIONES_POR_CORRIDA = 200


async def actualizar_comisiones_reales(
    db: Session, store_id: int, adapter: MercadoLibreAdapter, access_token: str, site_id: str
) -> dict:
    """Levanta MercadoLibreAuthError si Mercado Libre rechaza /listing_prices
    (la app sin el permiso "Publicación y sincronización"): quien llama decide
    qué responder.

    15 de septiembre de 2026 (QA fase 2): nunca mantiene tomada una conexión de
    la base mientras espera a Mercado Libre. Antes, con un catálogo grande, cada
    importación dejaba una tarea haciendo miles de llamadas con la conexión
    abierta; unas pocas importaciones agotaban el pool y el backend dejaba de
    responder a TODAS las empresas."""
    productos_con_precio = [
        (p.id, p.name, p.ml_category_id, [float(v.price) for v in p.variants if v.price is not None])
        for p in db.query(Product).filter_by(store_id=store_id).all()
    ]
    productos_con_precio = [p for p in productos_con_precio if p[3]]
    db.rollback()  # libera la conexión antes de llamar a Mercado Libre

    productos_sin_categoria: list[str] = []
    categorias: dict[int, str] = {}
    predicciones: dict[int, dict] = {}
    # Orden al azar: con el tope por corrida, los productos cuya categoría nunca
    # se puede predecir no bloquean para siempre a los demás (QA fase 2).
    for producto_id, nombre, categoria, _precios in random.sample(productos_con_precio, len(productos_con_precio)):
        if categoria:
            categorias[producto_id] = categoria
            continue
        if len(predicciones) + len(productos_sin_categoria) >= MAX_PREDICCIONES_POR_CORRIDA:
            continue
        try:
            prediccion = await adapter.predict_category(nombre, site_id)
        except (MercadoLibreAuthError, MercadoLibreRequestError):
            prediccion = None
        if prediccion is None:
            productos_sin_categoria.append(nombre)
            continue
        predicciones[producto_id] = prediccion
        categorias[producto_id] = prediccion["categoryId"]
    _guardar_categorias(db, store_id, predicciones)

    # (categoría, precio) únicos a consultar — un mismo par se pide una sola
    # vez aunque varios productos/variantes lo compartan.
    cacheados: dict[tuple[str, float], set[str]] = {}
    for fila in db.query(MercadoLibreCategoryFee).filter_by(store_id=store_id).all():
        cacheados.setdefault((fila.category_id, float(fila.price)), set()).add(fila.listing_type_id)
    db.rollback()
    pares_a_pedir: set[tuple[str, float]] = set()
    for producto_id, _nombre, _categoria, precios in productos_con_precio:
        categoria = categorias.get(producto_id)
        if not categoria:
            continue
        for precio in precios:
            if not set(LISTING_TYPE_IDS.values()).issubset(cacheados.get((categoria, precio), set())):
                pares_a_pedir.add((categoria, precio))

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
        db.commit()  # libera la conexión antes de la siguiente llamada
        combinaciones_actualizadas += 1

    return {
        "productosRevisados": len(productos_con_precio),
        "productosSinCategoriaDetectada": productos_sin_categoria,
        "combinacionesComisionActualizadas": combinaciones_actualizadas,
        "combinacionesConError": combinaciones_con_error,
    }


def _guardar_categorias(db: Session, store_id: int, predicciones: dict[int, dict]) -> None:
    for producto_id, prediccion in predicciones.items():
        db.query(Product).filter_by(id=producto_id, store_id=store_id).update(
            {Product.ml_category_id: prediccion["categoryId"], Product.ml_category_name: prediccion["categoryName"]},
            synchronize_session=False,
        )
    db.commit()


SITIO_POR_DEFECTO = "MLC"  # Nexo opera en Mercado Libre Chile


async def _solo_predecir_categorias(db: Session, store_id: int, settings) -> dict | None:
    """Predice la categoría de Mercado Libre de los productos que todavía no
    la tienen, sin cuenta conectada (GET /domain_discovery es público). No
    consulta comisiones: eso necesita el token de la cuenta. Best effort.
    Igual que arriba: nunca con la conexión de la base tomada mientras espera."""
    from app.api.routes.mercadolibre import _build_ml_config

    # Al azar entre los que siguen sin categoría: si algunos nunca se pueden
    # predecir, no bloquean para siempre a los demás (QA fase 2, 15/09/2026).
    pendientes = db.query(Product.id, Product.name).filter(Product.store_id == store_id, Product.ml_category_id.is_(None)).all()
    productos = random.sample(pendientes, min(len(pendientes), MAX_PREDICCIONES_POR_CORRIDA))
    db.rollback()  # libera la conexión antes de llamar a Mercado Libre
    if not productos:
        return {"productosConCategoriaNueva": 0, "productosSinCategoriaDetectada": []}
    adapter = MercadoLibreAdapter(_build_ml_config(settings))
    try:
        predicciones: dict[int, dict] = {}
        sin_categoria: list[str] = []
        for producto_id, nombre in productos:
            try:
                prediccion = await adapter.predict_category(nombre, SITIO_POR_DEFECTO)
            except (MercadoLibreAuthError, MercadoLibreRequestError):
                prediccion = None
            if prediccion is None:
                sin_categoria.append(nombre)
                continue
            predicciones[producto_id] = prediccion
        _guardar_categorias(db, store_id, predicciones)
        return {"productosConCategoriaNueva": len(predicciones), "productosSinCategoriaDetectada": sin_categoria}
    except Exception as err:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudieron predecir categorías de Mercado Libre (store_id=%s): %s", store_id, err)
        return None
    finally:
        await adapter.aclose()


async def actualizar_comisiones_reales_de_la_tienda(db: Session, store_id: int, settings) -> dict | None:
    """Versión "best effort" (nunca levanta). None si no se pudo correr: sin
    Mercado Libre conectado, sin credenciales o por un error que queda en el log."""
    # Import diferido: routes.mercadolibre importa este módulo.
    from app.api.routes.mercadolibre import _build_ml_config, _get_valid_access_token

    account = db.query(MarketplaceAccount).filter_by(store_id=store_id, marketplace="mercadolibre").first()
    if account is None or account.status != "connected":
        # 15 de septiembre de 2026 — revisión por perfil: sin cuenta conectada
        # igual se predice la categoría (endpoint público), así al conectar
        # Mercado Libre la comisión real queda lista enseguida.
        return await _solo_predecir_categorias(db, store_id, settings)
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
    se cerró cuando esto corre).

    15 de septiembre de 2026 (QA fase 2): una sola tarea por empresa a la vez.
    Importar varias veces seguidas apilaba tareas que recorrían el mismo
    catálogo en paralelo; si ya hay una en curso, la nueva no hace nada (la que
    corre ya toma los productos recién importados que siguen sin categoría)."""
    if store_id in _tiendas_en_curso:
        logger.info("Ya hay una actualización de comisiones en curso (store_id=%s): se omite la nueva", store_id)
        return
    _tiendas_en_curso.add(store_id)
    db = Session(bind=bind)
    try:
        resultado = await actualizar_comisiones_reales_de_la_tienda(db, store_id, settings)
        if resultado is not None:
            logger.info("Comisiones reales actualizadas en segundo plano (store_id=%s): %s", store_id, resultado)
    finally:
        db.close()
        _tiendas_en_curso.discard(store_id)


_tiendas_en_curso: set[int] = set()
