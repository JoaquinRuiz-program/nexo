"""
Conexión real (OAuth) e importación de ventas de Mercado Libre.

ARQUITECTURA MULTIEMPRESA — dos cosas que nunca hay que confundir:

1. La APLICACIÓN DESARROLLADORA (MERCADOLIBRE_CLIENT_ID/SECRET/REDIRECT_URI
   en backend/.env) es de NEXO. Se crea UNA sola vez en
   https://developers.mercadolibre.cl y sirve para TODAS las empresas que
   usen Nexo — nunca se le pide a un cliente que cree su propia aplicación
   de desarrollador. Estas credenciales no viven nunca en la base de datos
   (no son datos "de una empresa"), solo en el entorno del servidor.
2. La CUENTA VENDEDORA (el seller que Mercado Libre identifica en
   /users/me — external_account_id/nickname/site_id en
   `MarketplaceAccount`) es del cliente. Cada empresa que conecta Mercado
   Libre autoriza con SU propia cuenta, y esa fila queda scopeada por
   `store_id` — nunca global. Dos empresas conectando cada una su propio
   seller conviven sin problema (`MarketplaceAccount` tiene
   `UniqueConstraint(store_id, marketplace)`: una empresa no puede tener dos
   conexiones activas del mismo marketplace, pero nada impide que dos
   empresas distintas tengan cada una la suya).

Nada de esto simula datos: /conectar necesita las credenciales reales de la
app de Nexo o devuelve un error explicando EXACTAMENTE qué falta — nunca
genera una URL de autorización con un client_id inventado. /importar-ventas
necesita una cuenta ya conectada de verdad; sin eso no hay ningún pedido "de
ejemplo" que mostrar.

/callback SIEMPRE redirige el navegador de vuelta al frontend (nunca
devuelve JSON): a quien llega ahí es al navegador real del dueño, recién
saliendo de autorizar en Mercado Libre — un JSON crudo en pantalla se vería
como un error. Los errores (autorización rechazada, code vencido,
credenciales mal configuradas, etc.) también redirigen, con un código corto
en `razon` — nunca el detalle técnico ni una excepción — que el frontend
traduce a lenguaje humano.

Limitación conocida y deliberada de esta primera versión: solo ingresa
pedidos NUEVOS. Si un pedido ya importado cambia de estado en Mercado Libre
después (ej. se cancela), se actualiza el estado acá, pero el stock
reservado para ML que ya se descontó NO se revierte automáticamente — el
dueño lo ajusta a mano en /api/productos/{id}/stock-mercadolibre si hace
falta. Revertir automáticamente es una función aparte, no construida todavía.

29 de agosto de 2026 — autenticación real: "la tienda actual" se resuelve
con `Depends(get_current_store)` (app/api/deps.py), desde la sesión del
usuario logueado — nunca "la primera tienda que exista". `/conectar`,
`/estado`, `/desconectar`, `/importar-ventas` y `/comisiones/recalcular`
requieren sesión válida. La única excepción a propósito es `/callback`:
NO depende de la sesión — el navegador llega ahí recién saliendo de
autorizar en Mercado Libre, y podría no traer la cookie de Nexo en todos
los casos (redirect entre dominios). En cambio, `/callback` recupera la
empresa dueña de la conexión desde el `state` (`store_id` embebido al
llamar `/conectar`, ver `_new_state`/`_consume_state`) — el mismo
mecanismo ya estaba armado así desde antes de que existiera login real,
precisamente para este momento.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.adapters.mercadolibre import (
    MercadoLibreAdapter,
    MercadoLibreAuthError,
    MercadoLibreConfig,
    MercadoLibreRequestError,
    generate_pkce_pair,
)
from app.api.deps import get_current_store
from app.config import Settings, get_settings
from app.db.models import MarketplaceAccount, MercadoLibreCategoryFee, Order, OrderItem, Product, ProductVariant, Store
from app.db.session import get_db
from app.domain.marketplace_orders import map_ml_order
from app.domain.marketplace_stock import MarketplaceStockError, apply_sale
from app.domain.ml_fees import LISTING_TYPE_IDS, parse_listing_fees
from app.domain.token_crypto import TokenEncryptionNotConfigured, decrypt_token, encrypt_token

router = APIRouter(prefix="/api/mercadolibre", tags=["mercadolibre"])

MARKETPLACE = "mercadolibre"

# Estados pendientes de OAuth (protección CSRF + PKCE) — en memoria del
# proceso, con expiración corta. Alcanza para un solo backend en
# desarrollo; si esto corre algún día con varias réplicas, hay que moverlo
# a algo compartido (Redis, o una tabla) — anotado a propósito, no resuelto
# porque no hace falta todavía con un solo proceso.
_pending_states: dict[str, dict] = {}
_STATE_TTL_S = 600


def _new_state(store_id: int) -> tuple[str, str]:
    """(state, code_challenge) — genera y guarda también el code_verifier de
    PKCE Y la tienda/empresa que inició este intento de conexión, ambos
    emparejados con este state para recuperarlos en el callback.

    Guardar `store_id` acá (y no volver a resolver "la tienda actual" en
    /callback) es lo que hace que la cuenta de Mercado Libre quede asociada
    a la empresa que REALMENTE empezó este flujo — no a la que resulte ser
    "la tienda actual" en el momento en que Mercado Libre responde, que
    puede ser un instante distinto (o, ahora con login real, una sesión
    distinta). `store_id` viene de `Depends(get_current_store)` en
    /conectar — nunca de un parámetro que mande el cliente."""
    _cleanup_states()
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = generate_pkce_pair()
    _pending_states[state] = {"created": time.time(), "code_verifier": code_verifier, "store_id": store_id}
    return state, code_challenge


def _consume_state(state: str) -> Optional[dict]:
    """Devuelve {"code_verifier", "store_id"} guardados para este state (o
    None si el state no existe o venció) — y lo borra: un state solo se usa
    una vez."""
    _cleanup_states()
    return _pending_states.pop(state, None)


def _cleanup_states() -> None:
    ahora = time.time()
    for s in [s for s, entry in _pending_states.items() if ahora - entry["created"] > _STATE_TTL_S]:
        _pending_states.pop(s, None)


def _build_ml_config(settings: Settings) -> MercadoLibreConfig:
    return MercadoLibreConfig(
        client_id=settings.mercadolibre_client_id,
        client_secret=settings.mercadolibre_client_secret,
        redirect_uri=settings.mercadolibre_redirect_uri,
        auth_domain=settings.mercadolibre_auth_domain,
    )


def _require_configured(cfg: MercadoLibreConfig, settings: Settings) -> None:
    faltantes = []
    if not cfg.client_id:
        faltantes.append("MERCADOLIBRE_CLIENT_ID")
    if not cfg.client_secret:
        faltantes.append("MERCADOLIBRE_CLIENT_SECRET")
    if not cfg.redirect_uri:
        faltantes.append("MERCADOLIBRE_REDIRECT_URI")
    if not settings.token_encryption_key:
        faltantes.append("TOKEN_ENCRYPTION_KEY")
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=(
                "Faltan datos de Mercado Libre en backend/.env: "
                f"{', '.join(faltantes)}. MERCADOLIBRE_* son las credenciales de "
                "la aplicación desarrolladora de NEXO (se crean UNA sola vez en "
                "https://developers.mercadolibre.cl, nunca por cada empresa que "
                "use Nexo) — no son datos de la cuenta vendedora de ningún "
                "cliente. TOKEN_ENCRYPTION_KEY se genera local (ver .env.example). "
                "Ninguno de los dos se puede inventar."
            ),
        )


def _get_account(db: Session, store: Store) -> MarketplaceAccount | None:
    return db.query(MarketplaceAccount).filter_by(store_id=store.id, marketplace=MARKETPLACE).first()


def _get_or_create_account(db: Session, store: Store) -> MarketplaceAccount:
    account = _get_account(db, store)
    if account is None:
        account = MarketplaceAccount(store=store, marketplace=MARKETPLACE, status="not_connected")
        db.add(account)
        db.flush()
    return account


def _account_status(account: MarketplaceAccount | None, configurado: bool) -> dict:
    if account is None:
        return {
            "conectado": False,
            "estado": "not_connected",
            "cuentaExternaId": None,
            "nickname": None,
            "siteId": None,
            "conectadoEn": None,
            "credencialesConfiguradas": configurado,
        }
    return {
        "conectado": account.status == "connected",
        "estado": account.status,
        "cuentaExternaId": account.external_account_id,
        "nickname": account.external_account_nickname,
        "siteId": account.external_account_site_id,
        "conectadoEn": account.connected_at.isoformat() if account.connected_at else None,
        "credencialesConfiguradas": configurado,
    }


def build_estado_conexion(db: Session, store: Store, settings: Settings) -> dict:
    """Misma respuesta que GET /estado — factorizado para que
    app/api/routes/dashboard.py pueda mostrar el estado real de conexión sin
    duplicar la consulta ni inventar un "conectado" que no sea real."""
    return _account_status(_get_account(db, store), _build_ml_config(settings).is_configured())


@router.get("/estado")
def estado(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    return build_estado_conexion(db, store, get_settings())


@router.get("/conectar")
def conectar(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)

    state, code_challenge = _new_state(store.id)
    adapter = MercadoLibreAdapter(cfg)
    return {"authorizationUrl": adapter.build_authorization_url(state, code_challenge)}


def _frontend_redirect(settings: Settings, *, ml: str, razon: Optional[str] = None) -> RedirectResponse:
    """A dónde vuelve el navegador después de /callback — SIEMPRE una
    redirección al frontend (nunca un JSON): quien llega acá es el
    navegador real del dueño, recién saliendo de autorizar en Mercado
    Libre, no un cliente HTTP programático. `razon` es un código corto
    (nunca el detalle técnico ni un mensaje de excepción) — el frontend lo
    traduce a lenguaje humano (ver js/app.js, RAZON_ERROR_ML)."""
    params = {"ml": ml}
    if razon:
        params["razon"] = razon
    return RedirectResponse(f"{settings.frontend_base_url}/?{urlencode(params)}#/mercadolibre", status_code=303)


@router.get("/callback")
async def callback(
    state: Optional[str] = None,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()

    # Mercado Libre redirige con ?error=access_denied (sin "code") cuando el
    # dueño cancela la autorización en vez de aceptarla — no es un fallo del
    # sistema, así que nunca debe verse como un 4xx/5xx crudo.
    if error:
        _consume_state(state) if state else None
        razon = "rechazado" if error == "access_denied" else "error_autorizacion"
        return _frontend_redirect(settings, ml="error", razon=razon)

    if not state or not code:
        return _frontend_redirect(settings, ml="error", razon="solicitud_invalida")

    pendiente = _consume_state(state)
    if pendiente is None:
        return _frontend_redirect(settings, ml="error", razon="estado_invalido")
    code_verifier = pendiente["code_verifier"]

    # La empresa dueña de esta conexión es la que se guardó en el state al
    # iniciar /conectar — no "la tienda actual" recién ahora (ver
    # _new_state). Si esa tienda ya no existe (caso extremo: se borró entre
    # medio), no hay a quién asociar la cuenta — mismo error que un state
    # inválido, nunca un 500.
    store = db.get(Store, pendiente["store_id"])
    if store is None:
        return _frontend_redirect(settings, ml="error", razon="estado_invalido")

    cfg = _build_ml_config(settings)
    try:
        _require_configured(cfg, settings)
    except HTTPException:
        return _frontend_redirect(settings, ml="error", razon="credenciales_faltantes")

    adapter = MercadoLibreAdapter(cfg)
    try:
        tokens = await adapter.exchange_code_for_tokens(code, code_verifier)
        user_info = await adapter.get_user_info(tokens.access_token)
    except (MercadoLibreAuthError, MercadoLibreRequestError):
        # El motivo técnico (código vencido, ML caído, etc.) queda en los
        # logs del servidor — nunca en la URL a la que vuelve el navegador.
        return _frontend_redirect(settings, ml="error", razon="conexion_fallida")
    finally:
        await adapter.aclose()

    try:
        access_token_encrypted = encrypt_token(tokens.access_token, settings.token_encryption_key)
        refresh_token_encrypted = encrypt_token(tokens.refresh_token, settings.token_encryption_key)
    except TokenEncryptionNotConfigured:
        # Mercado Libre ya autorizó la app (los tokens son reales y válidos)
        # pero TOKEN_ENCRYPTION_KEY está mal escrita en .env — se le avisa al
        # dueño en la UI, el detalle técnico se resuelve mirando el .env.
        return _frontend_redirect(settings, ml="error", razon="cifrado_no_configurado")

    account = _get_or_create_account(db, store)
    now = datetime.now()
    account.access_token_encrypted = access_token_encrypted
    account.refresh_token_encrypted = refresh_token_encrypted
    account.token_expires_at = now + timedelta(seconds=tokens.expires_in)
    account.external_account_id = str(user_info.get("id") or tokens.user_id)
    account.external_account_nickname = user_info.get("nickname")
    account.external_account_site_id = user_info.get("site_id")
    account.status = "connected"
    account.connected_at = now
    account.last_checked_at = now
    db.commit()

    return _frontend_redirect(settings, ml="conectado")


@router.post("/desconectar")
def desconectar(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    """Borra la conexión guardada — el dueño puede volver a conectar
    (la misma cuenta u otra) desde cero en cualquier momento. Nunca falla
    si ya estaba desconectado: desconectar es idempotente."""
    account = _get_account(db, store)
    if account is not None:
        account.status = "not_connected"
        account.access_token_encrypted = None
        account.refresh_token_encrypted = None
        account.token_expires_at = None
        account.external_account_id = None
        account.external_account_nickname = None
        account.external_account_site_id = None
        account.connected_at = None
        account.last_checked_at = None
        db.commit()
    return build_estado_conexion(db, store, get_settings())


async def _get_valid_access_token(db: Session, account: MarketplaceAccount, cfg: MercadoLibreConfig, encryption_key: str) -> str:
    if account.status != "connected" or not account.access_token_encrypted:
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado — conectar primero con GET /api/mercadolibre/conectar.")

    if account.token_expires_at and account.token_expires_at <= datetime.now():
        adapter = MercadoLibreAdapter(cfg)
        try:
            refresh_token = decrypt_token(account.refresh_token_encrypted, encryption_key)
            tokens = await adapter.refresh_tokens(refresh_token)
        except MercadoLibreAuthError as err:
            account.status = "token_expired"
            db.commit()
            raise HTTPException(
                status_code=401,
                detail=f"El token de Mercado Libre venció y no se pudo renovar: {err}. Hay que reconectar la cuenta.",
            ) from err
        except MercadoLibreRequestError as err:
            # Renovar falló por red/servidor, no porque el refresh token esté
            # mal — no se marca la cuenta como desconectada, se puede
            # reintentar la importación más tarde.
            raise HTTPException(status_code=502, detail=f"No se pudo renovar el token de Mercado Libre: {err}") from err
        except TokenEncryptionNotConfigured as err:
            raise HTTPException(status_code=400, detail=f"No se pudo leer/guardar el token cifrado: {err}") from err
        finally:
            await adapter.aclose()

        account.access_token_encrypted = encrypt_token(tokens.access_token, encryption_key)
        account.refresh_token_encrypted = encrypt_token(tokens.refresh_token, encryption_key)
        account.token_expires_at = datetime.now() + timedelta(seconds=tokens.expires_in)
        db.commit()

    try:
        return decrypt_token(account.access_token_encrypted, encryption_key)
    except TokenEncryptionNotConfigured as err:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el token guardado: {err}") from err


@router.post("/importar-ventas")
async def importar_ventas(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)

    account = _get_account(db, store)
    if account is None or account.status != "connected":
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado todavía.")

    access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)

    adapter = MercadoLibreAdapter(cfg)
    try:
        resultado = await adapter.search_orders(access_token, seller_id=account.external_account_id)
    except MercadoLibreAuthError as err:
        raise HTTPException(status_code=502, detail=f"Mercado Libre rechazó la consulta de pedidos: {err}") from err
    except MercadoLibreRequestError as err:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar pedidos de Mercado Libre: {err}") from err
    finally:
        await adapter.aclose()

    ordenes_nuevas: list[str] = []
    ordenes_ya_existian: list[str] = []
    items_sin_sku_en_catalogo: list[str] = []
    desajustes_stock_reservado: list[str] = []
    ahora = datetime.now()

    for raw_order in resultado.get("results", []):
        fila = map_ml_order(raw_order)
        existente = db.query(Order).filter_by(
            store_id=store.id, channel=MARKETPLACE, external_order_id=fila["external_order_id"]
        ).first()

        if existente is not None:
            if fila["status"] == "cancelado" and existente.status != "cancelado":
                existente.status = "cancelado"
                existente.updated_at = ahora
            ordenes_ya_existian.append(fila["external_order_id"])
            continue

        order = Order(
            store=store,
            marketplace_account_id=account.id,
            channel=MARKETPLACE,
            external_order_id=fila["external_order_id"],
            order_date=fila["order_date"],
            status=fila["status"],
            total_amount=fila["total_amount"],
            commission_amount=fila["commission_amount"],
            created_at=ahora,
            updated_at=ahora,
        )
        db.add(order)
        db.flush()

        for item in fila["items"]:
            variant = (
                db.query(ProductVariant).filter_by(store_id=store.id, variant_sku=item["sku"]).first()
                if item["sku"]
                else None
            )
            if variant is None:
                items_sin_sku_en_catalogo.append(item["sku"] or "(sin SKU)")

            db.add(
                OrderItem(
                    order=order,
                    variant=variant,
                    external_item_sku=item["sku"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    created_at=ahora,
                )
            )

            if variant is not None and fila["status"] != "cancelado":
                try:
                    variant.marketplace_stock = apply_sale(variant.marketplace_stock, item["quantity"])
                except MarketplaceStockError:
                    # La venta ya ocurrió de verdad en Mercado Libre — nunca
                    # se descarta el pedido por esto. Se registra el
                    # desajuste para que el dueño ajuste el tope a mano.
                    desajustes_stock_reservado.append(item["sku"])

        ordenes_nuevas.append(fila["external_order_id"])

    account.last_checked_at = ahora
    db.commit()

    return {
        "ordenesNuevas": ordenes_nuevas,
        "ordenesYaExistian": ordenes_ya_existian,
        "itemsSinSkuEnCatalogo": items_sin_sku_en_catalogo,
        "desajustesStockReservado": desajustes_stock_reservado,
    }


@router.post("/comisiones/recalcular")
async def recalcular_comisiones(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    """Consulta la comisión REAL de Mercado Libre (Clásica y Premium, ver
    app/domain/ml_fees.py) para cada producto del catálogo con precio
    cargado — a pedido del dueño (29 de agosto de 2026): "la comisión de
    Mercado Libre varía por producto", nunca un % fijo asumido.

    Deliberadamente NO se llama durante la carga de un Excel (sería lento
    con catálogos grandes, y golpearía la API de Mercado Libre una vez por
    SKU) — es un paso aparte que el dueño dispara cuando quiere. Requiere
    la cuenta de Mercado Libre conectada y con el permiso "Publicación y
    sincronización" habilitado en la aplicación (no alcanza con "Venta y
    envíos" — ver MercadoLibreAdapter.get_listing_fees).

    Categoría por producto: se predice UNA vez por título
    (GET /domain_discovery, público) y se guarda en
    Product.ml_category_id — no se vuelve a predecir en corridas
    siguientes. Comisión por (categoría, precio): se cachea en
    MercadoLibreCategoryFee — si YA está cacheada para el precio actual del
    producto, no se vuelve a pedir a Mercado Libre."""
    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)

    account = _get_account(db, store)
    if account is None or account.status != "connected":
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado todavía — conectar primero con GET /api/mercadolibre/conectar.")

    site_id = account.external_account_site_id or "MLC"
    access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)

    productos_con_precio = [
        p for p in db.query(Product).filter_by(store_id=store.id).all()
        if any(v.price is not None for v in p.variants)
    ]

    adapter = MercadoLibreAdapter(cfg)
    productos_sin_categoria: list[str] = []
    combinaciones_actualizadas = 0
    combinaciones_con_error: list[str] = []
    try:
        for producto in productos_con_precio:
            if producto.ml_category_id:
                continue
            try:
                prediccion = await adapter.predict_category(producto.name, site_id)
            except (MercadoLibreAuthError, MercadoLibreRequestError):
                prediccion = None
            if prediccion is None:
                productos_sin_categoria.append(producto.name)
                continue
            producto.ml_category_id = prediccion["categoryId"]
            producto.ml_category_name = prediccion["categoryName"]
        db.commit()

        # (categoría, precio) únicos a consultar — un mismo par se pide una
        # sola vez aunque varios productos/variantes lo compartan.
        pares_a_pedir: set[tuple[str, float]] = set()
        for producto in productos_con_precio:
            if not producto.ml_category_id:
                continue
            for variante in producto.variants:
                if variante.price is None:
                    continue
                par = (producto.ml_category_id, float(variante.price))
                tipos_cacheados = {
                    fila.listing_type_id
                    for fila in db.query(MercadoLibreCategoryFee)
                    .filter_by(store_id=store.id, category_id=par[0], price=par[1])
                    .all()
                }
                if not set(LISTING_TYPE_IDS.values()).issubset(tipos_cacheados):
                    pares_a_pedir.add(par)

        ahora = datetime.now()
        for category_id, precio in pares_a_pedir:
            try:
                raw = await adapter.get_listing_fees(access_token, site_id, category_id, precio)
            except MercadoLibreAuthError as err:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Mercado Libre rechazó la consulta de comisiones — revisá que la "
                        "aplicación tenga habilitado el permiso 'Publicación y sincronización' "
                        "en developers.mercadolibre.cl."
                    ),
                ) from err
            except MercadoLibreRequestError:
                combinaciones_con_error.append(f"{category_id} @ ${precio:,.0f}")
                continue

            for clave, fee in parse_listing_fees(raw).items():
                listing_type_id = LISTING_TYPE_IDS[clave]
                fila = (
                    db.query(MercadoLibreCategoryFee)
                    .filter_by(store_id=store.id, category_id=category_id, listing_type_id=listing_type_id, price=precio)
                    .first()
                )
                if fila is None:
                    fila = MercadoLibreCategoryFee(
                        store_id=store.id, category_id=category_id, listing_type_id=listing_type_id, price=precio
                    )
                    db.add(fila)
                fila.percentage_fee = fee.percentage_fee
                fila.fixed_fee = fee.fixed_fee
                fila.sale_fee_amount = fee.sale_fee_amount
                fila.fetched_at = ahora
            combinaciones_actualizadas += 1
        db.commit()
    finally:
        await adapter.aclose()

    return {
        "productosRevisados": len(productos_con_precio),
        "productosSinCategoriaDetectada": productos_sin_categoria,
        "combinacionesComisionActualizadas": combinaciones_actualizadas,
        "combinacionesConError": combinaciones_con_error,
    }
