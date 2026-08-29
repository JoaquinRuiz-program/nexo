"""
Catálogo respaldado por la base de datos propia (no WooCommerce) — primera
porción vertical de "datos de prueba -> BD -> API -> frontend" (ver decisión
del 22 de agosto de 2026 de no depender todavía del acceso real a
WooCommerce). Hoy la base se llena con app/db/seed_demo.py; el día que exista
un job real de sincronización con WooCommerce, ese job llena las mismas
tablas (Product/ProductVariant) y este endpoint no cambia una línea.

Sin autenticación ni multi-tienda todavía: devuelve el catálogo completo,
sin filtrar por tienda (solo existe una tienda mientras no haya login). Eso
es lo próximo que habrá que agregar acá cuando exista un usuario autenticado.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Product, ProductVariant
from app.db.session import get_db
from app.domain.marketplace_stock import set_manual_stock

router = APIRouter(prefix="/api/productos", tags=["productos-bd"])


class MarketplaceStockUpdate(BaseModel):
    # None = dejar de ofrecer el producto por Mercado Libre (no configurado).
    cantidad: int | None = None


def _fila(producto: Product, variante: ProductVariant) -> dict:
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


@router.get("")
def listar_productos(db: Session = Depends(get_db)) -> list[dict]:
    productos = db.query(Product).order_by(Product.name).all()
    return [_fila(producto, variante) for producto in productos for variante in producto.variants]


@router.get("/{variant_id}")
def obtener_producto(variant_id: int, db: Session = Depends(get_db)) -> dict:
    variante = db.get(ProductVariant, variant_id)
    if variante is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    return _fila(variante.product, variante)


@router.put("/{variant_id}/stock-mercadolibre")
def configurar_stock_mercado_libre(
    variant_id: int, body: MarketplaceStockUpdate, db: Session = Depends(get_db)
) -> dict:
    """El dueño decide manualmente cuántas unidades ofrecer por Mercado
    Libre — 5 -> 10 -> 0 -> None, en cualquier momento. Nunca toca
    stock_quantity (el stock que reporta WooCommerce): son dos números
    completamente separados a propósito (ver domain/marketplace_stock.py)."""
    variante = db.get(ProductVariant, variant_id)
    if variante is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")

    try:
        variante.marketplace_stock = set_manual_stock(body.cantidad)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    db.commit()
    db.refresh(variante)
    return _fila(variante.product, variante)
