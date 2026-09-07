"""
"Mi plan" — 5 de septiembre de 2026, lo que ve un cliente de su propia
suscripción (nunca la de otra empresa: todo acá cuelga de
`get_current_store`, igual criterio que el resto del backend de cliente).

Solo lectura + uso actual. Un cliente puede cambiar/pagar su plan de verdad
desde el 6 de septiembre de 2026 — ver app/api/routes/pagos.py (Mercado
Pago) — pero SIEMPRE a través de un pago real confirmado por webhook,
nunca escribiendo directo sobre su propia fila de Subscription. El panel
de administrador de Nexo (app/api/routes/admin.py) conserva, aparte, la
capacidad de asignar/cambiar un plan a mano (para casos manuales:
cortesías, acuerdos especiales, arreglar un dato viejo) — un cliente NUNCA
puede modificar su propia suscripción con un request manipulado, ni ver la
de otra empresa (no hay ningún parámetro de store_id acá, a propósito).
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
