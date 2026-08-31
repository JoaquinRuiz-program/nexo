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
from app.domain.ml_fees import LISTING_TYPE_IDS, ListingFee, elegir_comision_principal
from app.domain.profitability import ChannelCosts, gross_margin, gross_margin_pct, net_margin, net_margin_pct

router = APIRouter(prefix="/api/rentabilidad", tags=["rentabilidad"])

# Canal implícito: la tienda física no cobra comisión ni envío sobre sus
# propias ventas (ver channel_costs.py) — no necesita una fila en la BD.
CHANNEL_MERCADO_LIBRE = "mercadolibre"

_LISTING_TYPE_ID_A_CLAVE = {v: k for k, v in LISTING_TYPE_IDS.items()}


def comisiones_ml_cacheadas(db: Session, store_id: int, producto: Product, precio: float | None) -> dict[str, ListingFee]:
    """31 de agosto de 2026 — único lookup a MercadoLibreCategoryFee de todo
    este archivo (store_id + category_id + price EXACTO, nunca aproximado
    ni interpolado): tanto _comision_ml_real (comparación Clásica/Premium,
    informativa) como resolver_costos_ml (single source of truth para
    calcular) parten de este mismo dict — antes cada una hacía su propia
    consulta idéntica. {} si el producto no tiene categoría de ML detectada
    o no hay nada cacheado para su precio actual — nunca se inventa."""
    if not producto.ml_category_id or precio is None:
        return {}
    filas = (
        db.query(MercadoLibreCategoryFee)
        .filter_by(store_id=store_id, category_id=producto.ml_category_id, price=precio)
        .all()
    )
    comisiones: dict[str, ListingFee] = {}
    for fila in filas:
        clave = _LISTING_TYPE_ID_A_CLAVE.get(fila.listing_type_id)
        if clave is None:
            continue
        comisiones[clave] = ListingFee(
            listing_type_name=fila.listing_type_id,
            percentage_fee=float(fila.percentage_fee),
            fixed_fee=float(fila.fixed_fee),
            sale_fee_amount=float(fila.sale_fee_amount),
        )
    return comisiones


def _comision_ml_real(comisiones: dict[str, ListingFee], costo: float | None, precio: float | None, costos_manual: ChannelCosts) -> dict | None:
    """Comisión REAL de Mercado Libre (Clásica/Premium) para ESTA variante a
    este precio exacto, si ya se consultó antes (ver POST
    /api/mercadolibre/comisiones/recalcular — acá nunca se llama a la API
    de Mercado Libre, solo se lee la caché). `comisiones` viene ya resuelto
    por comisiones_ml_cacheadas (no vuelve a consultar la BD). None si no
    hay ningún dato cacheado para su precio actual — nunca se inventa ni se
    aproxima con otro precio.

    31 de agosto de 2026 — hallazgo de backend-architect (ronda de pulido
    pre-cliente): antes recibía `producto` y usaba
    `producto.variants[0].cost_price` (el costo de la PRIMERA variante)
    para TODAS las variantes del producto — en un producto con 2+
    variantes, la fila de la variante #2 en adelante mostraba acá un
    margenClp/margenPct calculado con el costo equivocado, distinto al
    margenMercadoLibreClp/Pct de la misma fila (que sí usa el costo
    correcto). Ahora recibe directamente el costo de la variante que
    corresponde a esta fila, igual que el resto de _fila."""
    if not comisiones:
        return None

    resultado: dict = {}
    for clave, fee in comisiones.items():
        costos_reales = ChannelCosts(
            commission_pct=fee.percentage_fee,
            shipping_cost=costos_manual.shipping_cost,
            other_fixed_cost=(costos_manual.other_fixed_cost or 0.0) + fee.fixed_fee,
        )
        resultado[clave] = {
            "nombre": fee.listing_type_name,
            "comisionPct": fee.percentage_fee,
            "comisionFija": fee.fixed_fee,
            "comisionTotal": fee.sale_fee_amount,
            "margenClp": net_margin(precio, costo, costos_reales),
            "margenPct": net_margin_pct(precio, costo, costos_reales),
        }
    return resultado or None


def resolver_costos_ml(
    comisiones: dict[str, ListingFee], costos_manual: ChannelCosts, listing_type_pref: str | None
) -> tuple[ChannelCosts, str]:
    """ÚNICA función de todo el backend que decide "comisión real vs.
    manual" — la usan build_profitability_rows (Rentabilidad/Oportunidades)
    y app/api/routes/publicaciones.py (/precio-recomendado, /decision,
    /decision-lote) para que los lugares donde el dueño ve un margen de
    Mercado Libre calculen siempre el mismo número para el mismo producto.
    `comisiones` viene ya resuelto por comisiones_ml_cacheadas — esta
    función es pura (sin DB), así ningún caller repite el mismo lookup dos
    veces para el mismo producto (ver _fila, que necesita tanto esto como
    _comision_ml_real). Regla (pedido explícito del dueño, 31 de agosto de
    2026): la comisión REAL ya verificada contra Mercado Libre gana siempre
    que exista y haya una preferencia Clásica/Premium configurada; la
    manual (ChannelCostSettings) es el fallback explícito — sin
    listing_type_pref configurado, elegir_comision_principal
    (domain/ml_fees.py) nunca elige por el dueño y cae acá al manual.
    Nunca inventa un número: sin ninguna de las dos, devuelve la manual tal
    cual (puede venir vacía — ChannelCosts.is_configured() ya sabe manejar
    eso, cae en "datos_insuficientes" río abajo). Devuelve también la
    fuente ("real"|"manual") para que el frontend nunca muestre una
    estimación como si fuera un dato real."""
    principal = elegir_comision_principal(comisiones, listing_type_pref)
    if principal is not None:
        return (
            ChannelCosts(
                commission_pct=principal.percentage_fee,
                shipping_cost=costos_manual.shipping_cost,
                other_fixed_cost=(costos_manual.other_fixed_cost or 0.0) + principal.fixed_fee,
            ),
            "real",
        )
    return costos_manual, "manual"


def _fila(db: Session, store_id: int, producto: Product, variante: ProductVariant, costos_ml_manual: ChannelCosts, listing_type_pref: str | None) -> dict:
    precio = float(variante.price) if variante.price is not None else None
    costo = float(variante.cost_price) if variante.cost_price is not None else None

    comisiones = comisiones_ml_cacheadas(db, store_id, producto, precio)
    costos_ml_efectivos, fuente_comision_ml = resolver_costos_ml(comisiones, costos_ml_manual, listing_type_pref)
    ml_configurado = costos_ml_efectivos.is_configured()

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
        "margenMercadoLibreClp": net_margin(precio, costo, costos_ml_efectivos),
        "margenMercadoLibrePct": net_margin_pct(precio, costo, costos_ml_efectivos),
        # 31 de agosto de 2026 — de qué fuente sale la comisión usada en
        # margenMercadoLibreClp/Pct de ARRIBA ("real"|"manual"), None si no
        # hay ninguna. Nunca confundir con comisionMlReal de abajo, que es
        # el detalle informativo Clásica+Premium (puede tener datos aunque
        # acá el resultado sea "manual", si no hay listing_type_pref
        # configurado — ver resolver_costos_ml).
        "comisionMlFuente": fuente_comision_ml if ml_configurado else None,
        # Comisión REAL de Mercado Libre (29 de agosto de 2026, a pedido del
        # dueño: "la comisión varía por producto") — Clásica y Premium en
        # paralelo, para decidir cuál conviene. None hasta que se corra
        # POST /api/mercadolibre/comisiones/recalcular; nunca se calcula acá
        # con un valor estimado.
        "comisionMlReal": _comision_ml_real(comisiones, costo, precio, costos_ml_manual),
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

    listing_type_pref = config_ml.listing_type_pref if config_ml else None
    productos = db.query(Product).filter_by(store_id=store.id).order_by(Product.name).all()
    filas = [
        _fila(db, store.id, producto, variante, costos_ml, listing_type_pref)
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
