"""
Ayuda y soporte al cliente — 5 de septiembre de 2026.

MVP explícito (pedido del dueño): nada de chatbot, SLA, ticketing avanzado
ni knowledge base todavía. Una sola tabla, un solo campo de respuesta (el
admin puede pisarlo si responde de nuevo — no es un hilo de mensajes) es
suficiente para "cliente envía problema -> admin lo recibe -> responde ->
marca como resuelto".

Aislamiento: cada fila pertenece a una `Store` (nunca solo a un `User`,
mismo criterio que el resto del proyecto) — un cliente ve únicamente las
solicitudes de SU empresa; el admin de Nexo ve todas (ver
app/api/routes/admin.py).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

CATEGORIAS_VALIDAS = (
    "mercadolibre",
    "publicar",
    "productos",
    "imagenes",
    "cuenta",
    "suscripcion",
    "otro",
)

ESTADOS_VALIDOS = ("abierto", "en_revision", "resuelto", "cerrado")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    category: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Referencia libre a un producto/publicación afectado — nunca una FK
    # obligatoria (el problema puede no estar atado a nada puntual).
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="abierto")
    admin_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_response_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    store: Mapped["Store"] = relationship()  # noqa: F821
    user: Mapped["User"] = relationship()  # noqa: F821
