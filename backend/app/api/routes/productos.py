"""
Primer endpoint real de la app: conecta a WooCommerce con las credenciales
configuradas en .env, trae el catálogo completo (incluyendo variaciones de
color de productos "variable"), y devuelve el mismo tipo de reporte que ya
generaba `npm run audit` — reutilizando el adaptador y el análisis ya
probados, no una lógica nueva.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.adapters.woocommerce import (
    WooCommerceAdapter,
    WooCommerceAuthError,
    WooCommerceConfig,
    WooCommerceRequestError,
)
from app.config import get_settings
from app.domain.analysis import (
    build_productos_list,
    detect_duplicates,
    expand_variable_products,
    find_barcode_candidates,
    products_without_description,
    products_without_images,
    products_without_sku,
    products_without_stock_management,
    summarize_catalog,
)

router = APIRouter(prefix="/api/productos", tags=["productos"])


def _build_adapter() -> WooCommerceAdapter:
    settings = get_settings()
    if not settings.woocommerce_url or not settings.woocommerce_consumer_key or not settings.woocommerce_consumer_secret:
        raise HTTPException(
            status_code=500,
            detail=(
                "Faltan variables de entorno de WooCommerce (WOOCOMMERCE_URL / "
                "WOOCOMMERCE_CONSUMER_KEY / WOOCOMMERCE_CONSUMER_SECRET). "
                "Copia backend/.env.example a backend/.env y complétalo."
            ),
        )
    cfg = WooCommerceConfig(
        base_url=settings.woocommerce_url,
        consumer_key=settings.woocommerce_consumer_key,
        consumer_secret=settings.woocommerce_consumer_secret,
        auth_method=settings.woocommerce_auth_method,
    )
    return WooCommerceAdapter(cfg)


@router.get("/reporte")
async def reporte_productos() -> dict:
    """
    Reporte básico del catálogo real de WooCommerce: trae todos los
    productos, expande los "variable" en una fila por color (con SKU/stock
    reales de cada variación), y devuelve el mismo resumen de calidad de
    datos que ya calculaba el script de auditoría.
    """
    adapter = _build_adapter()
    try:
        products = await adapter.get_all_products()

        variable_products = [p for p in products if p.get("type") == "variable"]
        variations_by_product_id: dict[int, list[dict]] = {}
        for parent in variable_products:
            try:
                variations_by_product_id[parent["id"]] = await adapter.get_all_variations(parent["id"])
            except (WooCommerceAuthError, WooCommerceRequestError):
                # No se pudieron traer las variaciones de este producto puntual —
                # no abortamos todo el reporte por eso (ver expand_variable_products,
                # que deja el producto como padre en vez de perderlo).
                variations_by_product_id[parent["id"]] = []

        expanded = expand_variable_products(products, variations_by_product_id)

        summary = summarize_catalog(expanded)
        duplicates = detect_duplicates(expanded)
        barcode_candidates = find_barcode_candidates(expanded)

        return {
            "origen": get_settings().woocommerce_url,
            "productosOriginalesWooCommerce": len(products),
            "productosVariable": len(variable_products),
            "filasGeneradasPorColor": sum(1 for p in expanded if p.get("esVariante")),
            **summary,
            "posiblesDuplicados": len(duplicates),
            "candidatosCodigoBarras": len(barcode_candidates),
            "sinSkuEjemplos": [p["name"] for p in products_without_sku(expanded)[:10]],
            "sinStockGestionadoEjemplos": [p["name"] for p in products_without_stock_management(expanded)[:10]],
            "sinImagenesEjemplos": [p["name"] for p in products_without_images(expanded)[:10]],
            "sinDescripcionEjemplos": [p["name"] for p in products_without_description(expanded)[:10]],
            # Campo agregado (no rompe nada de lo anterior): lista completa,
            # una fila por producto/color, para la tabla de productos del
            # frontend. Antes de esto el endpoint solo daba conteos y hasta
            # 10 nombres de ejemplo por categoría de problema — no alcanzaba
            # para pintar una tabla real.
            "productos": build_productos_list(expanded),
        }
    except WooCommerceAuthError as err:
        raise HTTPException(status_code=502, detail=f"Autenticación con WooCommerce rechazada: {err}") from err
    except WooCommerceRequestError as err:
        raise HTTPException(status_code=502, detail=f"Error al conectar con WooCommerce: {err}") from err
    finally:
        await adapter.aclose()
