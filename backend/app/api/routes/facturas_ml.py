"""
Facturas propias del vendedor adjuntas a sus ventas de Mercado Libre (15 de
septiembre de 2026). Nexo NO emite boletas ni facturas del SII: el dueño las
emite con su proveedor autorizado y acá solo se adjuntan a la venta. Doc
oficial "Cargar y Obtener Facturas - Emisión Propia" (Chile, 16/03/2026):

- POST /packs/{pack_id}/fiscal_documents, multipart `fiscal_document`: un PDF
  de hasta 1 MB y opcionalmente un XML (uno de cada tipo por pack).
- DELETE /packs/{pack_id}/fiscal_documents borra todos los archivos del pack.
- pack_id sale de GET /orders/{id}; si viene null se usa el ID del pedido.
- En Chile no se permite para ventas con envío Full (403).

El archivo nunca se guarda en Nexo: se reenvía a Mercado Libre.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.adapters.mercadolibre import MercadoLibreAdapter, MercadoLibreAuthError, MercadoLibreRequestError
from app.api.deps import get_current_store
from app.api.routes.mercadolibre import MARKETPLACE, _build_ml_config, _get_account, _get_valid_access_token, _require_configured
from app.config import get_settings
from app.db.models import Order, OrderInvoice, Store
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mercadolibre/facturas", tags=["mercadolibre"])

TAMANO_MAXIMO_BYTES = 1024 * 1024  # 1 MB, límite de Mercado Libre por archivo

_MENSAJE_NO_PERMITIDO = (
    "Mercado Libre no permitió adjuntar facturas a esta venta. En Chile no se pueden adjuntar "
    "facturas propias a ventas con envío Full; si no es el caso, reconecta la cuenta de Mercado Libre."
)


def _fila(orden: Order, factura: Optional[OrderInvoice]) -> dict:
    return {
        "pedidoId": orden.external_order_id,
        "fecha": orden.order_date.isoformat(),
        "total": float(orden.total_amount or 0),
        "factura": None if factura is None else {
            "archivos": factura.file_names.split("|"),
            "subidaEn": factura.uploaded_at.isoformat(),
        },
    }


def _venta_de_la_empresa(db: Session, store: Store, pedido_id: str) -> Order:
    orden = db.query(Order).filter_by(store_id=store.id, channel=MARKETPLACE, external_order_id=pedido_id).first()
    if orden is None:
        raise HTTPException(status_code=404, detail="Venta no encontrada.")
    return orden


async def _leer_archivo(archivo: UploadFile, *, extension: str, content_type: str, firma: bytes | None = None) -> tuple[str, bytes, str]:
    nombre = (archivo.filename or "").strip()
    tipo = extension.lstrip(".").upper()
    if not nombre.lower().endswith(extension):
        raise HTTPException(status_code=400, detail=f"La factura debe ser un archivo {tipo}.")
    contenido = await archivo.read(TAMANO_MAXIMO_BYTES + 1)
    if not contenido:
        raise HTTPException(status_code=400, detail=f"El archivo {tipo} está vacío.")
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise HTTPException(status_code=400, detail=f"El archivo {tipo} supera 1 MB, el máximo que acepta Mercado Libre.")
    if firma is not None and not contenido.startswith(firma):
        raise HTTPException(status_code=400, detail=f"El archivo no es un {tipo} válido.")
    return nombre, contenido, content_type


async def _token_y_adaptador(db: Session, store: Store) -> tuple[str, MercadoLibreAdapter]:
    settings = get_settings()
    cfg = _build_ml_config(settings)
    _require_configured(cfg, settings)
    account = _get_account(db, store)
    if account is None or account.status != "connected":
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado todavía.")
    access_token = await _get_valid_access_token(db, account, cfg, settings.token_encryption_key)
    return access_token, MercadoLibreAdapter(cfg)


@router.get("")
def listar_facturas(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    ordenes = (
        db.query(Order)
        .filter(Order.store_id == store.id, Order.channel == MARKETPLACE, Order.status != "cancelado")
        .order_by(Order.order_date.desc(), Order.id.desc())
        .limit(100)
        .all()
    )
    facturas = {f.order_id: f for f in db.query(OrderInvoice).filter_by(store_id=store.id).all()}
    return {"ventas": [_fila(o, facturas.get(o.id)) for o in ordenes]}


@router.post("/{pedido_id}")
async def subir_factura(
    pedido_id: str,
    pdf: UploadFile = File(...),
    xml: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
) -> dict:
    orden = _venta_de_la_empresa(db, store, pedido_id)
    if db.query(OrderInvoice).filter_by(store_id=store.id, order_id=orden.id).first() is not None:
        raise HTTPException(status_code=409, detail="Esta venta ya tiene una factura adjunta. Quítala antes de subir otra.")
    archivos = [await _leer_archivo(pdf, extension=".pdf", content_type="application/pdf", firma=b"%PDF")]
    if xml is not None and (xml.filename or "").strip():
        archivos.append(await _leer_archivo(xml, extension=".xml", content_type="application/xml"))

    access_token, adapter = await _token_y_adaptador(db, store)
    try:
        detalle = await adapter.get_order(access_token, orden.external_order_id)
        pack_id = str(detalle.get("pack_id") or orden.external_order_id)
        respuesta = await adapter.upload_fiscal_documents(access_token, pack_id, archivos)
    except MercadoLibreAuthError as err:
        logger.error("Mercado Libre rechazó la factura del pedido %s (store_id=%s): %s", orden.external_order_id, store.id, err)
        raise HTTPException(status_code=400, detail=_MENSAJE_NO_PERMITIDO) from err
    except MercadoLibreRequestError as err:
        logger.error("No se pudo subir la factura del pedido %s (store_id=%s): %s", orden.external_order_id, store.id, err)
        if err.status == 409:
            detalle_error = "Mercado Libre ya tiene una factura para esta venta. Quítala desde Mercado Libre antes de subir otra."
        elif err.status is not None and 400 <= err.status < 500:
            detalle_error = "Mercado Libre rechazó el archivo: debe ser un PDF (y opcionalmente su XML) de hasta 1 MB."
        else:
            detalle_error = "No pudimos subir la factura a Mercado Libre en este momento. Intenta de nuevo más tarde."
        raise HTTPException(status_code=502 if err.status is None or err.status >= 500 else 400, detail=detalle_error) from err
    finally:
        await adapter.aclose()

    ids = [str(i) for i in (respuesta.get("ids") or [])]
    if not ids:
        raise HTTPException(status_code=502, detail="Mercado Libre no confirmó la carga de la factura. Revisa la venta en Mercado Libre.")
    factura = OrderInvoice(
        store_id=store.id, order_id=orden.id, pack_id=pack_id, document_ids=",".join(ids),
        file_names="|".join(nombre for nombre, _contenido, _tipo in archivos), uploaded_at=datetime.now(),
    )
    db.add(factura)
    db.commit()
    return _fila(orden, factura)


@router.delete("/{pedido_id}")
async def quitar_factura(pedido_id: str, db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    orden = _venta_de_la_empresa(db, store, pedido_id)
    factura = db.query(OrderInvoice).filter_by(store_id=store.id, order_id=orden.id).first()
    if factura is None:
        raise HTTPException(status_code=404, detail="Esta venta no tiene una factura adjunta desde Nexo.")

    access_token, adapter = await _token_y_adaptador(db, store)
    try:
        await adapter.delete_fiscal_documents(access_token, factura.pack_id)
    except MercadoLibreAuthError as err:
        logger.error("Mercado Libre rechazó quitar la factura del pedido %s (store_id=%s): %s", orden.external_order_id, store.id, err)
        raise HTTPException(status_code=400, detail="Mercado Libre no permitió quitar la factura. Reconecta la cuenta e intenta de nuevo.") from err
    except MercadoLibreRequestError as err:
        # 404 = el pack ya no tiene facturas en Mercado Libre: igual se limpia en Nexo.
        if err.status != 404:
            logger.error("No se pudo quitar la factura del pedido %s (store_id=%s): %s", orden.external_order_id, store.id, err)
            raise HTTPException(status_code=502, detail="No pudimos quitar la factura en Mercado Libre en este momento. Intenta de nuevo más tarde.") from err
    finally:
        await adapter.aclose()

    db.delete(factura)
    db.commit()
    return _fila(orden, None)
