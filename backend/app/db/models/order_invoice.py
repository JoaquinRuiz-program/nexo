"""
Factura propia del vendedor adjunta a una venta de Mercado Libre (15 de
septiembre de 2026). Nexo no emite facturas ni guarda el archivo: solo
recuerda qué se adjuntó a cada venta para poder mostrarlo y quitarlo.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderInvoice(Base):
    __tablename__ = "order_invoices"
    __table_args__ = (UniqueConstraint("store_id", "order_id", name="uq_order_invoice_store_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    # Pack de Mercado Libre al que se adjuntó (el ID del pedido si no tiene pack).
    pack_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # IDs de fiscal_document que devolvió Mercado Libre, separados por coma.
    document_ids: Mapped[str] = mapped_column(String(500), nullable=False)
    # Nombres de los archivos subidos, separados por "|".
    file_names: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
