"""
GET /api/publicaciones/borrador/{variant_id} y POST /api/publicaciones/preparar
— "preparar publicación" en modo simulación (24 de agosto de 2026).

Ningún dato se envía a Mercado Libre — no hay conexión real todavía (ver
adapters/mercadolibre.py). Esto es un cálculo de vista: junta rentabilidad
+ clasificación (ya calculadas por rentabilidad.py/catalog_selection.py) +
contenido simulado (ai_content.py) en el objeto que arma
domain/listing_draft.py. No se persiste en ninguna tabla — cuando exista
publicación real, "aprobar" un borrador recién ahí va a crear un
MarketplaceListing de verdad.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.rentabilidad import build_profitability_rows
from app.db.models import ProductVariant
from app.db.session import get_db
from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.listing_draft import build_draft

router = APIRouter(prefix="/api/publicaciones", tags=["publicaciones"])


def _build_one(db: Session, variant_id: int, criteria: SelectionCriteria) -> Optional[dict]:
    filas, _ = build_profitability_rows(db)
    fila = next((f for f in filas if f["id"] == variant_id), None)
    if fila is None:
        return None

    variante = db.get(ProductVariant, variant_id)
    producto = variante.product
    fila_clasificada = {**fila, **classify_product(fila, criteria)}

    return build_draft(
        fila_clasificada,
        categoria=producto.category,
        descripcion=producto.description,
        imagenes=[img.url for img in producto.images],
        codigo_barras=variante.barcode,
        variant_label=variante.variant_label,
        marca=producto.brand,
    )


@router.get("/borrador/{variant_id}")
def obtener_borrador(
    variant_id: int, canal: str = "tienda", requiere_stock: bool = True, db: Session = Depends(get_db)
) -> dict:
    criteria = SelectionCriteria(channel=canal, require_marketplace_stock=requiere_stock)
    borrador = _build_one(db, variant_id, criteria)
    if borrador is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    return borrador


class PrepararRequest(BaseModel):
    variant_ids: list[int]
    canal: str = "tienda"
    requiere_stock: bool = True


@router.post("/preparar")
def preparar_publicaciones(body: PrepararRequest, db: Session = Depends(get_db)) -> dict:
    criteria = SelectionCriteria(channel=body.canal, require_marketplace_stock=body.requiere_stock)
    borradores: list[dict] = []
    no_encontrados: list[int] = []

    for variant_id in body.variant_ids:
        borrador = _build_one(db, variant_id, criteria)
        if borrador is None:
            no_encontrados.append(variant_id)
        else:
            borradores.append(borrador)

    return {
        "resumen": {
            "total": len(borradores),
            "listosParaPublicar": sum(1 for b in borradores if b["estado"] == "listo_para_publicar"),
            "requierenRevision": sum(1 for b in borradores if b["estado"] == "requiere_revision"),
            "noRecomendados": sum(1 for b in borradores if b["estado"] == "no_recomendado"),
        },
        "borradores": borradores,
        "noEncontrados": no_encontrados,
    }
