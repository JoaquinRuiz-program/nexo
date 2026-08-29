"""
Conexión real (OAuth) e importación de ventas de Mercado Libre.

Nada de esto simula datos: /conectar necesita las credenciales reales del
dueño (MERCADOLIBRE_CLIENT_ID/SECRET/REDIRECT_URI en backend/.env) o
devuelve un error explicando EXACTAMENTE qué falta — nunca genera una URL
de autorización con un client_id inventado. /importar-ventas necesita una
cuenta ya conectada de verdad; sin eso no hay ningún pedido "de ejemplo"
que mostrar.

Limitación conocida y deliberada de esta primera versión: solo ingresa
pedidos NUEVOS. Si un pedido ya importado cambia de estado en Mercado Libre
después (ej. se cancela), se actualiza el estado acá, pero el stock
reservado para ML que ya se descontó NO se revierte automáticamente — el
dueño lo ajusta a mano en /api/productos/{id}/stock-mercadolibre si hace
falta. Revertir automáticamente es una función aparte, no construida todavía.

Sin autenticación de usuarios ni multi-tienda (mismo alcance que el resto
del backend): opera sobre la única tienda que existe.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.mercadolibre import (
    MercadoLibreAdapter,
    MercadoLibreAuthError,
    MercadoLibreConfig,
    MercadoLibreRequestError,
)
from app.config import Settings, get_settings
from app.db.models import MarketplaceAccount, Order, OrderItem, ProductVariant, Store
from app.db.session import get_db
from app.domain.marketplace_orders import map_ml_order
from app.domain.marketplace_stock import MarketplaceStockError, apply_sale
from app.domain.token_crypto import decrypt_token, encrypt_token

router = APIRouter(prefix="/api/mercadolibre", tags=["mercadolibre"])

MARKETPLACE = "mercadolibre"

# Estados pendientes de OAuth (protección CSRF) — en memoria del proceso,
# con expiración corta. Alcanza para un solo backend en desarrollo; si esto
# corre algún día con varias réplicas, hay que moverlo a algo compartido
# (Redis, o una tabla) — anotado a propósito, no resuelto porque no hace
# falta todavía con un solo proceso.
_pending_states: dict[str, float] = {}
_STATE_TTL_S = 600


def _new_state() -> str:
    _cleanup_states()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time()
    return state


def _consume_state(state: str) -> bool:
    _cleanup_states()
    return _pending_states.pop(state, None) is not None


def _cleanup_states() -> None:
    ahora = time.time()
    for s in [s for s, creado in _pending_states.items() if ahora - creado > _STATE_TTL_S]:
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
                f"{', '.join(faltantes)}. MERCADOLIBRE_* se generan creando una "
                "aplicación en https://developers.mercadolibre.cl con la cuenta "
                "real de la librería; TOKEN_ENCRYPTION_KEY se genera local (ver "
                ".env.example). Ninguno de los dos se puede inventar."
            ),
        )


def _get_default_store(db: Session) -> Store:
    store = db.query(Store).order_by(Store.id).first()
    if store is None:
        raise HTTPException(status_code=404, detail="No hay ninguna tienda creada todavía (correr app/db/seed_demo.py).")
    return store


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
        return {"conectado": False, "estado": "not_connected", "cuentaExternaId": None, "conectadoEn": None, "credencialesConfiguradas": configurado}
    return {
        "conectado": account.status == "connected",
        "estado": account.status,
        "cuentaExternaId": account.external_account_id,
        "conectadoEn": account.connected_at.isoformat() if account.connected_at else None,
        "credencialesConfiguradas": configurado,
    }


@router.get("/estado")
def estado(db: Session = Depends(get_db)) -> dict:
    store = _get_default_store(db)
    settings = get_settings()
    return _account_status(_get_account(db, store), _build_ml_config(settings).is_configured())


@router.get("/conectar")
def conectar(db: Session = Depends(get_db)) -> dict:
    _get_default_store(db)
    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)

    adapter = MercadoLibreAdapter(cfg)
    return {"authorizationUrl": adapter.build_authorization_url(_new_state())}


@router.get("/callback")
async def callback(code: str, state: str, db: Session = Depends(get_db)) -> dict:
    if not _consume_state(state):
        raise HTTPException(
            status_code=400,
            detail="El parámetro state es inválido o venció — iniciá la conexión de nuevo desde /api/mercadolibre/conectar.",
        )

    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)

    adapter = MercadoLibreAdapter(cfg)
    try:
        tokens = await adapter.exchange_code_for_tokens(code)
        user_info = await adapter.get_user_info(tokens.access_token)
    except MercadoLibreAuthError as err:
        raise HTTPException(status_code=502, detail=f"Mercado Libre rechazó la conexión: {err}") from err
    except MercadoLibreRequestError as err:
        raise HTTPException(status_code=502, detail=f"No se pudo conectar con Mercado Libre: {err}") from err
    finally:
        await adapter.aclose()

    store = _get_default_store(db)
    account = _get_or_create_account(db, store)
    now = datetime.now()
    account.access_token_encrypted = encrypt_token(tokens.access_token, settings.token_encryption_key)
    account.refresh_token_encrypted = encrypt_token(tokens.refresh_token, settings.token_encryption_key)
    account.token_expires_at = now + timedelta(seconds=tokens.expires_in)
    account.external_account_id = str(user_info.get("id") or tokens.user_id)
    account.status = "connected"
    account.connected_at = now
    account.last_checked_at = now
    db.commit()

    return _account_status(account, True)


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
        finally:
            await adapter.aclose()

        account.access_token_encrypted = encrypt_token(tokens.access_token, encryption_key)
        account.refresh_token_encrypted = encrypt_token(tokens.refresh_token, encryption_key)
        account.token_expires_at = datetime.now() + timedelta(seconds=tokens.expires_in)
        db.commit()

    return decrypt_token(account.access_token_encrypted, encryption_key)


@router.post("/importar-ventas")
async def importar_ventas(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)

    store = _get_default_store(db)
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
