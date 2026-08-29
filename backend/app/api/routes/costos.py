"""
POST /api/costos/importar — sube el archivo de costos del dueño (.csv o
.xlsx) directamente, sin pasar por una terminal. Reutiliza
app/db/import_costs.py: mismo comportamiento exacto que correr el script
por línea de comandos (mismos reportes de SKU no encontrados / costos
inválidos), solo cambia de dónde viene el archivo.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.import_costs import import_costs
from app.db.session import get_db

router = APIRouter(prefix="/api/costos", tags=["costos"])


@router.post("/importar")
async def importar_costos(file: UploadFile, db: Session = Depends(get_db)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="El archivo no tiene nombre.")

    contenido = await file.read()
    try:
        resultado = import_costs(io.BytesIO(contenido), file.filename, db)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return {
        "actualizados": resultado.actualizados,
        "noEncontrados": resultado.no_encontrados,
        "filasInvalidas": resultado.filas_invalidas,
    }
