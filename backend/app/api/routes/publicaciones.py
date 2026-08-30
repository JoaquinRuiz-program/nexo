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

29 de agosto de 2026 — fase de publicación real, commit 3/N: se agregan
POST /{variant_id}/mercadolibre/preparar y POST /{variant_id}/mercadolibre/validar,
el flujo de SOLO LECTURA hacia la API real de Mercado Libre (categoría +
atributos reales de la categoría). Ninguno de los dos llama nunca a
POST /items ni crea un MarketplaceListing — eso es exclusivamente del
futuro endpoint /confirmar (commit 4/N), que además vuelve a validar TODO
desde cero (rentabilidad incluida) en vez de confiar en lo que devolvió
/validar — ver la nota que ambos endpoints devuelven en su respuesta.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.api.deps import get_current_store
from app.api.routes.mercadolibre import _build_ml_config, _get_account, _require_configured
from app.api.routes.rentabilidad import build_profitability_rows
from app.config import get_settings
from app.db.models import ProductVariant, Store
from app.db.session import get_db
from app.domain.ai_content import generate_title
from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.listing_draft import build_draft
from app.domain.listing_validation import evaluar_atributos

router = APIRouter(prefix="/api/publicaciones", tags=["publicaciones"])

_NOTA_VALIDACION_NO_ES_AUTORIZACION = (
    "Esta validación no autoriza a publicar — la rentabilidad y los datos se vuelven a verificar al confirmar."
)


def _build_one(db: Session, store: Store, variant_id: int, criteria: SelectionCriteria) -> Optional[dict]:
    # build_profitability_rows ya scopea por tienda — un variant_id de otra
    # empresa simplemente no aparece en `filas`, así que esto devuelve None
    # (mismo 404 que "no existe") en vez de filtrar antes/después.
    filas, _ = build_profitability_rows(db, store)
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
    variant_id: int,
    canal: str = "tienda",
    requiere_stock: bool = True,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    criteria = SelectionCriteria(channel=canal, require_marketplace_stock=requiere_stock)
    borrador = _build_one(db, store, variant_id, criteria)
    if borrador is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    return borrador


class PrepararRequest(BaseModel):
    variant_ids: list[int]
    canal: str = "tienda"
    requiere_stock: bool = True


@router.post("/preparar")
def preparar_publicaciones(
    body: PrepararRequest, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    criteria = SelectionCriteria(channel=body.canal, require_marketplace_stock=body.requiere_stock)
    borradores: list[dict] = []
    no_encontrados: list[int] = []

    for variant_id in body.variant_ids:
        borrador = _build_one(db, store, variant_id, criteria)
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


# ------------------------------------------------------------------
# Publicación REAL en Mercado Libre — solo lectura por ahora (29 de agosto
# de 2026, commit 3/N). `_variante_de_la_empresa` es el único lugar de
# estos dos endpoints que decide "esta variante es de esta tienda" — igual
# criterio que productos_db.py: reusa build_profitability_rows (ya scopea
# por store_id) para el chequeo Y de paso trae la rentabilidad calculada,
# sin duplicar esa consulta.
# ------------------------------------------------------------------


def _variante_de_la_empresa(db: Session, store: Store, variant_id: int) -> tuple[ProductVariant, dict]:
    filas, _ = build_profitability_rows(db, store)
    fila = next((f for f in filas if f["id"] == variant_id), None)
    if fila is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    variante = db.get(ProductVariant, variant_id)
    return variante, fila


def _cuenta_ml_conectada(db: Session, store: Store):
    account = _get_account(db, store)
    if account is None or account.status != "connected" or not account.external_account_site_id:
        raise HTTPException(
            status_code=400,
            detail="Conectá tu cuenta de Mercado Libre (Integraciones → Mercado Libre) antes de publicar.",
        )
    return account


@router.post("/{variant_id}/mercadolibre/preparar")
async def preparar_publicacion_mercadolibre(
    variant_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """Arma lo que Nexo YA sabe del producto — nunca llama a POST /items.
    La categoría es siempre una SUGERENCIA (ver `categoriaConfirmada`,
    siempre False acá): confirmarla es responsabilidad del dueño en el
    siguiente paso (/validar), nunca de este endpoint."""
    variante, fila = _variante_de_la_empresa(db, store, variant_id)
    producto = variante.product

    if variante.price is None:
        raise HTTPException(
            status_code=400,
            detail="Este producto no tiene precio de venta cargado — no se puede preparar una publicación sin precio.",
        )

    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)
    account = _cuenta_ml_conectada(db, store)

    categoria_sugerida: Optional[dict] = None
    if producto.ml_category_id:
        categoria_sugerida = {"id": producto.ml_category_id, "nombre": producto.ml_category_name}
    else:
        # Todavía no se predijo ninguna categoría para este producto (no
        # pasó por el motor de comisiones) — se intenta predecir ahora,
        # público, no requiere la cuenta conectada en sí (solo su site_id).
        adapter = MercadoLibreAdapter(cfg)
        try:
            prediccion = await adapter.predict_category(producto.name, account.external_account_site_id)
        except (MercadoLibreAuthError, MercadoLibreRequestError):
            prediccion = None
        finally:
            await adapter.aclose()
        if prediccion:
            categoria_sugerida = {"id": prediccion["categoryId"], "nombre": prediccion["categoryName"]}

    imagenes = [img.url for img in producto.images]

    advertencias: list[str] = []
    if not imagenes:
        advertencias.append("Sin imagen cargada.")
    if categoria_sugerida is None:
        advertencias.append("No pudimos sugerir una categoría — buscala manualmente en el siguiente paso.")
    if not fila.get("tieneCosto"):
        advertencias.append("Todavía no se cargó el costo de compra de este producto.")
    if not fila.get("marketplaceStock"):
        advertencias.append("No hay unidades reservadas para Mercado Libre todavía.")

    return {
        "variantId": variante.id,
        "sku": variante.variant_sku or "",
        "titulo": generate_title(nombre=producto.name, marca=producto.brand),
        "precio": float(variante.price),
        "marketplaceStock": variante.marketplace_stock,
        "imagenes": imagenes,
        "categoriaSugerida": categoria_sugerida,
        "categoriaConfirmada": False,
        "marca": producto.brand,
        "codigoBarras": variante.barcode,
        "rentabilidad": {
            "margenTiendaClp": fila.get("margenTiendaClp"),
            "margenTiendaPct": fila.get("margenTiendaPct"),
            "margenMercadoLibreClp": fila.get("margenMercadoLibreClp"),
            "margenMercadoLibrePct": fila.get("margenMercadoLibrePct"),
        },
        "advertencias": advertencias,
    }


class ValidarPublicacionRequest(BaseModel):
    category_id: str
    condition: str = "new"


@router.post("/{variant_id}/mercadolibre/validar")
async def validar_publicacion_mercadolibre(
    variant_id: int,
    body: ValidarPublicacionRequest,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """Consulta los atributos REALES de la categoría (GET
    /categories/{id}/attributes) y los cruza contra lo que Nexo ya sabe —
    nunca llama a POST /items, nunca crea un MarketplaceListing. La
    rentabilidad que devuelve es informativa: el gate real que puede
    bloquear una publicación vive en el futuro /confirmar, no acá (ver nota
    en la respuesta)."""
    if body.condition not in ("new", "used"):
        raise HTTPException(status_code=400, detail="La condición tiene que ser 'new' o 'used'.")
    if not body.category_id or not body.category_id.strip():
        raise HTTPException(status_code=400, detail="Falta indicar la categoría a validar.")

    variante, fila = _variante_de_la_empresa(db, store, variant_id)
    producto = variante.product

    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)
    _cuenta_ml_conectada(db, store)

    adapter = MercadoLibreAdapter(cfg)
    try:
        atributos_categoria = await adapter.get_category_attributes(body.category_id.strip())
    except MercadoLibreRequestError as err:
        if err.status == 404:
            raise HTTPException(
                status_code=400, detail="La categoría no existe o no es válida. Verificá el ID e intentá de nuevo."
            ) from err
        raise HTTPException(
            status_code=502,
            detail="No pudimos consultar los atributos de esa categoría en Mercado Libre en este momento. Intentá de nuevo más tarde.",
        ) from err
    except MercadoLibreAuthError as err:
        raise HTTPException(
            status_code=502,
            detail="No pudimos consultar los atributos de esa categoría en Mercado Libre en este momento. Intentá de nuevo más tarde.",
        ) from err
    finally:
        await adapter.aclose()

    # Lo que Nexo ya sabe, mapeado a los IDs de atributo que Mercado Libre
    # podría usar — GTIN/EAN/UPC son alias del mismo dato real (el código
    # de barras), nunca tres datos distintos inventados.
    datos_conocidos: dict[str, str] = {}
    if producto.brand:
        datos_conocidos["BRAND"] = producto.brand
    if variante.barcode:
        datos_conocidos["GTIN"] = variante.barcode
        datos_conocidos["EAN"] = variante.barcode
        datos_conocidos["UPC"] = variante.barcode

    resultado = evaluar_atributos(atributos_categoria, body.condition, datos_conocidos, {})
    clasificacion = classify_product(fila, SelectionCriteria(channel="mercadolibre", require_marketplace_stock=True))

    return {
        "categoryId": body.category_id.strip(),
        "condition": body.condition,
        "atributosCompletos": [
            {"id": a.id, "valueId": a.value_id, "valueName": a.value_name} for a in resultado.completos
        ],
        "atributosFaltantes": [
            {"id": f.id, "nombre": f.nombre, "valueType": f.value_type, "opciones": f.opciones}
            for f in resultado.faltantes
        ],
        "listoParaPublicar": resultado.listo_para_publicar,
        "rentabilidad": {
            "clasificacion": clasificacion["clasificacion"],
            "razon": clasificacion["razon"],
            "margenMercadoLibreClp": fila.get("margenMercadoLibreClp"),
            "margenMercadoLibrePct": fila.get("margenMercadoLibrePct"),
        },
        "nota": _NOTA_VALIDACION_NO_ES_AUTORIZACION,
    }
