"""
GET /api/rentabilidad — el reporte que pidió el dueño el 22 de agosto de
2026: no solo qué se vende, sino qué CONVIENE vender, y por qué canal.

Usa domain/profitability.py para todos los cálculos — este archivo solo
arma las filas (join Product + ProductVariant + ChannelCostSettings) y las
ordena. Nunca calcula un margen acá directamente.

Reglas heredadas de profitability.py (ver ese archivo para el detalle):
- Producto sin costo cargado -> sin margen, en ningún canal.
- Canal sin costos configurados -> sin margen neto para ese canal (no se
  asume ninguna comisión).

La respuesta va envuelta en "resumen" + "productos" (24 de agosto de 2026,
a pedido del dueño): mientras no haya costos ni canales configurados, el
sistema no debe mostrar números — debe decir claramente "todavía no hay
datos". `resumen.productosConCosto === 0` es exactamente la condición que
el frontend (cuando exista esa pantalla) necesita para pintar el aviso
"⚠️ Aún no hay costos de compra cargados" en vez de una tabla vacía o, peor,
una tabla con márgenes inventados.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_store
from app.db.models import (
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    MercadoLibreCategoryFee,
    MercadoLibreShippingEstimate,
    Product,
    ProductVariant,
    Store,
)
from app.domain.ml_shipping import (
    DIAS_VIGENCIA_ESTIMACION_ENVIO,
    MOTIVO_BAJO_EL_MINIMO_DEL_DUENO,
    MOTIVO_ESTIMACION_NO_CONSULTADA,
    MOTIVO_CATEGORIA_SIN_MERCADO_ENVIOS,
    MOTIVO_ENVIO_NO_OBLIGATORIO,
    MOTIVO_ESTIMACION_VENCIDA,
    MOTIVO_NO_CONSULTADO,
    MOTIVO_NO_PUBLICADO,
    MOTIVO_PUBLICACION_CERRADA,
)
from app.db.session import get_db
from app.domain.ml_fees import (
    LISTING_TYPE_IDS,
    TIPO_PUBLICACION_LABEL,
    ListingFee,
    elegir_comision_principal,
    recomendar_tipo_publicacion,
)
from app.domain.profitability import ChannelCosts, gross_margin, gross_margin_pct, net_margin, net_margin_pct

router = APIRouter(prefix="/api/rentabilidad", tags=["rentabilidad"])

# Canal implícito: la tienda física no cobra comisión ni envío sobre sus
# propias ventas (ver channel_costs.py) — no necesita una fila en la BD.
CHANNEL_MERCADO_LIBRE = "mercadolibre"

_LISTING_TYPE_ID_A_CLAVE = {v: k for k, v in LISTING_TYPE_IDS.items()}


def comisiones_ml_cacheadas(db: Session, store_id: int, producto: Product, precio: float | None) -> dict[str, ListingFee]:
    """31 de agosto de 2026 — único lookup a MercadoLibreCategoryFee de todo
    este archivo (store_id + category_id + price EXACTO, nunca aproximado
    ni interpolado): tanto _comision_ml_real (comparación Clásica/Premium,
    informativa) como resolver_costos_ml (single source of truth para
    calcular) parten de este mismo dict — antes cada una hacía su propia
    consulta idéntica. {} si el producto no tiene categoría de ML detectada
    o no hay nada cacheado para su precio actual — nunca se inventa."""
    if not producto.ml_category_id or precio is None:
        return {}
    filas = (
        db.query(MercadoLibreCategoryFee)
        .filter_by(store_id=store_id, category_id=producto.ml_category_id, price=precio)
        .all()
    )
    comisiones: dict[str, ListingFee] = {}
    for fila in filas:
        clave = _LISTING_TYPE_ID_A_CLAVE.get(fila.listing_type_id)
        if clave is None:
            continue
        comisiones[clave] = ListingFee(
            listing_type_name=fila.listing_type_id,
            percentage_fee=float(fila.percentage_fee),
            fixed_fee=float(fila.fixed_fee),
            sale_fee_amount=float(fila.sale_fee_amount),
        )
    return comisiones


_ESTADOS_PUBLICACION_VIVA = ("active", "paused")


def publicaciones_ml_por_producto(
    db: Session, store_id: int, product_ids: list[int] | None = None, estados: tuple[str, ...] = _ESTADOS_PUBLICACION_VIVA
) -> dict[int, MarketplaceListing]:
    """Publicación viva de Mercado Libre de cada producto de ESTA empresa
    (como máximo una por producto, ver uq_listing_account_product)."""
    consulta = (
        db.query(MarketplaceListing)
        .join(MarketplaceAccount, MarketplaceAccount.id == MarketplaceListing.account_id)
        .filter(
            MarketplaceAccount.store_id == store_id,
            MarketplaceAccount.marketplace == CHANNEL_MERCADO_LIBRE,
            MarketplaceListing.status.in_(estados),
        )
    )
    if product_ids is not None:
        consulta = consulta.filter(MarketplaceListing.product_id.in_(product_ids))
    return {p.product_id: p for p in consulta.all()}


def estimacion_envio_vigente(estimacion: MercadoLibreShippingEstimate | None) -> bool:
    """16 de septiembre de 2026 — una estimación de envío más vieja que
    DIAS_VIGENCIA_ESTIMACION_ENVIO no se usa para calcular rentabilidad: si la
    actualización todavía no pudo correr (Mercado Libre caído, cuenta
    desconectada), el envío vuelve a ser dato faltante — nunca se muestra una
    tarifa vencida como si fuera la de hoy."""
    if estimacion is None or estimacion.fetched_at is None:
        return False
    return estimacion.fetched_at >= datetime.now() - timedelta(days=DIAS_VIGENCIA_ESTIMACION_ENVIO)


def estimaciones_envio_cacheadas(db: Session, store_id: int) -> dict[tuple[str, float], MercadoLibreShippingEstimate]:
    """Estimaciones de envío ya consultadas (categoría + precio exacto), ver
    services/ml_comisiones.py. Un solo lookup para toda la lista de productos.
    Si una quedó vencida, la descarta aplicar_envio_real_ml (único lugar que
    resuelve el envío), no esta consulta."""
    return {
        (e.category_id, float(e.price)): e
        for e in db.query(MercadoLibreShippingEstimate).filter_by(store_id=store_id).all()
    }


def estimacion_envio_cacheada(
    db: Session, store_id: int, category_id: str | None, precio: float | None
) -> MercadoLibreShippingEstimate | None:
    """La estimación de UN producto (misma caché que estimaciones_envio_cacheadas)."""
    if not category_id or precio is None:
        return None
    return (
        db.query(MercadoLibreShippingEstimate)
        .filter_by(store_id=store_id, category_id=category_id, price=precio)
        .first()
    )


def aplicar_envio_real_ml(
    costos: ChannelCosts,
    publicacion: MarketplaceListing | None,
    publicacion_cerrada: bool = False,
    *,
    precio: float | None = None,
    envio_desde_clp: float | None = None,
    estimacion: MercadoLibreShippingEstimate | None = None,
) -> tuple[ChannelCosts, dict]:
    """14 de septiembre de 2026 — costo de envío del cálculo de rentabilidad
    de Mercado Libre. Orden de prioridad:

    1. El costo REAL que informó Mercado Libre para la publicación existente
       (services/ml_shipping_sync.py).
    2. 16 de septiembre de 2026 (pedido del dueño: "que al analizar el margen
       también analice el envío"): la ESTIMACIÓN de Mercado Libre para la
       categoría y el precio del producto, consultada antes de publicar (ver
       services/ml_comisiones.py). Solo se descuenta si a ese precio el envío
       gratis es obligatorio — si no, lo paga el comprador y el costo es $0.
    3. El envío manual de Configuración YA NO completa el cálculo: es un
       promedio del dueño, no el envío de esta publicación, así que deja de
       decidir "conviene / no conviene" (antes el margen salía marcado solo
       como "provisional", con veredicto igual).

    Nunca inventa un valor. `envioMlResuelto` dice si el envío del cálculo ya
    está resuelto: real, estimado, o confirmado que no corre por cuenta del
    vendedor (un $0 de verdad). Con False el envío es DATO FALTANTE y la
    rentabilidad de Mercado Libre no se puede determinar — los costos vuelven
    con shipping_unknown=True, así net_margin devuelve None en vez de calcular
    con un envío $0 supuesto, y classify_product responde "Faltan datos" en
    lugar de "Conviene" o "No conviene" (16 de septiembre de 2026, regla
    estricta del dueño: "no puedes ver el envío antes de decir si es
    conveniente o no").

    Devuelve los costos a usar + los campos de envío para la respuesta."""
    if publicacion is not None and publicacion.shipping_cost is not None:
        real = float(publicacion.shipping_cost)
        return replace(costos, shipping_cost=real), {
            "costoEnvioMl": real,
            "envioMlFuente": "mercadolibre",
            "envioMlMotivo": None,
            "envioMlResuelto": True,
            "envioMlActualizadoEn": publicacion.shipping_synced_at.isoformat() if publicacion.shipping_synced_at else None,
        }
    if publicacion is None:
        # Sin publicación viva: distinguir "nunca se publicó" de "existe pero
        # está cerrada en Mercado Libre" (solo cambia el texto, no el costo).
        motivo = MOTIVO_PUBLICACION_CERRADA if publicacion_cerrada else MOTIVO_NO_PUBLICADO
    else:
        motivo = publicacion.shipping_cost_unavailable_reason or MOTIVO_NO_CONSULTADO

    actualizado_en = publicacion.shipping_synced_at.isoformat() if publicacion is not None and publicacion.shipping_synced_at else None
    if estimacion is not None and not estimacion_envio_vigente(estimacion):
        # Vencida y todavía sin poder actualizarse: no se usa una tarifa vieja
        # como si fuera la de hoy — vuelve a ser dato faltante.
        estimacion, motivo = None, MOTIVO_ESTIMACION_VENCIDA
    if estimacion is not None:
        # El dueño puede decir desde qué precio paga él el envío: bajo ese
        # precio no se descuenta, aunque Mercado Libre estime un costo.
        bajo_el_minimo_del_dueno = envio_desde_clp is not None and precio is not None and precio < envio_desde_clp
        if estimacion.shipping_cost is not None and estimacion.mandatory and not bajo_el_minimo_del_dueno:
            estimado = float(estimacion.shipping_cost)
            return replace(costos, shipping_cost=estimado), {
                "costoEnvioMl": estimado,
                "envioMlFuente": "estimado_ml",
                "envioMlMotivo": None,
                    "envioMlResuelto": True,
                "envioMlActualizadoEn": estimacion.fetched_at.isoformat() if estimacion.fetched_at else None,
            }
        if estimacion.shipping_cost is not None or estimacion.unavailable_reason == MOTIVO_CATEGORIA_SIN_MERCADO_ENVIOS:
            # Envío que NO corre por cuenta del vendedor a este precio: el
            # margen ya está completo, no es provisional.
            return replace(costos, shipping_cost=0.0), {
                "costoEnvioMl": None,
                "envioMlFuente": "no_disponible",
                "envioMlMotivo": MOTIVO_CATEGORIA_SIN_MERCADO_ENVIOS
                if estimacion.shipping_cost is None
                else (MOTIVO_BAJO_EL_MINIMO_DEL_DUENO if bajo_el_minimo_del_dueno else MOTIVO_ENVIO_NO_OBLIGATORIO),
                "envioMlResuelto": True,
                "envioMlActualizadoEn": estimacion.fetched_at.isoformat() if estimacion.fetched_at else None,
            }
        motivo = estimacion.unavailable_reason or motivo

    if estimacion is None and motivo == MOTIVO_NO_PUBLICADO:
        # "Todavía no está publicado" explica por qué no hay costo REAL, pero
        # como razón para el dueño confunde (parecería que hay que publicar a
        # ciegas para saber si conviene): lo que falta es la consulta del
        # envío estimado — eso es lo que se le dice, y para eso está el botón
        # "Actualizar envíos".
        motivo = MOTIVO_ESTIMACION_NO_CONSULTADA
    # Dato faltante: ni el envío real de la publicación, ni una estimación
    # vigente de Mercado Libre. El envío manual de Configuración no ocupa este
    # lugar (ver docstring), y el $0 tampoco: shipping_unknown corta el cálculo
    # del margen neto río abajo en vez de descontar cero.
    return replace(costos, shipping_cost=None, shipping_unknown=True), {
        "costoEnvioMl": None,
        "envioMlFuente": "no_disponible",
        "envioMlMotivo": motivo,
        "envioMlResuelto": False,
        "envioMlActualizadoEn": actualizado_en,
    }


def _comision_ml_real(comisiones: dict[str, ListingFee], costo: float | None, precio: float | None, costos_manual: ChannelCosts) -> dict | None:
    """Comisión REAL de Mercado Libre (Clásica/Premium) para ESTA variante a
    este precio exacto, si ya se consultó antes (ver POST
    /api/mercadolibre/comisiones/recalcular — acá nunca se llama a la API
    de Mercado Libre, solo se lee la caché). `comisiones` viene ya resuelto
    por comisiones_ml_cacheadas (no vuelve a consultar la BD). None si no
    hay ningún dato cacheado para su precio actual — nunca se inventa ni se
    aproxima con otro precio.

    31 de agosto de 2026 — hallazgo de backend-architect (ronda de pulido
    pre-cliente): antes recibía `producto` y usaba
    `producto.variants[0].cost_price` (el costo de la PRIMERA variante)
    para TODAS las variantes del producto — en un producto con 2+
    variantes, la fila de la variante #2 en adelante mostraba acá un
    margenClp/margenPct calculado con el costo equivocado, distinto al
    margenMercadoLibreClp/Pct de la misma fila (que sí usa el costo
    correcto). Ahora recibe directamente el costo de la variante que
    corresponde a esta fila, igual que el resto de _fila."""
    if not comisiones:
        return None

    resultado: dict = {}
    for clave, fee in comisiones.items():
        costos_reales = ChannelCosts(
            commission_pct=fee.percentage_fee,
            shipping_cost=costos_manual.shipping_cost,
            other_fixed_cost=(costos_manual.other_fixed_cost or 0.0) + fee.fixed_fee,
            # Si el envío quedó como desconocido, sigue desconocido acá: este
            # detalle (Clásica/Premium) no puede dar un margen que el resto de
            # la aplicación no puede dar.
            shipping_unknown=costos_manual.shipping_unknown,
        )
        resultado[clave] = {
            "nombre": fee.listing_type_name,
            "comisionPct": fee.percentage_fee,
            "comisionFija": fee.fixed_fee,
            "comisionTotal": fee.sale_fee_amount,
            "margenClp": net_margin(precio, costo, costos_reales),
            "margenPct": net_margin_pct(precio, costo, costos_reales),
        }
    return resultado or None


def preferencia_efectiva(
    listing_type_pref: str | None,
    precio: float | None,
    costo: float | None,
    comisiones: dict[str, ListingFee],
    costos: ChannelCosts,
    target_margin_pct: float | None,
):
    """Tipo de publicación con el que se calcula el margen de Mercado Libre.
    Con preferencia manual (Clásica/Premium), esa. Sin preferencia, el tipo
    que recomienda recomendar_tipo_publicacion con la comisión REAL de cada
    uno. 15 de septiembre de 2026 — revisión por perfil: antes solo
    Rentabilidad hacía esta elección; ¿Conviene?, el precio recomendado y la
    decisión en lote caían a la comisión manual. Devuelve (preferencia,
    recomendación o None)."""
    if listing_type_pref is not None or precio is None:
        return listing_type_pref, None
    recomendacion = recomendar_tipo_publicacion(
        precio,
        costo if costo is not None else 0.0,  # sin costo registrado: costo considerado $0
        comisiones,
        shipping_cost=costos.shipping_cost or 0.0,
        other_fixed_cost=costos.other_fixed_cost or 0.0,
        target_margin_pct=target_margin_pct,
    )
    return (recomendacion.tipo if recomendacion else None), recomendacion


def resolver_costos_ml(
    comisiones: dict[str, ListingFee], costos_manual: ChannelCosts, listing_type_pref: str | None
) -> tuple[ChannelCosts, str]:
    """ÚNICA función de todo el backend que decide "comisión real vs.
    manual" — la usan build_profitability_rows (Rentabilidad/Oportunidades)
    y app/api/routes/publicaciones.py (/precio-recomendado, /decision,
    /decision-lote) para que los lugares donde el dueño ve un margen de
    Mercado Libre calculen siempre el mismo número para el mismo producto.
    `comisiones` viene ya resuelto por comisiones_ml_cacheadas — esta
    función es pura (sin DB), así ningún caller repite el mismo lookup dos
    veces para el mismo producto (ver _fila, que necesita tanto esto como
    _comision_ml_real). Regla (pedido explícito del dueño, 31 de agosto de
    2026): la comisión REAL ya verificada contra Mercado Libre gana siempre
    que exista y haya una preferencia Clásica/Premium configurada; la
    manual (ChannelCostSettings) es el fallback explícito — sin
    listing_type_pref configurado, elegir_comision_principal
    (domain/ml_fees.py) nunca elige por el dueño y cae acá al manual.
    Nunca inventa un número: sin ninguna de las dos, devuelve la manual tal
    cual (puede venir vacía — ChannelCosts.is_configured() ya sabe manejar
    eso, cae en "datos_insuficientes" río abajo). Devuelve también la
    fuente ("real"|"manual") para que el frontend nunca muestre una
    estimación como si fuera un dato real."""
    principal = elegir_comision_principal(comisiones, listing_type_pref)
    if principal is not None:
        return (
            ChannelCosts(
                commission_pct=principal.percentage_fee,
                shipping_cost=costos_manual.shipping_cost,
                other_fixed_cost=(costos_manual.other_fixed_cost or 0.0) + principal.fixed_fee,
                # La comisión real no vuelve conocido un envío que no lo es.
                shipping_unknown=costos_manual.shipping_unknown,
            ),
            "real",
        )
    return costos_manual, "manual"


def _fila(
    db: Session,
    store_id: int,
    producto: Product,
    variante: ProductVariant,
    costos_ml_manual: ChannelCosts,
    listing_type_pref: str | None,
    target_margin_pct: float | None = None,
    publicacion_ml: MarketplaceListing | None = None,
    publicacion_ml_cerrada: bool = False,
    envio_desde_clp: float | None = None,
    estimacion_envio: MercadoLibreShippingEstimate | None = None,
) -> dict:
    precio = float(variante.price) if variante.price is not None else None
    costo = float(variante.cost_price) if variante.cost_price is not None else None
    # 15 de septiembre de 2026 — sin costo de compra registrado (un producto que
    # la empresa ya tiene, ej. un repuesto retirado) el costo considerado es $0:
    # la ganancia es lo que queda después de comisión, envío y otros costos.
    # `costo` sigue en None en la respuesta ("Sin registrar", tieneCosto=False).
    costo_calculo = costo if costo is not None else 0.0

    comisiones = comisiones_ml_cacheadas(db, store_id, producto, precio)
    costos_ml_manual, envio_ml = aplicar_envio_real_ml(
        costos_ml_manual, publicacion_ml, publicacion_ml_cerrada, precio=precio, envio_desde_clp=envio_desde_clp,
        estimacion=estimacion_envio,
    )

    # Elección AUTOMÁTICA del tipo de publicación (14 de septiembre de 2026),
    # ver preferencia_efectiva: sin preferencia manual, el tipo recomendado
    # pasa a ser la preferencia efectiva y el margen usa la comisión real.
    pref_efectiva, recomendacion = preferencia_efectiva(
        listing_type_pref, precio, costo, comisiones, costos_ml_manual, target_margin_pct
    )

    costos_ml_efectivos, fuente_comision_ml = resolver_costos_ml(comisiones, costos_ml_manual, pref_efectiva)
    # 16 de septiembre de 2026 — el canal está en condiciones de dar un margen
    # cuando se conoce su COMISIÓN (real o manual). Antes bastaba con que
    # hubiera cualquier costo cargado, así que un envío resuelto en $0 alcanzaba
    # para mostrar un margen calculado con una comisión de 0 % que nadie
    # configuró (ver domain/profitability.py::net_margin).
    ml_configurado = costos_ml_efectivos.commission_pct is not None

    return {
        "id": variante.id,
        "sku": variante.variant_sku or "",
        "nombre": f"{producto.name} - {variante.variant_label}" if variante.variant_label else producto.name,
        "precio": precio,
        "costo": costo,
        "tieneCosto": costo is not None,
        # Tope de unidades reservadas para Mercado Libre — lo necesita
        # domain/catalog_selection.py para saber si hay algo que publicar,
        # sin confundirlo con el stock físico (ver domain/marketplace_stock.py).
        "marketplaceStock": variante.marketplace_stock,
        "margenTiendaClp": gross_margin(precio, costo_calculo),
        "margenTiendaPct": gross_margin_pct(precio, costo_calculo),
        "mercadoLibreConfigurado": ml_configurado,
        "margenMercadoLibreClp": net_margin(precio, costo_calculo, costos_ml_efectivos),
        "margenMercadoLibrePct": net_margin_pct(precio, costo_calculo, costos_ml_efectivos),
        # Costo de envío de Mercado Libre y su origen ("mercadolibre" =
        # el real de la publicación | "estimado_ml" = estimado para la
        # categoría y el precio | "no_disponible"), ver aplicar_envio_real_ml.
        # Sin envío resuelto (envioMlResuelto False) el margen de arriba es
        # None y la clasificación es "Faltan datos" — nunca un veredicto
        # calculado con un envío supuesto de $0.
        **envio_ml,
        # Estado de la publicación de Mercado Libre de este producto
        # ("active" | "paused" | "closed" | None = nunca publicado): Oportunidades
        # muestra los ya publicados en su propia sección, no como oportunidad.
        "publicacionMlEstado": publicacion_ml.status if publicacion_ml is not None else ("closed" if publicacion_ml_cerrada else None),
        # 31 de agosto de 2026 — de qué fuente sale la comisión usada en
        # margenMercadoLibreClp/Pct de ARRIBA ("real"|"manual"), None si no
        # hay ninguna. Nunca confundir con comisionMlReal de abajo, que es
        # el detalle informativo Clásica+Premium (puede tener datos aunque
        # acá el resultado sea "manual", si no hay listing_type_pref
        # configurado — ver resolver_costos_ml).
        "comisionMlFuente": fuente_comision_ml if ml_configurado else None,
        # Comisión REAL de Mercado Libre (29 de agosto de 2026, a pedido del
        # dueño: "la comisión varía por producto") — Clásica y Premium en
        # paralelo, para decidir cuál conviene. None hasta que se corra
        # POST /api/mercadolibre/comisiones/recalcular; nunca se calcula acá
        # con un valor estimado.
        "comisionMlReal": _comision_ml_real(comisiones, costo_calculo, precio, costos_ml_manual),
        # Tipo de publicación que el sistema recomienda para ESTE producto
        # (Clásica/Premium), elegido solo por margen con la comisión exacta —
        # None si hay preferencia manual o si no hay comisión real todavía.
        "tipoPublicacionRecomendado": recomendacion.tipo if recomendacion else None,
        "tipoPublicacionRecomendadoLabel": TIPO_PUBLICACION_LABEL.get(recomendacion.tipo) if recomendacion else None,
        "tipoPublicacionRazon": recomendacion.razon if recomendacion else None,
        "mlCategoriaId": producto.ml_category_id,
        "mlCategoriaNombre": producto.ml_category_name,
    }


def build_profitability_rows(db: Session, store: Store) -> tuple[list[dict], bool]:
    """Arma las mismas filas que devuelve GET /api/rentabilidad — factorizado
    acá para que app/api/routes/seleccion.py y publicaciones.py las reusen
    sin duplicar la consulta ni el cálculo de márgenes.

    `store` viene SIEMPRE de la sesión autenticada (ver
    app/api/deps.py:get_current_store) — nunca se vuelve a resolver "la
    primera tienda que exista" acá adentro. Con auth obligatorio en todos
    los endpoints que llaman a esto, no existe un caso real de "request
    válida sin tienda" — un usuario logueado siempre tiene una (ver
    POST /api/auth/registro)."""
    config_ml = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel=CHANNEL_MERCADO_LIBRE).first()
    costos_ml = ChannelCosts(
        commission_pct=float(config_ml.commission_pct) if config_ml and config_ml.commission_pct is not None else None,
        shipping_cost=float(config_ml.shipping_cost) if config_ml and config_ml.shipping_cost is not None else None,
        other_fixed_cost=float(config_ml.other_fixed_cost) if config_ml and config_ml.other_fixed_cost is not None else None,
    )
    ml_configurado = costos_ml.is_configured()

    listing_type_pref = config_ml.listing_type_pref if config_ml else None
    envio_desde = float(config_ml.shipping_min_price_clp) if config_ml and config_ml.shipping_min_price_clp is not None else None
    target_margin_pct = (
        float(config_ml.target_margin_pct) if config_ml and config_ml.target_margin_pct is not None else None
    )
    # QA fase 2 (15/09/2026): variantes en una consulta, no una por producto.
    productos = db.query(Product).options(selectinload(Product.variants)).filter_by(store_id=store.id).order_by(Product.name).all()
    publicaciones_ml = publicaciones_ml_por_producto(db, store.id)
    publicaciones_ml_cerradas = publicaciones_ml_por_producto(db, store.id, estados=("closed",))
    estimaciones_envio = estimaciones_envio_cacheadas(db, store.id)
    filas = [
        _fila(
            db, store.id, producto, variante, costos_ml, listing_type_pref, target_margin_pct,
            publicaciones_ml.get(producto.id), producto.id in publicaciones_ml_cerradas, envio_desde,
            estimaciones_envio.get((producto.ml_category_id, float(variante.price))) if producto.ml_category_id and variante.price is not None else None,
        )
        for producto in productos
        for variante in producto.variants
    ]
    return filas, ml_configurado


@router.get("")
def reporte_rentabilidad(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    filas, ml_configurado = build_profitability_rows(db, store)

    # Prioriza lo que más conviene (mayor margen en tienda) primero; lo que
    # todavía no tiene costo cargado va al final, no se mezcla ordenado como
    # si valiera $0 (eso lo haría parecer lo menos rentable, y no lo sabemos).
    # 15 de septiembre de 2026 (QA integral): un producto con costo pero SIN
    # precio tiene margenTiendaClp None y rompía este orden (error 500 en toda
    # la pantalla). Sin margen calculable va al final, igual que sin costo.
    con_margen = sorted((f for f in filas if f["margenTiendaClp"] is not None), key=lambda f: f["margenTiendaClp"], reverse=True)
    sin_margen = [f for f in filas if f["margenTiendaClp"] is None]

    return {
        "resumen": {
            "totalProductos": len(filas),
            "productosConCosto": sum(1 for f in filas if f["tieneCosto"]),
            "canalesConfigurados": [CHANNEL_MERCADO_LIBRE] if ml_configurado else [],
        },
        "productos": con_margen + sin_margen,
    }
