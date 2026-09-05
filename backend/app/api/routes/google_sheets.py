"""
Conexión real (OAuth) e importación de catálogo desde Google Sheets — 5 de
septiembre de 2026.

Mismo patrón que app/api/routes/mercadolibre.py (ver ese archivo para el
razonamiento completo de por qué está armado así) — acá solo lo distinto:

1. Reusa `MarketplaceAccount` con `marketplace="google_sheets"` (el campo es
   texto libre exactamente para esto — ver su docstring). Los campos
   pensados para "cuenta vendedora" se reaprovechan con otro significado,
   documentado acá mismo:
     - external_account_id       -> ID de la spreadsheet vinculada
     - external_account_nickname -> título de esa spreadsheet
     - external_account_site_id  -> nombre de la pestaña/hoja usada la
                                     última vez (para poder "volver a
                                     sincronizar" sin tener que repetir el
                                     link cada vez)
2. Sin PKCE (Google no lo pide para un cliente confidencial tipo "Web
   application" — ver app/adapters/google_sheets.py).
3. `/callback` NO es async por networking propio salvo el intercambio de
   tokens — igual que ML, resuelve la empresa dueña desde `state`, nunca de
   la sesión (el navegador puede volver sin cookie de Nexo).
4. La importación en sí (leer filas, detectar columnas, crear/actualizar
   productos) reutiliza EXACTAMENTE los mismos módulos que ya usa el
   importador de Excel/CSV (app/domain/catalog_import.py y
   app/domain/catalog_writer.py) — la única pieza nueva es cómo se
   consiguen (encabezados, filas): en vez de leer un archivo subido
   (app/domain/spreadsheet_io.py), se piden a la API de Google Sheets
   (GoogleSheetsAdapter.get_values, que devuelve la misma forma exacta).

No hay sincronización automática/periódica ni workers/webhooks en esta
versión (pedido explícito) — "volver a sincronizar" es una acción manual
que el dueño dispara desde la UI, llamando de nuevo a
/importar/analizar + /importar/confirmar (nunca se auto-ejecuta sola).
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.google_sheets import (
    GoogleAuthError,
    GoogleRequestError,
    GoogleSheetsAdapter,
    GoogleSheetsConfig,
    extract_spreadsheet_id,
)
from app.api.deps import get_current_store
from app.config import Settings, get_settings
from app.db.models import MarketplaceAccount, Store
from app.db.session import get_db
from app.domain.catalog_import import IMPORT_FIELDS, ColumnMapping, build_rows, detect_columns, row_to_dict, summarize_rows
from app.domain.catalog_writer import escribir_filas
from app.domain.token_crypto import TokenEncryptionNotConfigured, decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/google-sheets", tags=["google-sheets"])

MARKETPLACE = "google_sheets"

# Mismo mecanismo de estados pendientes que app/api/routes/mercadolibre.py
# (ver ese archivo para el razonamiento completo) — instancia propia, nunca
# compartida entre integraciones distintas.
_pending_states: dict[str, dict] = {}
_STATE_TTL_S = 600


def _new_state(store_id: int) -> str:
    _cleanup_states()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = {"created": time.time(), "store_id": store_id}
    return state


def _consume_state(state: str) -> Optional[dict]:
    _cleanup_states()
    return _pending_states.pop(state, None)


def _cleanup_states() -> None:
    ahora = time.time()
    for s in [s for s, entry in _pending_states.items() if ahora - entry["created"] > _STATE_TTL_S]:
        _pending_states.pop(s, None)


def _build_google_config(settings: Settings) -> GoogleSheetsConfig:
    return GoogleSheetsConfig(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
    )


def _require_configured(cfg: GoogleSheetsConfig, settings: Settings) -> None:
    faltantes = []
    if not cfg.client_id:
        faltantes.append("GOOGLE_CLIENT_ID")
    if not cfg.client_secret:
        faltantes.append("GOOGLE_CLIENT_SECRET")
    if not cfg.redirect_uri:
        faltantes.append("GOOGLE_REDIRECT_URI")
    if not settings.token_encryption_key:
        faltantes.append("TOKEN_ENCRYPTION_KEY")
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=(
                "Faltan datos de Google en backend/.env: "
                f"{', '.join(faltantes)}. GOOGLE_* son las credenciales de la "
                "aplicación OAuth de NEXO en Google Cloud Console (se crean UNA "
                "sola vez, nunca por cada empresa que use Nexo) — no son datos "
                "de la cuenta de Google de ningún cliente. TOKEN_ENCRYPTION_KEY "
                "se genera local (ver .env.example). Ninguno de los dos se "
                "puede inventar."
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
            "credencialesConfiguradas": configurado,
            "spreadsheetId": None,
            "spreadsheetTitulo": None,
            "hojaSeleccionada": None,
            "conectadoEn": None,
        }
    return {
        "conectado": account.status == "connected",
        "estado": account.status,
        "credencialesConfiguradas": configurado,
        "spreadsheetId": account.external_account_id,
        "spreadsheetTitulo": account.external_account_nickname,
        "hojaSeleccionada": account.external_account_site_id,
        "conectadoEn": account.connected_at.isoformat() if account.connected_at else None,
    }


@router.get("/estado")
def estado(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    settings = get_settings()
    return _account_status(_get_account(db, store), _build_google_config(settings).is_configured())


@router.get("/conectar")
def conectar(store: Store = Depends(get_current_store)) -> dict:
    settings = get_settings()
    cfg = _build_google_config(settings)
    _require_configured(cfg, settings)

    state = _new_state(store.id)
    adapter = GoogleSheetsAdapter(cfg)
    return {"authorizationUrl": adapter.build_authorization_url(state)}


def _frontend_redirect(settings: Settings, *, gs: str, razon: Optional[str] = None) -> RedirectResponse:
    """Igual criterio que mercadolibre.py::_frontend_redirect — /callback
    SIEMPRE vuelve al navegador real del dueño, nunca un JSON crudo."""
    params = {"gs": gs}
    if razon:
        params["razon"] = razon
    return RedirectResponse(f"{settings.frontend_base_url}/?{urlencode(params)}#/integraciones", status_code=303)


@router.get("/callback")
async def callback(
    state: Optional[str] = None,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()

    # Google redirige con ?error=access_denied (sin "code") cuando el dueño
    # cancela la autorización en la pantalla de consentimiento.
    if error:
        _consume_state(state) if state else None
        razon = "rechazado" if error == "access_denied" else "error_autorizacion"
        return _frontend_redirect(settings, gs="error", razon=razon)

    if not state or not code:
        return _frontend_redirect(settings, gs="error", razon="solicitud_invalida")

    pendiente = _consume_state(state)
    if pendiente is None:
        return _frontend_redirect(settings, gs="error", razon="estado_invalido")

    store = db.get(Store, pendiente["store_id"])
    if store is None:
        return _frontend_redirect(settings, gs="error", razon="estado_invalido")

    cfg = _build_google_config(settings)
    try:
        _require_configured(cfg, settings)
    except HTTPException:
        return _frontend_redirect(settings, gs="error", razon="credenciales_faltantes")

    adapter = GoogleSheetsAdapter(cfg)
    try:
        tokens = await adapter.exchange_code_for_tokens(code)
    except (GoogleAuthError, GoogleRequestError):
        return _frontend_redirect(settings, gs="error", razon="conexion_fallida")
    finally:
        await adapter.aclose()

    if not tokens.refresh_token:
        # No debería pasar con access_type=offline + prompt=consent (ver
        # adapters/google_sheets.py) — si igual pasara, la conexión no
        # podría renovarse sola en ~1 hora: mejor avisar ahora que dejarla
        # a medias, nunca guardar una conexión que se va a romper sola.
        logger.error("Google no devolvió refresh_token para store_id=%s — no se puede guardar la conexión.", store.id)
        return _frontend_redirect(settings, gs="error", razon="sin_refresh_token")

    try:
        access_token_encrypted = encrypt_token(tokens.access_token, settings.token_encryption_key)
        refresh_token_encrypted = encrypt_token(tokens.refresh_token, settings.token_encryption_key)
    except TokenEncryptionNotConfigured:
        return _frontend_redirect(settings, gs="error", razon="cifrado_no_configurado")

    account = _get_or_create_account(db, store)
    now = datetime.now()
    account.access_token_encrypted = access_token_encrypted
    account.refresh_token_encrypted = refresh_token_encrypted
    account.token_expires_at = now + timedelta(seconds=tokens.expires_in)
    account.status = "connected"
    account.connected_at = now
    account.last_checked_at = now
    db.commit()

    return _frontend_redirect(settings, gs="conectado")


@router.post("/desconectar")
def desconectar(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    """Idempotente, mismo criterio que mercadolibre.py::desconectar — borra
    también la spreadsheet/hoja vinculada: reconectar empieza de cero."""
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
    settings = get_settings()
    return _account_status(_get_account(db, store), _build_google_config(settings).is_configured())


async def _get_valid_access_token(db: Session, account: MarketplaceAccount, cfg: GoogleSheetsConfig, encryption_key: str) -> str:
    if account.status != "connected" or not account.access_token_encrypted:
        raise HTTPException(status_code=400, detail="Google Sheets no está conectado — conectar primero con GET /api/google-sheets/conectar.")

    if account.token_expires_at and account.token_expires_at <= datetime.now():
        adapter = GoogleSheetsAdapter(cfg)
        try:
            refresh_token = decrypt_token(account.refresh_token_encrypted, encryption_key)
            tokens = await adapter.refresh_tokens(refresh_token)
        except GoogleAuthError as err:
            account.status = "token_expired"
            db.commit()
            raise HTTPException(
                status_code=401,
                detail=f"El acceso a Google venció y no se pudo renovar: {err}. Hay que reconectar Google Sheets.",
            ) from err
        except GoogleRequestError as err:
            raise HTTPException(status_code=502, detail=f"No se pudo renovar el acceso a Google: {err}") from err
        except TokenEncryptionNotConfigured as err:
            raise HTTPException(status_code=400, detail=f"No se pudo leer/guardar el token cifrado: {err}") from err
        finally:
            await adapter.aclose()

        account.access_token_encrypted = encrypt_token(tokens.access_token, encryption_key)
        # Google normalmente NO devuelve un refresh_token nuevo al renovar
        # (ver adapters/google_sheets.py) — se conserva el que ya había.
        if tokens.refresh_token:
            account.refresh_token_encrypted = encrypt_token(tokens.refresh_token, encryption_key)
        account.token_expires_at = datetime.now() + timedelta(seconds=tokens.expires_in)
        db.commit()

    try:
        return decrypt_token(account.access_token_encrypted, encryption_key)
    except TokenEncryptionNotConfigured as err:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el token guardado: {err}") from err


def _config_o_error(store: Store, db: Session) -> tuple[GoogleSheetsConfig, MarketplaceAccount]:
    settings = get_settings()
    cfg = _build_google_config(settings)
    _require_configured(cfg, settings)
    account = _get_account(db, store)
    if account is None or account.status != "connected":
        raise HTTPException(status_code=400, detail="Google Sheets no está conectado todavía — conectar primero con GET /api/google-sheets/conectar.")
    return cfg, account


async def _access_token_o_502(db: Session, account: MarketplaceAccount, cfg: GoogleSheetsConfig) -> str:
    settings = get_settings()
    try:
        return await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
    except HTTPException as err:
        if err.status_code == 401:
            raise HTTPException(status_code=401, detail="El acceso a Google venció y no se pudo renovar. Hay que reconectar Google Sheets.") from err
        raise HTTPException(status_code=502, detail="No pudimos validar la conexión con Google en este momento. Intentá de nuevo más tarde.") from err


class VincularHojaBody(BaseModel):
    url: str


@router.post("/hoja")
async def vincular_hoja(body: VincularHojaBody, db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    """Paso "seleccionar hoja/spreadsheet" del flujo — el dueño pega el link
    (o el ID) de una hoja de cálculo de Google Sheets a la que su cuenta
    tenga acceso. Devuelve el título y la lista de pestañas para que elija
    con cuál trabajar (si tiene una sola, se preselecciona sola)."""
    cfg, account = _config_o_error(store, db)
    access_token = await _access_token_o_502(db, account, cfg)

    spreadsheet_id = extract_spreadsheet_id(body.url)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Pegá el link completo de la hoja de cálculo de Google Sheets, o su ID.")

    adapter = GoogleSheetsAdapter(cfg)
    try:
        metadata = await adapter.get_spreadsheet_metadata(access_token, spreadsheet_id)
    except GoogleAuthError as err:
        raise HTTPException(
            status_code=400,
            detail="Google rechazó el acceso a esa hoja de cálculo. Verificá que el link sea correcto y que la cuenta de Google que conectaste tenga acceso a ella.",
        ) from err
    except GoogleRequestError as err:
        if err.status == 404:
            raise HTTPException(status_code=400, detail="No encontramos esa hoja de cálculo. Revisá el link e intentá de nuevo.") from err
        logger.error("Error consultando metadata de spreadsheet %s: %s", spreadsheet_id, err)
        raise HTTPException(status_code=502, detail="No pudimos leer esa hoja de cálculo en este momento. Intentá de nuevo más tarde.") from err
    finally:
        await adapter.aclose()

    if not metadata["hojas"]:
        raise HTTPException(status_code=400, detail="Esa hoja de cálculo no tiene ninguna pestaña con datos.")

    account.external_account_id = spreadsheet_id
    account.external_account_nickname = metadata["titulo"]
    # Con una sola pestaña, se preselecciona — coincide con el caso más
    # común (una empresa que arma su catálogo en una sola hoja) y evita un
    # paso extra. Con varias, el dueño elige explícitamente en el paso de
    # análisis (ver /importar/analizar, parámetro `hoja`).
    account.external_account_site_id = metadata["hojas"][0] if len(metadata["hojas"]) == 1 else None
    account.last_checked_at = datetime.now()
    db.commit()

    return {
        "spreadsheetId": spreadsheet_id,
        "titulo": metadata["titulo"],
        "hojas": metadata["hojas"],
        "hojaSeleccionada": account.external_account_site_id,
    }


def _resolver_hoja(account: MarketplaceAccount, hoja: Optional[str]) -> str:
    if not account.external_account_id:
        raise HTTPException(status_code=400, detail="Todavía no vinculaste ninguna hoja de cálculo — usá primero POST /api/google-sheets/hoja.")
    hoja_final = hoja or account.external_account_site_id
    if not hoja_final:
        raise HTTPException(status_code=400, detail="Esa hoja de cálculo tiene varias pestañas — indicá con cuál trabajar (parámetro 'hoja').")
    return hoja_final


async def _leer_filas_de_google(db: Session, store: Store, hoja: Optional[str]) -> tuple[str, list[str], list]:
    """Devuelve (hoja_usada, encabezados, raw_rows) — centraliza la parte
    que SÍ es específica de Google (pedir el token válido y llamar a la
    API); detect_columns/build_rows de ahí en más son el mismo código que
    usa el importador de Excel/CSV."""
    cfg, account = _config_o_error(store, db)
    hoja_final = _resolver_hoja(account, hoja)
    access_token = await _access_token_o_502(db, account, cfg)

    adapter = GoogleSheetsAdapter(cfg)
    try:
        headers, raw_rows = await adapter.get_values(access_token, account.external_account_id, hoja_final)
    except GoogleAuthError as err:
        raise HTTPException(
            status_code=400,
            detail="Google rechazó el acceso a esa hoja de cálculo. Puede que se haya revocado el permiso — reconectá Google Sheets.",
        ) from err
    except GoogleRequestError as err:
        if err.status == 400:
            raise HTTPException(status_code=400, detail=f"La pestaña '{hoja_final}' no existe en esa hoja de cálculo.") from err
        logger.error("Error leyendo valores de spreadsheet %s (%s): %s", account.external_account_id, hoja_final, err)
        raise HTTPException(status_code=502, detail="No pudimos leer los datos de Google Sheets en este momento. Intentá de nuevo más tarde.") from err
    finally:
        await adapter.aclose()

    if not headers:
        raise HTTPException(status_code=400, detail=f"La pestaña '{hoja_final}' está vacía.")

    # Recordar la última pestaña usada, para que "volver a sincronizar" no
    # tenga que volver a pedirla (ver docstring del módulo).
    account.external_account_site_id = hoja_final
    account.last_checked_at = datetime.now()
    db.commit()

    return hoja_final, headers, raw_rows


class AnalizarHojaBody(BaseModel):
    hoja: Optional[str] = None


@router.post("/importar/analizar")
async def analizar_hoja(
    body: AnalizarHojaBody = AnalizarHojaBody(),
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """Mismo contrato de respuesta que POST /api/catalogo/importar/analizar
    — no escribe nada, solo propone mapeo y valida filas. `hoja` es
    opcional: si no se manda, usa la última pestaña vinculada (permite
    "volver a sincronizar" sin repetir nada)."""
    hoja_usada, headers, raw_rows = await _leer_filas_de_google(db, store, body.hoja)

    mapping = detect_columns(headers)
    rows = build_rows(raw_rows, mapping)

    account = _get_account(db, store)
    return {
        "spreadsheetTitulo": account.external_account_nickname if account else None,
        "hojaUsada": hoja_usada,
        "encabezados": headers,
        "mapeoPropuesto": mapping.mapping,
        "camposReconocidos": list(IMPORT_FIELDS),
        "resumen": summarize_rows(rows),
        "filas": [row_to_dict(r) for r in rows],
    }


class ConfirmarHojaBody(BaseModel):
    hoja: Optional[str] = None
    mapeo: dict[str, Optional[str]]
    omitirErrores: bool = True


@router.post("/importar/confirmar")
async def confirmar_hoja(
    body: ConfirmarHojaBody,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    """Mismo contrato de respuesta que POST /api/catalogo/importar/confirmar.
    Vuelve a leer la hoja desde Google (nunca confía en filas que mande el
    cliente, mismo criterio que el importador de Excel/CSV vuelve a leer el
    archivo en vez de confiar en el preview del paso anterior) y crea/
    actualiza productos con app.domain.catalog_writer.escribir_filas —
    respeta el límite de productos del plan igual que cualquier otro
    origen de catálogo."""
    _hoja_usada, _headers, raw_rows = await _leer_filas_de_google(db, store, body.hoja)
    mapping = ColumnMapping(mapping=body.mapeo)
    rows = build_rows(raw_rows, mapping)

    return escribir_filas(db, store, rows, fuente="google_sheets", omitir_errores=body.omitirErrores)
