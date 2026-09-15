"""Ventas reales de Mercado Libre (15 de septiembre de 2026) — resumen,
gráfico, más vendidos y pedidos, calculados sobre la tabla `orders` que llena
POST /api/mercadolibre/importar-ventas. Siempre de la empresa de la sesión
(get_current_store); el cálculo vive en app/domain/ventas_ml.py."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_store
from app.db.models import Order, OrderItem, OrderReturn, ProductVariant, Store
from app.db.session import get_db
from app.domain.ventas_ml import Venta, VentaItem, grafico_ventas, mas_vendidos, pedidos, resumen_ventas

router = APIRouter(prefix="/api/mercadolibre", tags=["mercadolibre"])

MARKETPLACE = "mercadolibre"
_RANGO = "^(7d|30d|mes)$"


def _fecha_local(fecha: datetime) -> datetime:
    # Mercado Libre informa la fecha con zona horaria; el resto de Nexo trabaja
    # con hora local sin zona (mismo criterio que el Dashboard y el admin).
    return fecha.astimezone().replace(tzinfo=None) if fecha.tzinfo else fecha


def _ventas_de_la_empresa(db: Session, store: Store) -> list[Venta]:
    ordenes = (
        db.query(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.variant).selectinload(ProductVariant.product))
        .filter(Order.store_id == store.id, Order.channel == MARKETPLACE)
        .all()
    )
    reembolsadas = {
        order_id
        for (order_id,) in db.query(OrderReturn.order_id).filter(
            OrderReturn.store_id == store.id, OrderReturn.money_status == "refunded", OrderReturn.order_id.isnot(None)
        )
    }
    ventas = []
    for orden in ordenes:
        items = []
        for item in orden.items:
            variante = item.variant
            if variante is not None:
                nombre = f"{variante.product.name} - {variante.variant_label}" if variante.variant_label else variante.product.name
                sku = variante.variant_sku or item.external_item_sku or ""
            else:
                nombre = "Producto fuera del catálogo de Nexo"
                sku = item.external_item_sku or ""
            items.append(VentaItem(sku=sku, nombre=nombre, cantidad=item.quantity, subtotal=float(item.unit_price) * item.quantity))
        ventas.append(Venta(
            external_id=orden.external_order_id, fecha=_fecha_local(orden.order_date), estado=orden.status,
            total=float(orden.total_amount), reembolsada=orden.id in reembolsadas, items=items,
        ))
    return ventas


@router.get("/ventas/resumen")
def resumen_ventas_ml(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    return resumen_ventas(_ventas_de_la_empresa(db, store), datetime.now().date())


@router.get("/ventas/grafico")
def grafico_ventas_ml(
    rango: str = Query("30d", pattern=_RANGO), db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> list[dict]:
    return grafico_ventas(_ventas_de_la_empresa(db, store), rango, datetime.now().date())


@router.get("/ventas/mas-vendidos")
def mas_vendidos_ml(
    rango: str = Query("30d", pattern=_RANGO),
    limite: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> list[dict]:
    return mas_vendidos(_ventas_de_la_empresa(db, store), rango, datetime.now().date(), limite)


@router.get("/pedidos")
def pedidos_ml(
    search: str = "",
    estado: str = "todos",
    producto: str = "todos",
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    return pedidos(_ventas_de_la_empresa(db, store), search=search, estado=estado, producto=producto, page=page, page_size=pageSize)
