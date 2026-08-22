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
from sqlalchemy.orm import Session

from app.db.models import Product, ProductVariant
from app.db.session import get_db

router = APIRouter(prefix="/api/productos", tags=["productos-bd"])


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
