"""
Escritura en base de datos de filas ya validadas por app/domain/catalog_import.py.

Separado de catalog_import.py a propósito: ese módulo es funciones puras
(sin red, sin DB, ver su propio docstring) — esto sí toca la base de datos,
así que vive aparte. Factorizado el 5 de septiembre de 2026 al agregar la
importación desde Google Sheets (app/api/routes/google_sheets.py): antes
esta lógica de "crear o actualizar productos a partir de RowResult" vivía
solo dentro de app/api/routes/catalogo.py::confirmar_importacion — ahora la
comparten los dos orígenes (Excel/CSV subido y Google Sheets) sin duplicar
el loop de creación/actualización ni el respeto al límite de productos del
plan.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Product, ProductImage, ProductVariant, Store
from app.domain.catalog_import import RowResult
from app.domain.plans import limite_alcanzado


def escribir_filas(db: Session, store: Store, rows: list[RowResult], *, fuente: str, omitir_errores: bool = True) -> dict:
    """Crea/actualiza productos reales a partir de filas ya validadas.
    Misma lógica exacta que usaba app/api/routes/catalogo.py: reimportar un
    SKU ya existente actualiza el producto (nunca lo duplica), y crear
    productos nuevos respeta el límite de productos del plan de la tienda
    (nunca lo pasa por alto, sin importar el origen de los datos)."""
    ahora = datetime.now()

    creados: list[str] = []
    actualizados: list[str] = []
    omitidos: list[dict] = []
    omitidos_por_limite = 0

    limite_productos = store.subscription.plan.product_limit if (store.subscription and store.subscription.plan) else None
    cantidad_productos = db.query(Product).filter_by(store_id=store.id).count()

    for row in rows:
        if row.estado == "error" and omitir_errores:
            omitidos.append({"fila": row.row_index, "nombre": row.nombre or None, "problemas": row.problemas})
            continue

        variante_existente = (
            db.query(ProductVariant).filter_by(store_id=store.id, variant_sku=row.sku).first() if row.sku else None
        )

        if variante_existente is not None:
            producto = variante_existente.product
            producto.name = row.nombre or producto.name
            producto.brand = row.marca or producto.brand
            producto.category = row.categoria or producto.category
            producto.description = row.descripcion or producto.description
            producto.updated_at = ahora
            if row.precio is not None:
                variante_existente.price = row.precio
            if row.costo is not None:
                variante_existente.cost_price = row.costo
            if row.stock is not None:
                variante_existente.stock_quantity = row.stock
                variante_existente.manage_stock = True
                variante_existente.stock_status = "instock" if row.stock > 0 else "outofstock"
            if row.codigo_barras:
                variante_existente.barcode = row.codigo_barras
            variante_existente.updated_at = ahora
            actualizados.append(row.sku or row.nombre)
            continue

        if limite_alcanzado(cantidad_productos, limite_productos):
            omitidos_por_limite += 1
            omitidos.append({
                "fila": row.row_index, "nombre": row.nombre or None,
                "problemas": [f"Has alcanzado el límite de productos de tu plan ({limite_productos}). Actualiza tu plan para agregar más."],
            })
            continue

        producto = Product(
            store=store,
            internal_sku=row.sku,
            name=row.nombre,
            brand=row.marca,
            category=row.categoria,
            description=row.descripcion,
            product_type="simple",
            source=fuente,
            created_at=ahora,
            updated_at=ahora,
        )
        db.add(producto)
        db.flush()

        db.add(
            ProductVariant(
                product=producto,
                store_id=store.id,
                variant_sku=row.sku,
                price=row.precio,
                cost_price=row.costo,
                stock_quantity=row.stock,
                manage_stock=row.stock is not None,
                stock_status="instock" if (row.stock or 0) > 0 else "outofstock",
                barcode=row.codigo_barras,
                created_at=ahora,
                updated_at=ahora,
            )
        )

        if row.imagen_url:
            db.add(ProductImage(product=producto, url=row.imagen_url, source="excel_url", position=0, created_at=ahora))

        creados.append(row.sku or row.nombre)
        cantidad_productos += 1

    db.commit()

    return {
        "creados": len(creados),
        "actualizados": len(actualizados),
        "omitidos": len(omitidos),
        "detalleOmitidos": omitidos[:20],
        # 15 de septiembre de 2026 — revisión por perfil: el retailer subió
        # 1.100 filas, entraron 1.000 y nada decía que fue por el plan.
        "limitePlan": {"limite": limite_productos, "omitidosPorLimite": omitidos_por_limite} if omitidos_por_limite else None,
    }
