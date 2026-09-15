"""
Ayuda y soporte (lado cliente) — 5 de septiembre de 2026. Ver
app/db/models/support.py para el modelo y el criterio de aislamiento.

Cada endpoint cuelga de get_current_store: un cliente jamás puede leer,
crear o modificar una solicitud de otra empresa (no existe ningún
parámetro de store_id que se pueda manipular — la tienda sale siempre de
la sesión, igual que el resto del backend de cliente)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_store, get_current_user
from app.db.models import Store, SupportTicket, User
from app.db.models.support import CATEGORIAS_VALIDAS
from app.db.session import get_db

router = APIRouter(prefix="/api/soporte", tags=["soporte"])


class CrearSolicitudRequest(BaseModel):
    category: str
    subject: str
    description: str
    reference: str | None = None

    @field_validator("category")
    @classmethod
    def _categoria_valida(cls, v: str) -> str:
        if v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"Categoría inválida. Tiene que ser una de: {', '.join(CATEGORIAS_VALIDAS)}.")
        return v

    @field_validator("subject", "description")
    @classmethod
    def _no_vacio(cls, v: str, info) -> str:  # noqa: ANN001
        v = (v or "").strip()
        if not v:
            raise ValueError("Este campo no puede estar vacío.")
        # QA fase 2 (15/09/2026): se aceptaba un asunto de 200.000 caracteres
        # (la columna es de 200) y una descripción sin tope.
        if len(v) > (200 if info.field_name == "subject" else 10_000):
            raise ValueError("Este campo es demasiado largo.")
        return v

    @field_validator("reference")
    @classmethod
    def _referencia_corta(cls, v: str | None) -> str | None:
        if v is not None and len(v.strip()) > 200:
            raise ValueError("La referencia es demasiado larga.")
        return v


def _fila(t: SupportTicket) -> dict:
    return {
        "id": t.id,
        "categoria": t.category,
        "asunto": t.subject,
        "descripcion": t.description,
        "referencia": t.reference,
        "estado": t.status,
        "respuestaAdmin": t.admin_response,
        "respuestaAdminEn": t.admin_response_at.isoformat() if t.admin_response_at else None,
        "creadoEn": t.created_at.isoformat(),
        "actualizadoEn": t.updated_at.isoformat(),
    }


@router.get("/solicitudes")
def listar_mis_solicitudes(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> list[dict]:
    tickets = db.query(SupportTicket).filter_by(store_id=store.id).order_by(SupportTicket.created_at.desc()).all()
    return [_fila(t) for t in tickets]


@router.post("/solicitudes")
def crear_solicitud(
    body: CrearSolicitudRequest,
    db: Session = Depends(get_db),
    store: Store = Depends(get_current_store),
    usuario: User = Depends(get_current_user),
) -> dict:
    ahora = datetime.now()
    # QA fase 2 (15/09/2026): un doble clic (o reintentar) creaba varias
    # solicitudes iguales. La misma solicitud dentro del último minuto se
    # devuelve en vez de duplicarse.
    repetida = (
        db.query(SupportTicket)
        .filter(
            SupportTicket.store_id == store.id, SupportTicket.user_id == usuario.id,
            SupportTicket.subject == body.subject.strip(), SupportTicket.description == body.description.strip(),
            SupportTicket.created_at >= datetime.fromtimestamp(ahora.timestamp() - 60),
        )
        .first()
    )
    if repetida is not None:
        return _fila(repetida)
    ticket = SupportTicket(
        store=store,
        user=usuario,
        category=body.category,
        subject=body.subject.strip(),
        description=body.description.strip(),
        reference=(body.reference or "").strip() or None,
        status="abierto",
        created_at=ahora,
        updated_at=ahora,
    )
    db.add(ticket)
    db.commit()
    return _fila(ticket)


@router.get("/solicitudes/{ticket_id}")
def obtener_mi_solicitud(ticket_id: int, db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> dict:
    ticket = db.query(SupportTicket).filter_by(id=ticket_id, store_id=store.id).first()
    if ticket is None:
        # 404 tanto si no existe como si es de otra empresa — nunca revela
        # cuál de los dos casos es (mismo criterio que require_nexo_admin).
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    return _fila(ticket)
