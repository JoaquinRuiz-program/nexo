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

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.api.deps import get_current_store
from app.api.routes.mercadolibre import _build_ml_config, _get_account, _get_valid_access_token, _require_configured
from app.api.routes.rentabilidad import build_profitability_rows
from app.config import get_settings
from app.db.models import MarketplaceListing, MarketplaceListingVariant, ProductVariant, Store
from app.db.session import get_db
from app.domain.ai_content import generate_title
from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.listing_draft import build_draft
from app.domain.listing_validation import construir_attributes_payload, evaluar_atributos
from app.domain.ml_fees import resolver_listing_type

logger = logging.getLogger(__name__)

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


# ------------------------------------------------------------------
# Publicación REAL (commit 4/N, 29 de agosto de 2026) — el único endpoint
# de todo el backend que puede terminar ejecutando POST /items de verdad.
#
# Vuelve a validar TODO desde cero (nunca confía en lo que devolvió
# /preparar o /validar, que pudieron haberse llamado hace rato): rentabilidad,
# atributos de categoría, condición, tipo de publicación/comisión, y
# duplicados. Del frontend solo se acepta lo que el dueño decide a mano
# (categoría, condición, Clásica/Premium, atributos que Nexo no puede saber
# solo) — precio/costo/stock/margen/SKU/marca/imágenes siempre se leen de
# la base en este mismo momento, nunca del body del request.
# ------------------------------------------------------------------


class _RespuestaMercadoLibreSinItemId(Exception):
    """Mercado Libre respondió sin un `id` real de publicación — no hay
    forma de saber con certeza qué pasó del otro lado, así que nunca se
    trata como éxito ni se persiste nada con este dato faltante."""


async def _ejecutar_publicacion_real(adapter: MercadoLibreAdapter, access_token: str, payload: dict) -> dict:
    """ÚNICA función de todo el backend que ejecuta el POST /items real —
    el punto auditable: validaciones -> construir payload -> [ACÁ] ->
    persistir resultado. No atrapa ninguna excepción: MercadoLibreAuthError
    y MercadoLibreRequestError suben tal cual para que quien llame decida
    qué responder, sin haber escrito nada en la base todavía."""
    respuesta = await adapter.create_item(access_token, payload)
    if not respuesta.get("id"):
        raise _RespuestaMercadoLibreSinItemId(f"Mercado Libre respondió sin item_id: {respuesta}")
    return respuesta


class ConfirmarPublicacionRequest(BaseModel):
    category_id: str
    condition: str = "new"
    listing_type: str  # "classic" | "premium"
    attributes: dict[str, str] = {}


@router.post("/{variant_id}/mercadolibre/confirmar")
async def confirmar_publicacion_mercadolibre(
    variant_id: int,
    body: ConfirmarPublicacionRequest,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    if body.condition not in ("new", "used"):
        raise HTTPException(status_code=400, detail="La condición tiene que ser 'new' o 'used'.")
    if not body.category_id or not body.category_id.strip():
        raise HTTPException(status_code=400, detail="Falta indicar la categoría a publicar.")
    if body.listing_type not in ("classic", "premium"):
        raise HTTPException(status_code=400, detail="El tipo de publicación tiene que ser 'classic' o 'premium'.")

    # store viene exclusivamente de get_current_store — variante y cuenta se
    # resuelven siempre a partir de esa store, nunca de un store_id que
    # pudiera venir del body (acá ni siquiera se acepta ese campo).
    variante, fila = _variante_de_la_empresa(db, store, variant_id)
    producto = variante.product
    account = _cuenta_ml_conectada(db, store)
    category_id = body.category_id.strip()

    # Duplicados: bloquea si esta variante ya tiene una publicación previa
    # (cualquier estado salvo not_published) para ESTA cuenta de ML.
    ya_publicada = (
        db.query(MarketplaceListingVariant)
        .join(MarketplaceListing, MarketplaceListingVariant.listing_id == MarketplaceListing.id)
        .filter(
            MarketplaceListingVariant.variant_id == variante.id,
            MarketplaceListing.account_id == account.id,
            MarketplaceListing.status != "not_published",
        )
        .first()
    )
    if ya_publicada is not None:
        raise HTTPException(
            status_code=409,
            detail="Este producto ya tiene una publicación de Mercado Libre para esta cuenta.",
        )

    # Rentabilidad recalculada de cero, con datos frescos de la base — nunca
    # se confía en lo que haya devuelto /validar en algún momento anterior.
    clasificacion = classify_product(fila, SelectionCriteria(channel="mercadolibre", require_marketplace_stock=True))
    if clasificacion["clasificacion"] not in ("rentable", "margen_bajo"):
        raise HTTPException(
            status_code=400,
            detail=f"Este producto no es rentable para publicar en Mercado Libre: {clasificacion['razon']}",
        )

    if variante.price is None:
        raise HTTPException(status_code=400, detail="Este producto no tiene precio de venta cargado.")
    imagenes = [img.url for img in producto.images]
    if not imagenes:
        raise HTTPException(
            status_code=400,
            detail="Este producto no tiene ninguna imagen cargada — Mercado Libre no permite publicar sin imagen.",
        )

    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)
    access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)

    datos_conocidos: dict[str, str] = {}
    if producto.brand:
        datos_conocidos["BRAND"] = producto.brand
    if variante.barcode:
        datos_conocidos["GTIN"] = variante.barcode
        datos_conocidos["EAN"] = variante.barcode
        datos_conocidos["UPC"] = variante.barcode

    adapter = MercadoLibreAdapter(cfg)
    try:
        # Atributos de la categoría, consultados de nuevo en este momento —
        # nunca los que trajo /validar antes (pudieron cambiar).
        try:
            atributos_categoria = await adapter.get_category_attributes(category_id)
        except MercadoLibreRequestError as err:
            if err.status == 404:
                raise HTTPException(status_code=400, detail="La categoría no existe o no es válida.") from err
            raise HTTPException(
                status_code=502,
                detail="No pudimos consultar los atributos de esa categoría en Mercado Libre en este momento.",
            ) from err
        except MercadoLibreAuthError as err:
            raise HTTPException(
                status_code=502,
                detail="No pudimos consultar los atributos de esa categoría en Mercado Libre en este momento.",
            ) from err

        resultado = evaluar_atributos(atributos_categoria, body.condition, datos_conocidos, body.attributes)
        if not resultado.listo_para_publicar:
            faltantes = ", ".join(f.nombre for f in resultado.faltantes)
            raise HTTPException(
                status_code=400,
                detail=f"Faltan atributos obligatorios para publicar: {faltantes}.",
            )

        # Comisión/tipo de publicación resueltos en vivo, en este momento —
        # nunca se confía en LISTING_TYPE_IDS para construir el payload real
        # (ver domain/ml_fees.py::resolver_listing_type).
        try:
            fees_crudo = await adapter.get_listing_fees(
                access_token, account.external_account_site_id, category_id, float(variante.price)
            )
        except (MercadoLibreAuthError, MercadoLibreRequestError) as err:
            raise HTTPException(
                status_code=502,
                detail="No pudimos consultar la comisión de Mercado Libre en este momento. Intentá de nuevo más tarde.",
            ) from err

        listing_type_raw = resolver_listing_type(fees_crudo, body.listing_type)
        if listing_type_raw is None:
            raise HTTPException(
                status_code=400,
                detail=f"Mercado Libre no ofrece el tipo de publicación '{body.listing_type}' para esta categoría/precio ahora mismo.",
            )

        payload = {
            "title": generate_title(nombre=producto.name, marca=producto.brand),
            "category_id": category_id,
            "price": float(variante.price),
            "currency_id": listing_type_raw["currency_id"],
            "available_quantity": variante.marketplace_stock or 0,
            "buying_mode": "buy_it_now",
            "listing_type_id": listing_type_raw["listing_type_id"],
            "pictures": [{"source": url} for url in imagenes],
            "attributes": construir_attributes_payload(resultado),
            "shipping": {"mode": "not_specified"},
        }

        # ---- ejecución real, después de todas las validaciones ----
        try:
            respuesta = await _ejecutar_publicacion_real(adapter, access_token, payload)
        except MercadoLibreAuthError as err:
            # 401/403 de Mercado Libre al publicar — rechazo definitivo, no
            # se creó nada. Nunca se guarda un registro fantasma; el detalle
            # crudo de Mercado Libre queda en el log, nunca en la respuesta.
            logger.error(
                "Mercado Libre rechazó la autenticación en POST /items para variant_id=%s (store_id=%s): %s",
                variante.id, store.id, err,
            )
            raise HTTPException(
                status_code=502, detail="Mercado Libre rechazó la autenticación al publicar. Reconectá la cuenta e intentá de nuevo."
            ) from err
        except MercadoLibreRequestError as err:
            if err.status is not None and err.status < 500:
                # Rechazo explícito de Mercado Libre (ej. 400 por payload
                # inválido) — sabemos con certeza que NO se creó nada.
                # Nunca se expone el JSON/mensaje crudo de Mercado Libre —
                # mismo criterio que el 400 de categoría inexistente en
                # /validar. El detalle completo queda en el log del server.
                logger.error(
                    "Mercado Libre rechazó POST /items para variant_id=%s (store_id=%s): %s",
                    variante.id, store.id, err,
                )
                raise HTTPException(
                    status_code=400,
                    detail="Mercado Libre rechazó los datos de la publicación (categoría, atributos o precio inválidos).",
                ) from err
            # 5xx o timeout/conexión perdida DESPUÉS de mandar el POST: no
            # hay forma de saber con certeza si Mercado Libre llegó a crear
            # el ítem del otro lado. A propósito NUNCA se reintenta
            # automáticamente (POST /items no es idempotente — reintentar
            # podría crear una publicación duplicada) y NUNCA se asume que
            # no se creó — se le devuelve al dueño un mensaje honesto para
            # que lo confirme a mano antes de reintentar.
            logger.error(
                "POST /items para variant_id=%s (store_id=%s) no confirmó resultado: %s",
                variante.id, store.id, err,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Mercado Libre no confirmó si la publicación se creó (error del servidor o de conexión). "
                    "Por seguridad NO reintentamos automáticamente — revisá tu cuenta de Mercado Libre antes "
                    "de volver a intentar, para evitar una publicación duplicada."
                ),
            ) from err
        except _RespuestaMercadoLibreSinItemId as err:
            logger.error(
                "POST /items para variant_id=%s (store_id=%s) respondió sin item_id: %s",
                variante.id, store.id, err,
            )
            raise HTTPException(
                status_code=502,
                detail="Mercado Libre respondió sin confirmar el item_id de la publicación. No se guardó nada.",
            ) from err
    finally:
        await adapter.aclose()

    item_id = respuesta["id"]
    user_product_id = respuesta.get("user_product_id")

    # La publicación YA existe de verdad en Mercado Libre en este punto —
    # si algo falla de acá para abajo, el item_id nunca se oculta (ver
    # excepción más abajo): es la única forma honesta de manejar que no
    # existe una transacción que una el POST externo con este commit local.
    try:
        listing = MarketplaceListing(
            account=account,
            product=producto,
            external_listing_id=str(item_id),
            user_product_id=str(user_product_id) if user_product_id else None,
            status="active",
            title=payload["title"],
            price=variante.price,
            created_at=datetime.now(),
        )
        db.add(listing)
        db.flush()
        db.add(
            MarketplaceListingVariant(
                listing=listing,
                variant=variante,
                price=variante.price,
                stock_quantity=variante.marketplace_stock,
            )
        )
        db.commit()
    except Exception as err:
        db.rollback()
        logger.error(
            "Mercado Libre publicó item_id=%s (user_product_id=%s) para variant_id=%s (store_id=%s) pero Nexo "
            "no pudo guardarlo localmente: %s",
            item_id, user_product_id, variante.id, store.id, err,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Mercado Libre creó la publicación (item_id={item_id}) pero hubo un error al guardarla en Nexo. "
                "La publicación SÍ existe en Mercado Libre — anotá este item_id y contactá soporte antes de "
                "volver a intentar, para no duplicarla."
            ),
        ) from err

    return {
        "itemId": item_id,
        "userProductId": user_product_id,
        "permalink": respuesta.get("permalink"),
        "status": listing.status,
        "listingId": listing.id,
    }
