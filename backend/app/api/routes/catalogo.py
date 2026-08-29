"""
Importador universal de catálogo (24 de agosto de 2026 — pivote a
plataforma multi-rubro): sube CUALQUIER Excel/CSV, detecta columnas por
sinónimo (nunca exige nombres exactos), y deja crear/actualizar productos
reales — ver app/domain/catalog_import.py para toda la lógica de detección
y validación, este archivo solo conecta HTTP con esa lógica y con la base
de datos.

Dos pasos, a propósito separados (igual idea que "Analizar archivo" antes
de "Confirmar importación" que pidió el dueño para el flujo de UI):

1. POST /importar/analizar — NO escribe nada. Devuelve el mapeo de columnas
   propuesto y una fila por producto con su validación, para que el usuario
   pueda corregir el mapeo antes de importar de verdad.
2. POST /importar/confirmar — recibe el archivo otra vez + el mapeo
   (corregido o no) y ahí sí crea/actualiza productos.
"""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.db.models import Product, ProductImage, ProductVariant, Store
from app.db.session import get_db
from app.domain.catalog_import import IMPORT_FIELDS, ColumnMapping, RowResult, build_rows, detect_columns, summarize_rows
from app.domain.spreadsheet_io import UnsupportedSpreadsheetFormat, read_rows

router = APIRouter(prefix="/api/catalogo", tags=["catalogo"])


def _read_uploaded_rows(file: UploadFile, contenido: bytes) -> tuple[list[str], list[dict]]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="El archivo no tiene nombre.")
    try:
        return read_rows(BytesIO(contenido), file.filename)
    except (UnsupportedSpreadsheetFormat, ValueError) as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        # Cualquier otro fallo leyendo el archivo (zip corrupto, xlsx dañado,
        # protegido con contraseña, etc.) es un problema del archivo subido,
        # no un error del servidor — un 500 acá además pierde los headers de
        # CORS y el frontend solo ve un fallo de red sin explicación.
        raise HTTPException(
            status_code=400,
            detail="No pudimos leer el archivo. Verifica que sea un Excel (.xlsx) o CSV válido, y que no esté dañado ni protegido con contraseña.",
        ) from err


def _row_to_dict(r: RowResult) -> dict:
    return {
        "fila": r.row_index,
        "sku": r.sku,
        "nombre": r.nombre,
        "marca": r.marca,
        "categoria": r.categoria,
        "precio": r.precio,
        "costo": r.costo,
        "stock": r.stock,
        "descripcion": r.descripcion,
        "imagenUrl": r.imagen_url,
        "codigoBarras": r.codigo_barras,
        "estado": r.estado,
        "problemas": r.problemas,
        "duplicado": r.duplicado,
    }


@router.post("/importar/analizar")
async def analizar_archivo(file: UploadFile, store: Store = Depends(get_current_store)) -> dict:
    # No escribe nada en la base (ver docstring del módulo) — igual exige
    # sesión válida (`store` sin usar más abajo, a propósito): nadie
    # anónimo debería poder ni siquiera previsualizar un archivo acá.
    contenido = await file.read()
    headers, raw_rows = _read_uploaded_rows(file, contenido)

    mapping = detect_columns(headers)
    rows = build_rows(raw_rows, mapping)

    return {
        "encabezados": headers,
        "mapeoPropuesto": mapping.mapping,
        "camposReconocidos": list(IMPORT_FIELDS),
        "resumen": summarize_rows(rows),
        "filas": [_row_to_dict(r) for r in rows],
    }


@router.post("/importar/confirmar")
async def confirmar_importacion(
    file: UploadFile,
    mapeo: str = Form(..., description="JSON con el mapeo de columnas — misma forma que mapeoPropuesto de /analizar"),
    omitir_errores: bool = Form(True),
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    try:
        mapping_dict = json.loads(mapeo)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail=f"El campo 'mapeo' no es JSON válido: {err}") from err

    contenido = await file.read()
    headers, raw_rows = _read_uploaded_rows(file, contenido)
    rows = build_rows(raw_rows, ColumnMapping(mapping=mapping_dict))

    ahora = datetime.now()
    fuente = "excel_upload" if file.filename.lower().endswith((".xlsx", ".xlsm")) else "csv_upload"

    creados: list[str] = []
    actualizados: list[str] = []
    omitidos: list[dict] = []

    for row in rows:
        if row.estado == "error" and omitir_errores:
            omitidos.append({"fila": row.row_index, "nombre": row.nombre or None, "problemas": row.problemas})
            continue

        variante_existente = (
            db.query(ProductVariant).filter_by(store_id=store.id, variant_sku=row.sku).first() if row.sku else None
        )

        if variante_existente is not None:
            # Reimportar el mismo SKU actualiza el producto — nunca lo duplica.
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

    db.commit()

    return {
        "creados": len(creados),
        "actualizados": len(actualizados),
        "omitidos": len(omitidos),
        "detalleOmitidos": omitidos[:20],
    }
