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
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.api.deps import get_current_store
from app.api.routes.mercadolibre import _build_ml_config, _get_account, _get_valid_access_token, _require_configured
from app.api.routes.rentabilidad import build_profitability_rows, comisiones_ml_cacheadas, resolver_costos_ml
from app.config import get_settings
from app.db.models import ChannelCostSettings, MarketplaceAccount, MarketplaceListing, MarketplaceListingVariant, Product, ProductVariant, Store
from app.db.session import get_db
from app.domain.ai_content import generate_full_description, generate_title
from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.competencia import AnalisisCompetencia, analizar_competencia
from app.domain.decision import evaluar_decision
from app.domain.pricing import ESTADO_RECOMENDACION, RecomendacionPrecio, recomendar_precio
from app.domain.profitability import ChannelCosts
from app.domain.listing_draft import build_draft
from app.domain.listing_validation import (
    RAZONES_GTIN_VACIO_VALIDAS,
    construir_attributes_payload,
    evaluar_atributos,
    gtin_checksum_valido,
)
from app.domain.ml_listing_payload import PayloadPublicacion, construir_payload_publicacion
from app.domain.ml_fees import resolver_listing_type
from app.domain.ml_seller_capabilities import es_user_product_seller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/publicaciones", tags=["publicaciones"])

_NOTA_VALIDACION_NO_ES_AUTORIZACION = (
    "Esta validación no autoriza a publicar — la rentabilidad y los datos se vuelven a verificar al confirmar."
)


def _build_one(db: Session, store: Store, variant_id: int, criteria: SelectionCriteria, filas: Optional[list[dict]] = None) -> Optional[dict]:
    # build_profitability_rows ya scopea por tienda — un variant_id de otra
    # empresa simplemente no aparece en `filas`, así que esto devuelve None
    # (mismo 404 que "no existe") en vez de filtrar antes/después.
    #
    # 31 de agosto de 2026 — hallazgo de backend-architect (ronda de pulido
    # pre-cliente): POST /preparar (el batch de abajo) llamaba a esto una
    # vez POR variant_id, y cada llamada recalculaba build_profitability_rows
    # completo (TODO el catálogo) — O(N×M) en vez de O(M). Ahora quien arma
    # un batch calcula `filas` una sola vez y la pasa; /borrador/{id}
    # (un solo producto) sigue calculándola acá mismo, sin cambios.
    if filas is None:
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
    filas, _ = build_profitability_rows(db, store)

    for variant_id in body.variant_ids:
        borrador = _build_one(db, store, variant_id, criteria, filas=filas)
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

    # max_title_length REAL de la categoría (30 de agosto de 2026, FASE 3)
    # — si no se puede consultar (o no hay categoría sugerida todavía), se
    # usa el default seguro de ai_content.py, nunca un número inventado.
    max_titulo = None
    if categoria_sugerida is not None:
        adapter = MercadoLibreAdapter(cfg)
        try:
            categoria_real = await adapter.get_category(categoria_sugerida["id"])
            max_titulo = (categoria_real.get("settings") or {}).get("max_title_length")
        except (MercadoLibreAuthError, MercadoLibreRequestError):
            max_titulo = None
        finally:
            await adapter.aclose()

    titulo = generate_title(
        nombre=producto.name, marca=producto.brand,
        **({"max_length": max_titulo} if max_titulo else {}),
    )
    descripcion = generate_full_description(
        nombre=producto.name, marca=producto.brand, categoria=producto.category,
        descripcion_original=producto.description, codigo_barras=variante.barcode, variant_label=variante.variant_label,
    )

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
        "titulo": titulo,
        # Revisable antes de publicar (FASE 3) — nunca se manda a Mercado
        # Libre automáticamente todavía, ver PUBLICACION_MERCADOLIBRE.md.
        "descripcionCorta": descripcion.corta,
        "descripcionCompleta": descripcion.completa,
        "caracteristicas": descripcion.caracteristicas,
        "especificaciones": descripcion.especificaciones,
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
            # 31 de agosto de 2026 — mismo campo que rentabilidad.py/_fila,
            # "real"|"manual"|None: para que el paso "Preparar publicación"
            # nunca muestre una comisión estimada como si fuera un dato
            # verificado contra Mercado Libre.
            "comisionMlFuente": fila.get("comisionMlFuente"),
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
            "comisionMlFuente": fila.get("comisionMlFuente"),
        },
        "nota": _NOTA_VALIDACION_NO_ES_AUTORIZACION,
    }


# ------------------------------------------------------------------
# GET /{variant_id}/mercadolibre/competencia — 30 de agosto de 2026, FASE 4
# del roadmap comercial (análisis de competencia). Solo lectura, nunca
# publica ni modifica nada. Cubre el "Caso 2" confirmado oficialmente
# (investigación de mercadolibre-researcher, 30/08/2026): un producto que
# el dueño TODAVÍA NO publicó — GET /products/search para encontrar el
# producto real de catálogo (por GTIN si hay uno válido, si no por
# nombre) + GET /products/{id} para el ganador real (buy_box_winner) y el
# rango real de precios de la competencia (buy_box_winner_price_range).
#
# Deliberadamente NO implementado todavía (documentado como próximo paso,
# no como "no existe"): /suggestions/items/{id}/details y
# price_to_win — ambos exigen que el vendedor YA sea dueño de un ítem
# publicado en Mercado Libre, y Nexo todavía no tiene ninguna publicación
# real (ver "próximo bloqueo" del informe anterior).
# ------------------------------------------------------------------


async def _buscar_producto_en_catalogo(
    adapter: MercadoLibreAdapter, access_token: str, site_id: str, variante: ProductVariant, producto: Product
) -> tuple[Optional[str], Optional[dict]]:
    """GET /products/search + GET /products/{id} — compartido por
    /competencia (FASE 4) y /precio-recomendado (FASE 5), para no tener dos
    formas distintas de encontrar el mismo producto de catálogo. Devuelve
    (None, None) si Mercado Libre no encontró nada — nunca inventa un
    match. Deja subir MercadoLibreAuthError/MercadoLibreRequestError tal
    cual, el caller decide qué responder."""
    if variante.barcode and gtin_checksum_valido(variante.barcode):
        # GTIN real (checksum válido) primero — más preciso que buscar por
        # nombre (evita moderaciones por mala productización, ver
        # documentación oficial de /products/search).
        busqueda = await adapter.search_catalog_products(access_token, site_id, product_identifier=variante.barcode)
    else:
        busqueda = await adapter.search_catalog_products(access_token, site_id, q=producto.name)

    resultados = busqueda.get("results") or []
    if not resultados:
        return None, None

    catalog_product_id = resultados[0].get("id")
    detalle = await adapter.get_catalog_product(access_token, catalog_product_id)
    return catalog_product_id, detalle


@router.get("/{variant_id}/mercadolibre/competencia")
async def analizar_competencia_mercadolibre(
    variant_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    variante, _fila = _variante_de_la_empresa(db, store, variant_id)
    producto = variante.product
    account = _cuenta_ml_conectada(db, store)

    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)
    try:
        access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
    except HTTPException as err:
        # _get_valid_access_token puede incluir texto crudo de Mercado Libre
        # en su detail (falla de refresh) — nunca se lo devolvemos tal cual
        # al frontend (hallazgo de security-engineer, FASE 6, 30/08/2026).
        raise HTTPException(
            status_code=502,
            detail="No pudimos validar la conexión con Mercado Libre en este momento. Intentá de nuevo más tarde.",
        ) from err

    adapter = MercadoLibreAdapter(cfg)
    try:
        try:
            catalog_product_id, detalle = await _buscar_producto_en_catalogo(
                adapter, access_token, account.external_account_site_id, variante, producto
            )
        except (MercadoLibreAuthError, MercadoLibreRequestError) as err:
            raise HTTPException(
                status_code=502,
                detail="No pudimos consultar productos similares en Mercado Libre en este momento. Intentá de nuevo más tarde.",
            ) from err
    finally:
        await adapter.aclose()

    if detalle is None:
        return {"encontrado": False, "catalogProductId": None, "nombreCatalogo": None, "analisis": None}

    analisis = analizar_competencia(
        detalle, precio_propio=float(variante.price) if variante.price is not None else None
    )

    return {
        "encontrado": True,
        "catalogProductId": catalog_product_id,
        "nombreCatalogo": detalle.get("name"),
        "analisis": {
            "hayCompetencia": analisis.hay_competencia,
            "precioGanador": analisis.precio_ganador,
            "monedaGanador": analisis.moneda_ganador,
            "condicionGanador": analisis.condicion_ganador,
            "envioGratisGanador": analisis.envio_gratis_ganador,
            "logisticaGanador": analisis.logistica_ganador,
            "reputacionGanador": analisis.reputacion_ganador,
            "rangoPrecioMinimo": analisis.rango_precio_minimo,
            "rangoPrecioMaximo": analisis.rango_precio_maximo,
            "posicionPrecioPropio": analisis.posicion_precio_propio,
        },
    }


# ------------------------------------------------------------------
# GET /{variant_id}/mercadolibre/precio-recomendado — 30 de agosto de 2026,
# FASE 5 del roadmap comercial. Solo lectura, SOLO RECOMIENDA — nunca
# modifica el precio real de Mercado Libre ni el de Nexo. Reutiliza
# domain/profitability.py (rentabilidad) y domain/competencia.py (FASE 4),
# nunca duplica ninguno de los dos cálculos. El costo/comisión/margen son
# el núcleo (siempre requeridos); la competencia es un agregado opcional —
# si Mercado Libre no está conectado, o no se encuentra el producto en su
# catálogo, la recomendación se sigue calculando igual, solo sin la
# comparación de mercado.
# ------------------------------------------------------------------


async def _resolver_recomendacion_precio(
    db: Session, store: Store, variante: ProductVariant, producto: Product
) -> tuple[RecomendacionPrecio, Optional[AnalisisCompetencia], str]:
    """Calcula la recomendación de precio + el análisis de competencia
    crudo, en un solo lugar — usado tanto por /precio-recomendado como por
    /decision (FASE 6), para no consultar Mercado Libre dos veces ni tener
    dos formas distintas de llegar al mismo resultado. Devuelve el
    AnalisisCompetencia crudo (no solo lo que RecomendacionPrecio guardó de
    él) porque decision.py necesita distinguir "nunca se consultó
    competencia" de "se consultó y no hay ganador".

    31 de agosto de 2026 — la comisión de Mercado Libre que arma
    `channel_costs` ya no es siempre la manual: `resolver_costos_ml`
    (app/api/routes/rentabilidad.py) es la ÚNICA función de todo el
    backend que decide "real vs. manual", reusada acá igual que en
    Rentabilidad/Oportunidades — nunca dos formas distintas de resolver la
    misma comisión para el mismo producto. Se devuelve también la fuente
    ("real"|"manual") para que el frontend nunca la confunda."""
    config_canal = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel="mercadolibre").first()
    channel_costs_manual = ChannelCosts(
        commission_pct=float(config_canal.commission_pct) if config_canal and config_canal.commission_pct is not None else None,
        shipping_cost=float(config_canal.shipping_cost) if config_canal and config_canal.shipping_cost is not None else None,
        other_fixed_cost=float(config_canal.other_fixed_cost) if config_canal and config_canal.other_fixed_cost is not None else None,
    )
    listing_type_pref = config_canal.listing_type_pref if config_canal else None
    precio_actual = float(variante.price) if variante.price is not None else None
    comisiones = comisiones_ml_cacheadas(db, store.id, producto, precio_actual)
    channel_costs, fuente_comision_ml = resolver_costos_ml(comisiones, channel_costs_manual, listing_type_pref)
    margen_objetivo_pct = float(config_canal.target_margin_pct) if config_canal and config_canal.target_margin_pct is not None else None
    margen_minimo_pct = float(config_canal.min_margin_pct) if config_canal and config_canal.min_margin_pct is not None else None

    # Competencia: agregado OPCIONAL — cualquier problema acá (sin cuenta
    # conectada, sin credenciales de la app, Mercado Libre no encontró el
    # producto, error de red) nunca bloquea la recomendación de precio en
    # sí, que no depende de Mercado Libre para nada más que esto.
    analisis_competencia: Optional[AnalisisCompetencia] = None
    account = _get_account(db, store)
    if account is not None and account.status == "connected" and account.external_account_site_id:
        settings = get_settings()
        cfg = _build_ml_config(settings)
        if cfg.is_configured():
            try:
                access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
                adapter = MercadoLibreAdapter(cfg)
                try:
                    _catalog_id, detalle = await _buscar_producto_en_catalogo(
                        adapter, access_token, account.external_account_site_id, variante, producto
                    )
                finally:
                    await adapter.aclose()
                if detalle is not None:
                    analisis_competencia = analizar_competencia(
                        detalle, precio_propio=float(variante.price) if variante.price is not None else None
                    )
            except (HTTPException, MercadoLibreAuthError, MercadoLibreRequestError):
                analisis_competencia = None

    recomendacion = recomendar_precio(
        costo=float(variante.cost_price) if variante.cost_price is not None else None,
        channel_costs=channel_costs,
        margen_objetivo_pct=margen_objetivo_pct,
        margen_minimo_pct=margen_minimo_pct,
        analisis_competencia=analisis_competencia,
    )
    return recomendacion, analisis_competencia, fuente_comision_ml


@router.get("/{variant_id}/mercadolibre/precio-recomendado")
async def precio_recomendado_mercadolibre(
    variant_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    variante, _fila = _variante_de_la_empresa(db, store, variant_id)
    producto = variante.product

    recomendacion, _analisis_competencia, fuente_comision_ml = await _resolver_recomendacion_precio(db, store, variante, producto)

    return {
        # Siempre "RECOMENDACION" — Nexo v1 nunca aplica un cambio de
        # precio real automáticamente, ver PUBLICACION_MERCADOLIBRE.md.
        "tipo": "RECOMENDACION",
        "estado": recomendacion.estado,
        "faltantes": recomendacion.faltantes,
        "precioMinimoRentable": recomendacion.precio_minimo_rentable,
        "precioRecomendado": recomendacion.precio_recomendado,
        "margenEstimadoClp": recomendacion.margen_estimado_clp,
        "margenEstimadoPct": recomendacion.margen_estimado_pct,
        "gananciaEstimada": recomendacion.ganancia_estimada,
        "precioMercadoGanador": recomendacion.precio_mercado_ganador,
        "posicionFrenteACompetencia": recomendacion.posicion_frente_a_competencia,
        "alcanzaMargenObjetivo": recomendacion.alcanza_margen_objetivo,
        "alcanzaMargenMinimo": recomendacion.alcanza_margen_minimo,
        # Hook para FASE 6 ("conviene publicar") — siempre None en V1.
        "clasificacion": recomendacion.clasificacion,
        # 31 de agosto de 2026 — "real" (ya verificada contra Mercado
        # Libre) o "manual" (configuración a mano) — nunca se le muestra al
        # dueño una estimación como si fuera un dato real. None si no se
        # pudo calcular nada (estado == datos_insuficientes).
        "comisionMlFuente": fuente_comision_ml if recomendacion.estado == ESTADO_RECOMENDACION else None,
    }


# ------------------------------------------------------------------
# GET /{variant_id}/mercadolibre/decision — 30 de agosto de 2026, FASE 6
# del roadmap comercial. Motor "¿conviene vender esto?" — SOLO análisis,
# nunca modifica nada en Mercado Libre ni en Nexo (ver domain/decision.py).
# Se construye encima de /precio-recomendado (comparte exactamente el mismo
# cálculo vía _resolver_recomendacion_precio, nunca lo duplica).
# ------------------------------------------------------------------


@router.get("/{variant_id}/mercadolibre/decision")
async def decision_mercadolibre(
    variant_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    variante, _fila = _variante_de_la_empresa(db, store, variant_id)
    producto = variante.product

    recomendacion, analisis_competencia, fuente_comision_ml = await _resolver_recomendacion_precio(db, store, variante, producto)
    decision = evaluar_decision(recomendacion, analisis_competencia)

    competencia_resumen = None
    if analisis_competencia is not None and analisis_competencia.hay_competencia:
        competencia_resumen = {
            "precioGanador": analisis_competencia.precio_ganador,
            "rangoPrecioMinimo": analisis_competencia.rango_precio_minimo,
            "rangoPrecioMaximo": analisis_competencia.rango_precio_maximo,
            "posicionPrecioPropio": recomendacion.posicion_frente_a_competencia,
        }

    return {
        # Nunca publica, nunca modifica precio/stock — solo lectura y
        # cálculo (ver domain/decision.py).
        "tipo": "DECISION",
        "decision": decision.decision,  # "conviene" | "revisar" | "no_conviene"
        "razon": decision.razon,
        "precioRecomendado": decision.precio_recomendado,
        "precioMinimoRentable": decision.precio_minimo_rentable,
        "gananciaEstimada": decision.ganancia_estimada,
        "margenEstimadoPct": decision.margen_estimado_pct,
        "competencia": competencia_resumen,
        "faltantes": decision.faltantes,
        # 31 de agosto de 2026 — "real"|"manual"|None, mismo criterio que
        # /precio-recomendado (comparten _resolver_recomendacion_precio,
        # nunca calculan la comisión de dos formas distintas).
        "comisionMlFuente": fuente_comision_ml if recomendacion.estado == ESTADO_RECOMENDACION else None,
    }


# ------------------------------------------------------------------
# GET /mercadolibre/decision-lote — 30 de agosto de 2026, frontend del
# flujo de decisión. Versión liviana de /decision para pintar una columna
# "Decisión" en una lista de productos: calcula la decisión de negocio para
# TODAS las variantes de la tienda de una sola vez, sin consultar
# competencia (evita N llamadas salientes a Mercado Libre, una por fila).
# Reutiliza domain/pricing.py y domain/decision.py tal cual — cero
# algoritmo nuevo, solo la misma función corrida sin el agregado opcional
# de competencia. decision.py ya sabe responder "revisar" cuando no hay
# suficiente información en vez de asumir nada.
# ------------------------------------------------------------------


@router.get("/mercadolibre/decision-lote")
def decision_lote_mercadolibre(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> list[dict]:
    config_canal = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel="mercadolibre").first()
    channel_costs_manual = ChannelCosts(
        commission_pct=float(config_canal.commission_pct) if config_canal and config_canal.commission_pct is not None else None,
        shipping_cost=float(config_canal.shipping_cost) if config_canal and config_canal.shipping_cost is not None else None,
        other_fixed_cost=float(config_canal.other_fixed_cost) if config_canal and config_canal.other_fixed_cost is not None else None,
    )
    listing_type_pref = config_canal.listing_type_pref if config_canal else None
    margen_objetivo_pct = float(config_canal.target_margin_pct) if config_canal and config_canal.target_margin_pct is not None else None
    margen_minimo_pct = float(config_canal.min_margin_pct) if config_canal and config_canal.min_margin_pct is not None else None

    # 31 de agosto de 2026 — antes armaba su propio ChannelCosts manual acá
    # mismo, en vez de reusar resolver_costos_ml (mismo hallazgo de
    # product-reviewer que _resolver_recomendacion_precio): esta era la
    # razón real por la que la columna "Decisión" de Oportunidades podía
    # contradecir el margen de la misma fila.
    variantes = db.query(ProductVariant).filter_by(store_id=store.id).all()
    resultado = []
    for variante in variantes:
        precio_actual = float(variante.price) if variante.price is not None else None
        comisiones = comisiones_ml_cacheadas(db, store.id, variante.product, precio_actual)
        channel_costs, _fuente = resolver_costos_ml(comisiones, channel_costs_manual, listing_type_pref)
        recomendacion = recomendar_precio(
            costo=float(variante.cost_price) if variante.cost_price is not None else None,
            channel_costs=channel_costs,
            margen_objetivo_pct=margen_objetivo_pct,
            margen_minimo_pct=margen_minimo_pct,
            analisis_competencia=None,
        )
        decision = evaluar_decision(recomendacion, analisis_competencia=None)
        resultado.append({
            "variantId": variante.id,
            "decision": decision.decision,
            "precioRecomendado": decision.precio_recomendado,
            "margenEstimadoPct": decision.margen_estimado_pct,
            "faltantes": decision.faltantes,
        })
    return resultado


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
    # Solo se usa (y se manda a Mercado Libre) si la cuenta es
    # user_product_seller (ver domain/ml_seller_capabilities.py) — 30 de
    # agosto de 2026, soporte User Products. Si no se manda, se calcula un
    # default (título truncado al max_title_length real de la categoría).
    family_name: Optional[str] = Field(default=None, max_length=500)


@dataclass
class ResolucionPublicacion:
    """Todo lo que hace falta para ejecutar (o previsualizar) el POST /items
    real — separado en su propio tipo para que /confirmar y
    /confirmar/preview (30 de agosto de 2026, ver PARTE 5/7 de la auditoría)
    compartan EXACTAMENTE la misma validación y el mismo payload, sin
    duplicar lógica. `access_token` viaja acá porque preview no lo usa
    (nunca llama a create_item), pero /confirmar sí lo necesita después."""

    variante: ProductVariant
    producto: Product
    account: MarketplaceAccount
    es_user_product_seller: bool
    resultado_payload: PayloadPublicacion
    access_token: str


async def _resolver_publicacion(
    db: Session, store: Store, variant_id: int, body: "ConfirmarPublicacionRequest"
) -> tuple[ResolucionPublicacion, MercadoLibreAdapter]:
    """Validación local + construcción del payload — TODO lo que pasa
    ANTES de POST /items, compartido por /confirmar y /confirmar/preview.
    Devuelve también el adapter (todavía abierto): quien llama es
    responsable de cerrarlo (`await adapter.aclose()`), y /confirmar lo
    reusa para el POST real en vez de abrir uno nuevo."""
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
    #
    # 31 de agosto de 2026 — cierre de inconsistencia de negocio (hallazgo
    # propio + revisión de backend-architect/product-reviewer): antes este
    # gate solo bloqueaba margen negativo, nunca el margen mínimo
    # configurado (ChannelCostSettings.min_margin_pct) — "margen_bajo"
    # estaba en la tupla permitida pero era INALCANZABLE (el threshold
    # nunca se pasaba a SelectionCriteria), así que un producto podía
    # publicarse al precio actual con un margen por debajo del piso que el
    # propio dueño configuró. `fila` ya trae el margen al precio ACTUAL de
    # la variante (el que realmente se publica, ver rentabilidad.py/_fila),
    # nunca el precio recomendado — este gate siempre evaluó el precio
    # correcto, solo le faltaba el threshold.
    #
    # Mismo criterio que domain/decision.py regla 3 ("no alcanza margen
    # mínimo -> no_conviene, sin excepción"): un mínimo configurado es un
    # piso de seguridad, no una sugerencia que el paso final pueda saltear
    # en silencio. Si el dueño quiere publicar igual con menos margen (ej.
    # liquidación), la vía correcta es bajar/quitar min_margin_pct en
    # Configuración para ese canal — un dato explícito y auditable, nunca
    # un botón que ignora el piso configurado. Sin min_margin_pct
    # configurado (None), el comportamiento no cambia: classify_product
    # nunca devuelve "margen_bajo" sin threshold, así que el gate sigue
    # bloqueando únicamente por margen negativo, igual que siempre.
    config_canal_gate = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel="mercadolibre").first()
    margen_minimo_pct = float(config_canal_gate.min_margin_pct) if config_canal_gate and config_canal_gate.min_margin_pct is not None else None
    clasificacion = classify_product(
        fila, SelectionCriteria(channel="mercadolibre", require_marketplace_stock=True, min_margin_pct=margen_minimo_pct)
    )
    if clasificacion["clasificacion"] != "rentable":
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

    # 30 de agosto de 2026 — segundo bug real de la prueba end-to-end
    # (Moleskine): un GTIN con checksum inválido llegaba intacto hasta
    # POST /items y recién ahí Mercado Libre lo rechazaba. Se detecta acá,
    # 100% local, ANTES de gastar ningún llamado a Mercado Libre — nunca se
    # corrige el dígito, solo se bloquea con un mensaje accionable.
    if variante.barcode and not gtin_checksum_valido(variante.barcode):
        raise HTTPException(
            status_code=400,
            detail=(
                "El código de barras cargado para este producto no es válido (no pasa el checksum GTIN/EAN) — "
                "corregilo en la ficha del producto antes de publicar."
            ),
        )

    # EMPTY_GTIN_REASON nunca es texto libre inventado — tiene que ser una
    # de las 4 razones reales que Mercado Libre ofrece (ver
    # domain/listing_validation.py::RAZONES_GTIN_VACIO_VALIDAS).
    razon_gtin_vacio = body.attributes.get("EMPTY_GTIN_REASON")
    if razon_gtin_vacio is not None and razon_gtin_vacio not in RAZONES_GTIN_VACIO_VALIDAS.values():
        raise HTTPException(
            status_code=400,
            detail=(
                "El motivo de GTIN vacío tiene que ser una de las opciones reales de Mercado Libre: "
                f"{', '.join(RAZONES_GTIN_VACIO_VALIDAS.values())}."
            ),
        )
    # 30 de agosto de 2026 — Caso D (Nexo todavía no conoce el GTIN) nunca
    # se puede resolver eligiendo "no tiene código registrado" sin que el
    # dueño lo haya confirmado antes, explícitamente, fuera de este mismo
    # request — si no, esa razón se convierte en un atajo para esconder un
    # dato que en realidad falta cargar (ver PUBLICACION_MERCADOLIBRE.md).
    if razon_gtin_vacio == RAZONES_GTIN_VACIO_VALIDAS["17055160"] and not variante.gtin_confirmado_ausente:
        raise HTTPException(
            status_code=400,
            detail=(
                "Datos incompletos: antes de publicar sin código, confirmá explícitamente que este producto "
                "no tiene GTIN (PUT /api/productos/{id}/codigo-barras con confirmarSinCodigo=true) — no elijas "
                "esa razón solo para completar el formulario si todavía no revisaste si el producto tiene uno real."
            ).format(id=variant_id),
        )

    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)
    try:
        access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
    except HTTPException as err:
        # Mismo criterio que /competencia y /precio-recomendado (FASE 6,
        # security-engineer, 30/08/2026): _get_valid_access_token puede
        # incluir texto crudo de Mercado Libre en su detail — nunca se lo
        # devolvemos tal cual al frontend. Hallazgo de la ronda de pulido
        # pre-cliente (31/08/2026): acá faltaba, único call-site de
        # publicaciones.py sin este wrapper. El 401 se preserva (mismo
        # criterio que /importar-ventas en mercadolibre.py) para que el
        # dueño sepa que hay que reconectar la cuenta, no solo reintentar.
        if err.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="El token de Mercado Libre venció y no se pudo renovar. Hay que reconectar la cuenta.",
            ) from err
        raise HTTPException(
            status_code=502,
            detail="No pudimos validar la conexión con Mercado Libre en este momento. Intentá de nuevo más tarde.",
        ) from err

    datos_conocidos: dict[str, str] = {}
    if producto.brand:
        datos_conocidos["BRAND"] = producto.brand
    if variante.barcode:
        datos_conocidos["GTIN"] = variante.barcode
        datos_conocidos["EAN"] = variante.barcode
        datos_conocidos["UPC"] = variante.barcode

    adapter = MercadoLibreAdapter(cfg)
    # ¿Esta cuenta ya está migrada al modelo User Products de Mercado
    # Libre? SIEMPRE se consulta fresco acá — nunca se cachea en
    # MarketplaceAccount — porque si Mercado Libre migra la cuenta
    # entre dos publicaciones, un valor cacheado seguiría mandando el
    # payload viejo (title) y Mercado Libre lo rechazaría (confirmado
    # en la prueba real del 30 de agosto de 2026: 400 "family_name"
    # requerido).
    try:
        user_info = await adapter.get_user_info(access_token)
    except (MercadoLibreAuthError, MercadoLibreRequestError) as err:
        await adapter.aclose()
        raise HTTPException(
            status_code=502,
            detail="No pudimos verificar el estado de tu cuenta de Mercado Libre en este momento. Intentá de nuevo más tarde.",
        ) from err
    es_up = es_user_product_seller(user_info)

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

        # es_user_product_seller=es_up: bajo User Products, un atributo
        # PARENT_PK (ej. MODEL) se trata como obligatorio aunque la
        # categoría solo lo marque catalog_required — ver
        # domain/listing_validation.py::_es_requerido.
        resultado = evaluar_atributos(
            atributos_categoria, body.condition, datos_conocidos, body.attributes, es_user_product_seller=es_up
        )
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

        titulo_generado = generate_title(nombre=producto.name, marca=producto.brand)

        family_name = body.family_name
        if es_up and not family_name:
            # Default: el título que Nexo ya calculó, truncado al
            # max_title_length REAL de la categoría — nunca un número
            # inventado. Este llamado solo se hace en esta rama puntual
            # (cuenta user_product_seller SIN family_name explícito) para
            # no sumar una llamada de más en el camino común (legacy).
            try:
                categoria = await adapter.get_category(category_id)
            except (MercadoLibreAuthError, MercadoLibreRequestError) as err:
                raise HTTPException(
                    status_code=502,
                    detail="No pudimos consultar los datos de esa categoría en Mercado Libre en este momento.",
                ) from err
            max_len = (categoria.get("settings") or {}).get("max_title_length")
            # Reusa generate_title solo para el truncado (con "…" si hace
            # falta) — sin marca/modelo, titulo_generado ya los tiene.
            family_name = generate_title(nombre=titulo_generado, max_length=max_len) if max_len else titulo_generado

        resultado_payload: PayloadPublicacion = construir_payload_publicacion(
            titulo=titulo_generado,
            category_id=category_id,
            price=float(variante.price),
            currency_id=listing_type_raw["currency_id"],
            available_quantity=variante.marketplace_stock or 0,
            listing_type_id=listing_type_raw["listing_type_id"],
            pictures=[{"source": url} for url in imagenes],
            attributes=construir_attributes_payload(resultado),
            es_user_product_seller=es_up,
            family_name=family_name,
        )
    except Exception:
        await adapter.aclose()
        raise

    return (
        ResolucionPublicacion(
            variante=variante, producto=producto, account=account,
            es_user_product_seller=es_up, resultado_payload=resultado_payload, access_token=access_token,
        ),
        adapter,
    )


def _preview_sanitizado(resolucion: ResolucionPublicacion) -> dict:
    """Payload que se PIENSA mandar — nunca token/refresh_token/client
    secret/cookies/credenciales (30 de agosto de 2026, PARTE 5 de la
    auditoría). Todo lo que devuelve viene del payload ya construido, no
    hay ningún camino por el que un secreto pueda colarse acá."""
    payload = resolucion.resultado_payload.payload
    atributos_por_id = {a["id"]: a.get("value_name") for a in payload["attributes"]}
    account = resolucion.account
    return {
        "seller": {"nickname": account.external_account_nickname, "siteId": account.external_account_site_id},
        "userProductSeller": resolucion.es_user_product_seller,
        "categoryId": payload["category_id"],
        "familyName": payload.get("family_name"),
        "title": payload.get("title"),
        "model": atributos_por_id.get("MODEL"),
        "gtin": atributos_por_id.get("GTIN") or atributos_por_id.get("EAN") or atributos_por_id.get("UPC"),
        "emptyGtinReason": atributos_por_id.get("EMPTY_GTIN_REASON"),
        "price": payload["price"],
        "currencyId": payload["currency_id"],
        "availableQuantity": payload["available_quantity"],
        "listingTypeId": payload["listing_type_id"],
        "pictures": payload["pictures"],
        "attributes": payload["attributes"],
        "shipping": payload["shipping"],
    }


@router.post("/{variant_id}/mercadolibre/confirmar/preview")
async def preview_publicacion_mercadolibre(
    variant_id: int, body: ConfirmarPublicacionRequest, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    """Corre EXACTAMENTE la misma validación local + construcción de
    payload que /confirmar — pero nunca llega a POST /items. Para poder
    inspeccionar el payload real antes de autorizar la publicación (30 de
    agosto de 2026, ver PARTE 5/7 de la auditoría de User Products)."""
    resolucion, adapter = await _resolver_publicacion(db, store, variant_id, body)
    await adapter.aclose()
    return _preview_sanitizado(resolucion)


@router.post("/{variant_id}/mercadolibre/confirmar")
async def confirmar_publicacion_mercadolibre(
    variant_id: int,
    body: ConfirmarPublicacionRequest,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    resolucion, adapter = await _resolver_publicacion(db, store, variant_id, body)
    variante = resolucion.variante
    producto = resolucion.producto
    account = resolucion.account
    access_token = resolucion.access_token
    payload = resolucion.resultado_payload.payload

    try:
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
            # El título real: bajo el modelo User Products, Mercado Libre
            # lo genera y lo devuelve en la RESPUESTA (nunca en `payload`,
            # que en esa rama no tiene la clave "title" — ver
            # domain/ml_listing_payload.py). Se usa el de la respuesta
            # cuando viene; si no, el que Nexo calculó localmente.
            title=respuesta.get("title") or resolucion.resultado_payload.titulo_local,
            family_name=payload.get("family_name"),
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
    except IntegrityError as err:
        # 30 de agosto de 2026 — red de seguridad real (hallazgo de
        # qa-engineer) contra la carrera de dos requests casi simultáneas
        # para el mismo producto: el chequeo de "¿ya publicado?" de más
        # arriba es un SELECT sin lock, así que las dos pueden pasarlo y
        # las dos pueden llegar a ejecutar el POST /items real contra
        # Mercado Libre. Esta constraint (uq_listing_account_product) no
        # puede evitar ESE POST real duplicado del lado de Mercado Libre
        # — ya se ejecutó, arriba, antes de este bloque — pero sí evita
        # que Nexo termine con dos registros locales silenciosos, y le
        # avisa al dueño con un mensaje honesto para que revise su cuenta.
        db.rollback()
        logger.error(
            "Mercado Libre publicó item_id=%s (user_product_id=%s) para variant_id=%s (store_id=%s) pero ya "
            "existía un registro local para esta cuenta/producto (carrera de doble publicación): %s",
            item_id, user_product_id, variante.id, store.id, err,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Mercado Libre creó una publicación (item_id={item_id}) pero Nexo ya tenía otra publicación "
                "registrada para este producto — probablemente se enviaron dos solicitudes de publicación al "
                "mismo tiempo. Revisá tu cuenta de Mercado Libre: es posible que haya quedado una publicación "
                "duplicada que tengas que pausar o cerrar a mano."
            ),
        ) from err
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
