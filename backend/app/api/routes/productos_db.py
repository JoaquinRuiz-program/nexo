"""
Catálogo respaldado por la base de datos propia (no WooCommerce) — primera
porción vertical de "datos de prueba -> BD -> API -> frontend" (ver decisión
del 22 de agosto de 2026 de no depender todavía del acceso real a
WooCommerce). Hoy la base se llena con app/db/seed_demo.py; el día que exista
un job real de sincronización con WooCommerce, ese job llena las mismas
tablas (Product/ProductVariant) y este endpoint no cambia una línea.

29 de agosto de 2026 — cada endpoint exige sesión válida y filtra/valida
por `store.id` (Depends(get_current_store)). Antes de esto, `GET/PUT
/api/productos/{id}` buscaba la variante SOLO por su ID, sin verificar de
qué tienda era — con una sola tienda en desarrollo era invisible, pero es
exactamente el hueco (IDOR: adivinar/iterar un ID ajeno) que había que
cerrar antes de tener más de un cliente real. `_variante_de_la_tienda`
centraliza ese chequeo: un ID que existe pero es de OTRA tienda responde
404, igual que un ID que no existe — nunca se distingue una cosa de la
otra en la respuesta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.db.models import Product, ProductVariant, Store
from app.db.session import get_db
from app.domain.marketplace_stock import set_manual_stock

router = APIRouter(prefix="/api/productos", tags=["productos-bd"])


class MarketplaceStockUpdate(BaseModel):
    # None = dejar de ofrecer el producto por Mercado Libre (no configurado).
    cantidad: int | None = None


class CostoUpdate(BaseModel):
    # None = borrar el costo cargado (vuelve a "sin costo", nunca $0).
    costo: float | None = None


def build_producto_fila(producto: Product, variante: ProductVariant) -> dict:
    return {
        "id": variante.id,
        "sku": variante.variant_sku or "",
        "nombre": f"{producto.name} - {variante.variant_label}" if variante.variant_label else producto.name,
        "categoria": producto.category,
        "tipo": producto.product_type,
        "precio": float(variante.price) if variante.price is not None else None,
        "stockQuantity": variante.stock_quantity,
        "gestionaStock": variante.manage_stock,
        "estadoStock": variante.stock_status,
        # Tope manual de unidades reservadas para Mercado Libre — NO es
        # stock físico (ver app/domain/marketplace_stock.py). None = el
        # dueño todavía no decidió ofrecer este producto por ese canal.
        "marketplaceStock": variante.marketplace_stock,
        "esVariante": producto.product_type == "variable",
        "colorVariante": variante.variant_label,
        "parentId": producto.id,
        # Todavía no hay vínculo con WooCommerce para datos de prueba —
        # nunca se inventa un ID que no existe (ver app/domain/analysis.py).
        "woocommerceParentId": None,
        "woocommerceVariationId": None,
    }


def _variante_de_la_tienda(db: Session, store: Store, variant_id: int) -> ProductVariant:
    """La variante SOLO si es de esta tienda — un ID real pero de otra
    empresa da el mismo 404 que un ID inexistente (nunca 403: no hay que
    confirmarle a quien pregunta que ese ID existe en algún lado)."""
    variante = db.get(ProductVariant, variant_id)
    if variante is None or variante.store_id != store.id:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    return variante


@router.get("")
def listar_productos(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> list[dict]:
    productos = db.query(Product).filter_by(store_id=store.id).order_by(Product.name).all()
    return [build_producto_fila(producto, variante) for producto in productos for variante in producto.variants]


@router.get("/{variant_id}")
def obtener_producto(variant_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    variante = _variante_de_la_tienda(db, store, variant_id)
    return build_producto_fila(variante.product, variante)


@router.put("/{variant_id}/stock-mercadolibre")
def configurar_stock_mercado_libre(
    variant_id: int,
    body: MarketplaceStockUpdate,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """El dueño decide manualmente cuántas unidades ofrecer por Mercado
    Libre — 5 -> 10 -> 0 -> None, en cualquier momento. Nunca toca
    stock_quantity (el stock que reporta WooCommerce): son dos números
    completamente separados a propósito (ver domain/marketplace_stock.py)."""
    variante = _variante_de_la_tienda(db, store, variant_id)

    try:
        variante.marketplace_stock = set_manual_stock(body.cantidad)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)


@router.put("/{variant_id}/costo")
def configurar_costo(
    variant_id: int, body: CostoUpdate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """Cierra el círculo de "Oportunidades": completar el costo de compra de
    UN producto puntual, sin tener que volver a subir todo el catálogo por
    Excel. `cost_price` es el mismo campo que ya lee domain/profitability.py
    — el margen se recalcula solo la próxima vez que se pida (acá no se
    guarda ningún margen, solo el costo real, igual que en la importación)."""
    variante = _variante_de_la_tienda(db, store, variant_id)
    if body.costo is not None and body.costo < 0:
        raise HTTPException(status_code=400, detail="El costo no puede ser negativo.")

    variante.cost_price = body.costo
    db.commit()
    db.refresh(variante)
    return build_producto_fila(variante.product, variante)
