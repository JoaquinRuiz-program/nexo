"""
Registro simple de acciones administrativas — 6 de septiembre de 2026,
auditoría comercial (pedido explícito, marcado como opcional en el
original: se implementa porque la arquitectura existente lo permite sin
nada nuevo — una tabla y tres llamadas desde admin.py, nada de colas,
nada de un sistema de auditoría genérico).

Registra ÚNICAMENTE acciones administrativas reales de Nexo sobre una
empresa cliente (suspender/reactivar, cambiar plan/estado de suscripción,
responder un ticket de soporte) — nunca acciones de un cliente sobre sus
propios datos, eso no es "administración de la plataforma".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Nullable: una acción administrativa podría no estar atada a una
    # empresa puntual en el futuro — hoy todas lo están.
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    admin_user: Mapped["User"] = relationship()  # noqa: F821
    store: Mapped["Store | None"] = relationship()  # noqa: F821
