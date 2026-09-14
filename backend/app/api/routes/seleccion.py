"""
GET /api/seleccion — "¿qué productos conviene publicar en Mercado Libre?"
(24 de agosto de 2026). Reutiliza domain/catalog_selection.py sobre las
mismas filas que arma GET /api/rentabilidad — nunca recalcula un margen
acá, y ningún umbral queda hardcodeado: el usuario decide qué "rentable"
significa vía query params.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.api.routes.rentabilidad import build_profitability_rows
from app.db.models import Store
from app.db.session import get_db
from app.domain.catalog_selection import SelectionCriteria, select, summarize_selection

router = APIRouter(prefix="/api/seleccion", tags=["seleccion"])


@router.get("")
def seleccionar_productos(
    canal: str = Query("tienda", pattern="^(tienda|mercadolibre)$", description="Sobre qué margen evaluar"),
    margen_minimo_clp: Optional[float] = Query(None, description='"Ganancia superior a $X"'),
    margen_minimo_pct: Optional[float] = Query(None, description='"Margen superior a X%"'),
    top: Optional[int] = Query(None, ge=1, description='"Los N productos más rentables"'),
    requiere_stock: bool = Query(False, description="El stock NO afecta la rentabilidad (solo margen monetario); dejar en False salvo un caso especial"),
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    filas, _ = build_profitability_rows(db, store)
    criterios = SelectionCriteria(
        min_margin_clp=margen_minimo_clp,
        min_margin_pct=margen_minimo_pct,
        require_marketplace_stock=requiere_stock,
        channel=canal,
    )
    clasificadas = select(filas, criterios, top_n=top)
    return {"resumen": summarize_selection(clasificadas), "productos": clasificadas}
