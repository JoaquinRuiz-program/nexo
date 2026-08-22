"""
Tienda — entidad central del catálogo, en vez de colgar todo directo del
usuario (ver decisión D del informe A-H). Hoy la relación Usuario→Tienda es
simple (un dueño, una o más tiendas), pero como catálogo/integraciones/
suscripción cuelgan de `store_id` y no de `user_id`, agregar más adelante
"varios usuarios por tienda" (una tabla `store_members`) es aditivo — no
obliga a rehacer nada de lo que se construye ahora.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Santiago")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CLP")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="stores")  # noqa: F821
    settings: Mapped["StoreSettings | None"] = relationship(back_populates="store", uselist=False)
    products: Mapped[list["Product"]] = relationship(back_populates="store")  # noqa: F821
    subscription: Mapped["Subscription | None"] = relationship(back_populates="store", uselist=False)  # noqa: F821
    marketplace_accounts: Mapped[list["MarketplaceAccount"]] = relationship(back_populates="store")  # noqa: F821
    orders: Mapped[list["Order"]] = relationship(back_populates="store")  # noqa: F821


class StoreSettings(Base):
    """Lo que hoy vive en `js/settings.js` del frontend (preferencias de
    negocio, no de la persona): umbral de stock bajo, notificaciones,
    nombre de empresa/tienda mostrado en Configuración > General."""

    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), unique=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    store_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    notify_stock_alerts: Mapped[bool] = mapped_column(default=True)
    notify_sync_errors: Mapped[bool] = mapped_column(default=True)
    notify_important_changes: Mapped[bool] = mapped_column(default=True)

    store: Mapped["Store"] = relationship(back_populates="settings")
