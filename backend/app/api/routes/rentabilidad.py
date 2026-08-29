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

from app.db.models import ChannelCostSettings, Product, ProductVariant
from app.db.session import get_db
from app.domain.profitability import ChannelCosts, gross_margin, gross_margin_pct, net_margin, net_margin_pct

router = APIRouter(prefix="/api/rentabilidad", tags=["rentabilidad"])

# Canal implícito: la tienda física no cobra comisión ni envío sobre sus
# propias ventas (ver channel_costs.py) — no necesita una fila en la BD.
CHANNEL_MERCADO_LIBRE = "mercadolibre"


def _fila(producto: Product, variante: ProductVariant, costos_ml: ChannelCosts, ml_configurado: bool) -> dict:
    precio = float(variante.price) if variante.price is not None else None
    costo = float(variante.cost_price) if variante.cost_price is not None else None

    return {
        "id": variante.id,
        "sku": variante.variant_sku or "",
        "nombre": f"{producto.name} - {variante.variant_label}" if variante.variant_label else producto.name,
        "precio": precio,
        "costo": costo,
        "tieneCosto": costo is not None,
        "margenTiendaClp": gross_margin(precio, costo),
        "margenTiendaPct": gross_margin_pct(precio, costo),
        "mercadoLibreConfigurado": ml_configurado,
        "margenMercadoLibreClp": net_margin(precio, costo, costos_ml),
        "margenMercadoLibrePct": net_margin_pct(precio, costo, costos_ml),
    }


@router.get("")
def reporte_rentabilidad(db: Session = Depends(get_db)) -> dict:
    config_ml = db.query(ChannelCostSettings).filter_by(channel=CHANNEL_MERCADO_LIBRE).first()
    costos_ml = ChannelCosts(
        commission_pct=float(config_ml.commission_pct) if config_ml and config_ml.commission_pct is not None else None,
        shipping_cost=float(config_ml.shipping_cost) if config_ml and config_ml.shipping_cost is not None else None,
        other_fixed_cost=float(config_ml.other_fixed_cost) if config_ml and config_ml.other_fixed_cost is not None else None,
    )
    ml_configurado = costos_ml.is_configured()

    productos = db.query(Product).order_by(Product.name).all()
    filas = [
        _fila(producto, variante, costos_ml, ml_configurado)
        for producto in productos
        for variante in producto.variants
    ]

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
