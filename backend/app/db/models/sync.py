"""
Trazabilidad de sincronización: qué se sincronizó, cuándo, desde dónde,
hacia dónde, con qué resultado, y el detalle de cada error — exactamente lo
que pidió el dueño en la sección 5 de su mensaje, con los dos ejemplos
concretos:

  21/08/2026 20:31 — WooCommerce → Mercado Libre — 153 productos — Correcto
  21/08/2026 20:35 — WooCommerce → Mercado Libre — Error — SKU-123 — stock inválido

`SyncJob` es la fila-resumen (arma la primera línea); `SyncLog` es el
detalle por producto cuando algo específico falla (arma la segunda línea).
Ningún registro de sincronización real se genera todavía en esta fase — solo
se deja la estructura lista para cuando exista el motor de sincronización.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    # woocommerce_to_ml | ml_to_woocommerce | reconciliation
    direction: Mapped[str] = mapped_column(String(50), nullable=False)
    # manual | scheduled | webhook
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # running | success | partial_error | error
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    products_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    store: Mapped["Store"] = relationship()  # noqa: F821
    logs: Mapped[list["SyncLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_job_id: Mapped[int] = mapped_column(ForeignKey("sync_jobs.id"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"), nullable=True)
    # info | warning | error
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    job: Mapped["SyncJob"] = relationship(back_populates="logs")
    variant: Mapped["ProductVariant | None"] = relationship()  # noqa: F821
