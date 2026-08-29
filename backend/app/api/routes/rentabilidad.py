"""
GET /api/rentabilidad — el reporte que pidió el dueño el 22 de agosto de
2026: no solo qué se vende, sino qué CONVIENE vender, y por qué canal.

Usa domain/profitability.py para todos los cálculos — este archivo solo
arma las filas (join Product + ProductVariant + ChannelCostSettings) y las
ordena. Nunca calcula un margen acá directamente.

Reglas heredadas de profitability.py (ver ese archivo para el detalle):
- Producto sin costo cargado -> sin margen, en ningún canal.
- Canal sin costos configurados -> sin margen neto para ese canal (no se
  asume ninguna comisión).

La respuesta va envuelta en "resumen" + "productos" (24 de agosto de 2026,
a pedido del dueño): mientras no haya costos ni canales configurados, el
sistema no debe mostrar números — debe decir claramente "todavía no hay
datos". `resumen.productosConCosto === 0` es exactamente la condición que
el frontend (cuando exista esa pantalla) necesita para pintar el aviso
"⚠️ Aún no hay costos de compra cargados" en vez de una tabla vacía o, peor,
una tabla con márgenes inventados.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.db.models import ChannelCostSettings, MercadoLibreCategoryFee, Product, ProductVariant, Store
from app.db.session import get_db
from app.domain.ml_fees import LISTING_TYPE_IDS
from app.domain.profitability import ChannelCosts, gross_margin, gross_margin_pct, net_margin, net_margin_pct

router = APIRouter(prefix="/api/rentabilidad", tags=["rentabilidad"])

# Canal implícito: la tienda física no cobra comisión ni envío sobre sus
# propias ventas (ver channel_costs.py) — no necesita una fila en la BD.
CHANNEL_MERCADO_LIBRE = "mercadolibre"

_LISTING_TYPE_ID_A_CLAVE = {v: k for k, v in LISTING_TYPE_IDS.items()}


def _comision_ml_real(db: Session, store_id: int, producto: Product, precio: float | None, costos_manual: ChannelCosts) -> dict | None:
    """Comisión REAL de Mercado Libre (Clásica/Premium) para este producto a
    este precio exacto, si ya se consultó antes (ver POST
    /api/mercadolibre/comisiones/recalcular — acá nunca se llama a la API
    de Mercado Libre, solo se lee la caché). None si el producto todavía no
    tiene categoría de ML detectada, o no hay ningún dato cacheado para su
    precio actual — nunca se inventa ni se aproxima con otro precio."""
    if not producto.ml_category_id or precio is None:
        return None
    filas = (
        db.query(MercadoLibreCategoryFee)
        .filter_by(store_id=store_id, category_id=producto.ml_category_id, price=precio)
        .all()
    )
    if not filas:
        return None

    resultado: dict = {}
    for fila in filas:
        clave = _LISTING_TYPE_ID_A_CLAVE.get(fila.listing_type_id)
        if clave is None:
            continue
        costos_reales = ChannelCosts(
            commission_pct=float(fila.percentage_fee),
            shipping_cost=costos_manual.shipping_cost,
            other_fixed_cost=(costos_manual.other_fixed_cost or 0.0) + float(fila.fixed_fee),
        )
        costo_producto = float(producto.variants[0].cost_price) if producto.variants and producto.variants[0].cost_price is not None else None
        resultado[clave] = {
            "nombre": fila.listing_type_id,
            "comisionPct": float(fila.percentage_fee),
            "comisionFija": float(fila.fixed_fee),
            "comisionTotal": float(fila.sale_fee_amount),
            "margenClp": net_margin(precio, costo_producto, costos_reales),
            "margenPct": net_margin_pct(precio, costo_producto, costos_reales),
        }
    return resultado or None


def _fila(db: Session, store_id: int, producto: Product, variante: ProductVariant, costos_ml: ChannelCosts, ml_configurado: bool) -> dict:
    precio = float(variante.price) if variante.price is not None else None
    costo = float(variante.cost_price) if variante.cost_price is not None else None

    return {
        "id": variante.id,
        "sku": variante.variant_sku or "",
        "nombre": f"{producto.name} - {variante.variant_label}" if variante.variant_label else producto.name,
        "precio": precio,
        "costo": costo,
        "tieneCosto": costo is not None,
        # Tope de unidades reservadas para Mercado Libre — lo necesita
        # domain/catalog_selection.py para saber si hay algo que publicar,
        # sin confundirlo con el stock físico (ver domain/marketplace_stock.py).
        "marketplaceStock": variante.marketplace_stock,
        "margenTiendaClp": gross_margin(precio, costo),
        "margenTiendaPct": gross_margin_pct(precio, costo),
        "mercadoLibreConfigurado": ml_configurado,
        "margenMercadoLibreClp": net_margin(precio, costo, costos_ml),
        "margenMercadoLibrePct": net_margin_pct(precio, costo, costos_ml),
        # Comisión REAL de Mercado Libre (29 de agosto de 2026, a pedido del
        # dueño: "la comisión varía por producto") — Clásica y Premium en
        # paralelo, para decidir cuál conviene. None hasta que se corra
        # POST /api/mercadolibre/comisiones/recalcular; nunca se calcula acá
        # con un valor estimado.
        "comisionMlReal": _comision_ml_real(db, store_id, producto, precio, costos_ml),
        "mlCategoriaId": producto.ml_category_id,
        "mlCategoriaNombre": producto.ml_category_name,
    }


def build_profitability_rows(db: Session, store: Store) -> tuple[list[dict], bool]:
    """Arma las mismas filas que devuelve GET /api/rentabilidad — factorizado
    acá para que app/api/routes/seleccion.py y publicaciones.py las reusen
    sin duplicar la consulta ni el cálculo de márgenes.

    `store` viene SIEMPRE de la sesión autenticada (ver
    app/api/deps.py:get_current_store) — nunca se vuelve a resolver "la
    primera tienda que exista" acá adentro. Con auth obligatorio en todos
    los endpoints que llaman a esto, no existe un caso real de "request
    válida sin tienda" — un usuario logueado siempre tiene una (ver
    POST /api/auth/registro)."""
    config_ml = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel=CHANNEL_MERCADO_LIBRE).first()
    costos_ml = ChannelCosts(
        commission_pct=float(config_ml.commission_pct) if config_ml and config_ml.commission_pct is not None else None,
        shipping_cost=float(config_ml.shipping_cost) if config_ml and config_ml.shipping_cost is not None else None,
        other_fixed_cost=float(config_ml.other_fixed_cost) if config_ml and config_ml.other_fixed_cost is not None else None,
    )
    ml_configurado = costos_ml.is_configured()

    productos = db.query(Product).filter_by(store_id=store.id).order_by(Product.name).all()
    filas = [
        _fila(db, store.id, producto, variante, costos_ml, ml_configurado)
        for producto in productos
        for variante in producto.variants
    ]
    return filas, ml_configurado


@router.get("")
def reporte_rentabilidad(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    filas, ml_configurado = build_profitability_rows(db, store)

    # Prioriza lo que más conviene (mayor margen en tienda) primero; lo que
    # todavía no tiene costo cargado va al final, no se mezcla ordenado como
    # si valiera $0 (eso lo haría parecer lo menos rentable, y no lo sabemos).
    con_costo = sorted((f for f in filas if f["tieneCosto"]), key=lambda f: f["margenTiendaClp"], reverse=True)
    sin_costo = [f for f in filas if not f["tieneCosto"]]

    return {
        "resumen": {
            "totalProductos": len(filas),
            "productosConCosto": len(con_costo),
            "canalesConfigurados": [CHANNEL_MERCADO_LIBRE] if ml_configurado else [],
        },
        "productos": con_costo + sin_costo,
    }
