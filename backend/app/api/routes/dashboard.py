"""
GET /api/dashboard/resumen — el único endpoint que arma el Dashboard del
frontend, consolidando en una sola llamada lo que antes eran varias
consultas sueltas: catálogo, rentabilidad, ventas importadas de Mercado
Libre y estado de conexión. No inventa ni calcula nada nuevo — cada sección
reusa el mismo código ya probado que usan sus endpoints dedicados
(GET /api/productos, GET /api/rentabilidad, GET /api/mercadolibre/estado),
para no duplicar reglas de negocio ni arriesgar que se desincronicen.

29 de agosto de 2026 — con login real, cada request resuelve la tienda
desde la sesión (ver app/api/deps.py:get_current_store), nunca "la primera
que exista". Un usuario sin sesión válida nunca llega a ver este resumen.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.api.routes.mercadolibre import build_estado_conexion
from app.api.routes.productos_db import build_producto_fila
from app.api.routes.rentabilidad import build_profitability_rows
from app.config import get_settings
from app.db.models import Order, Product, Store
from app.db.session import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

VENTANA_VENTAS_RECIENTES_DIAS = 30


def _umbral_stock_bajo(store: Store) -> int:
    if store.settings is not None:
        return store.settings.low_stock_threshold
    return 5  # mismo default que StoreSettings.low_stock_threshold


@router.get("/resumen")
def resumen(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    umbral = _umbral_stock_bajo(store)

    productos = db.query(Product).filter_by(store_id=store.id).order_by(Product.name).all()
    pares = [(producto, variante) for producto in productos for variante in producto.variants]

    con_stock = [par for par in pares if par[1].stock_status == "instock"]
    sin_stock_gestionado = [
        par for par in pares if par[1].manage_stock and (par[1].stock_quantity or 0) <= 0
    ]
    stock_bajo = [
        par
        for par in pares
        if par[1].manage_stock and par[1].stock_quantity is not None and 0 < par[1].stock_quantity <= umbral
    ]

    filas_rentabilidad, ml_configurado = build_profitability_rows(db, store)
    con_costo = [f for f in filas_rentabilidad if f["tieneCosto"]]
    # None si todavía no hay ningún costo cargado — "0 rentables" sería
    # engañoso (parecería que se revisó y ninguno conviene, cuando en
    # realidad no hay con qué calcularlo todavía).
    rentables = len([f for f in con_costo if (f["margenTiendaClp"] or 0) > 0]) if con_costo else None

    total_pedidos = db.query(Order).filter_by(store_id=store.id).count()
    desde = datetime.now() - timedelta(days=VENTANA_VENTAS_RECIENTES_DIAS)
    pedidos_recientes = db.query(Order).filter_by(store_id=store.id).filter(Order.order_date >= desde).count()
    ultimo_pedido = db.query(Order).filter_by(store_id=store.id).order_by(Order.order_date.desc()).first()

    mercado_libre = build_estado_conexion(db, store, get_settings())

    return {
        "catalogo": {
            "total": len(pares),
            "conStock": len(con_stock),
            "sinStock": len(sin_stock_gestionado),
            "stockBajo": len(stock_bajo),
            "alertasStockBajo": [build_producto_fila(p, v) for p, v in stock_bajo[:5]],
            "alertasSinStock": [build_producto_fila(p, v) for p, v in sin_stock_gestionado[:5]],
        },
        "rentabilidad": {
            "totalProductos": len(filas_rentabilidad),
            "productosConCosto": len(con_costo),
            "productosRentables": rentables,
            "canalesConfigurados": [c for c in (["mercadolibre"] if ml_configurado else [])],
        },
        "ventas": {
            "pedidosImportados": total_pedidos,
            "pedidosUltimos30Dias": pedidos_recientes,
            "ultimaVentaImportada": ultimo_pedido.order_date.isoformat() if ultimo_pedido else None,
        },
        "mercadoLibre": mercado_libre,
        "ultimaActualizacion": datetime.now().isoformat(),
    }
