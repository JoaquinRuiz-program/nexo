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
from io import BytesIO

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.db.models import Store
from app.db.session import get_db
from app.domain.catalog_import import IMPORT_FIELDS, ColumnMapping, build_rows, detect_columns, row_to_dict, summarize_rows
from app.domain.catalog_writer import escribir_filas
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
        "filas": [row_to_dict(r) for r in rows],
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

    fuente = "excel_upload" if file.filename.lower().endswith((".xlsx", ".xlsm")) else "csv_upload"
    return escribir_filas(db, store, rows, fuente=fuente, omitir_errores=omitir_errores)
