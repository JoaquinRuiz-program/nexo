"""
"Mi plan" — 5 de septiembre de 2026, lo que ve un cliente de su propia
suscripción (nunca la de otra empresa: todo acá cuelga de
`get_current_store`, igual criterio que el resto del backend de cliente).

Solo lectura + uso actual. Cambiar de plan/estado es exclusivo del panel de
administrador de Nexo (ver app/api/routes/admin.py) mientras no exista un
proveedor de pago real conectado — un cliente NUNCA puede modificar su
propia suscripción con un request manipulado, ni ver la de otra empresa
(no hay ningún parámetro de store_id acá, a propósito).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.api.deps import get_current_store
from app.db.models import Store
from app.db.session import get_db
from app.domain.plans import resumen_suscripcion

router = APIRouter(prefix="/api/suscripcion", tags=["suscripcion"])


@router.get("")
def obtener_mi_suscripcion(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    return resumen_suscripcion(db, store)
