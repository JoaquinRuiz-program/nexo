"""
Registro real de las sincronizaciones con Mercado Libre (14 de septiembre de
2026) en `SyncJob`/`SyncLog` (app/db/models/sync.py), que existían desde el
principio pero nadie escribía. Casos reales que motivaron esto: el stock que
no llegó a una publicación y la foto que dejó una publicación pausada — los dos
quedaban solo en el log del servidor, invisibles para el admin de Nexo.

Nunca se inventa un error: solo se registra lo que efectivamente pasó en una
sincronización que se ejecutó. Quien llama hace el commit (salvo
`registrar_fallo`, que se usa justo antes de responder un error).
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import SyncJob, SyncLog

logger = logging.getLogger(__name__)

DIRECCION_ML_VENTAS = "ml_importar_ventas"
DIRECCION_ML_COSTOS_ENVIO = "ml_costos_envio"
DIRECCION_ML_STOCK = "ml_stock"
DIRECCION_ML_DEVOLUCIONES = "ml_devoluciones"

_LARGO_MAXIMO_MENSAJE = 1000

Detalle = list[tuple[int | None, str]]  # (variant_id o None, mensaje)


def registrar_sincronizacion(
    db: Session,
    store_id: int,
    *,
    direccion: str,
    productos_afectados: int,
    inicio: datetime,
    errores: Detalle | None = None,
    advertencias: Detalle | None = None,
    triggered_by: str = "manual",
) -> SyncJob:
    """Una fila de historial por sincronización. Estado: `success` sin
    errores, `partial_error` si hubo errores pero algo se sincronizó, `error`
    si no se sincronizó nada."""
    errores = errores or []
    advertencias = advertencias or []
    ahora = datetime.now()
    if not errores:
        estado = "success"
    elif productos_afectados > 0:
        estado = "partial_error"
    else:
        estado = "error"
    job = SyncJob(
        store_id=store_id, direction=direccion, triggered_by=triggered_by,
        started_at=inicio, finished_at=ahora, status=estado, products_affected=productos_afectados,
    )
    db.add(job)
    db.flush()
    for nivel, detalle in (("error", errores), ("warning", advertencias)):
        for variant_id, mensaje in detalle:
            db.add(SyncLog(job=job, variant_id=variant_id, level=nivel, message=mensaje[:_LARGO_MAXIMO_MENSAJE], created_at=ahora))
    return job


def registrar_fallo(db: Session, store_id: int, direccion: str, mensaje: str) -> None:
    """Sincronización que no llegó a correr (ML caído, token inválido,
    error inesperado). Hace su propio commit y nunca levanta: registrar un
    fallo no puede tapar el error original."""
    try:
        ahora = datetime.now()
        registrar_sincronizacion(db, store_id, direccion=direccion, productos_afectados=0, inicio=ahora, errores=[(None, mensaje)])
        db.commit()
    except Exception as err:  # noqa: BLE001 — best effort a propósito
        db.rollback()
        logger.error("No se pudo registrar el fallo de sincronización %s (store_id=%s): %s", direccion, store_id, err)
