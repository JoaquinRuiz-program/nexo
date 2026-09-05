"""
Planes y suscripciones. Los precios son de EJEMPLO (demo) — igual que ya
están marcados en `js/demoData.js` — hasta que se defina un precio real.
Las columnas de Stripe quedan reservadas y nulas: no se implementa cobro
real en esta fase, solo se deja la estructura lista para conectarlo después.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # starter | growth | business | enterprise
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    product_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = sin límite (Enterprise)
    # 5 de septiembre de 2026 — límite de publicaciones activas (distinto de
    # productos: un producto puede existir sin estar publicado en ningún
    # marketplace). None = sin límite, mismo criterio que product_limit.
    publication_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_demo_label: Mapped[str] = mapped_column(String(50), nullable=False)  # ej. "Precio demo: $19.990"
    features: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), unique=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    # active | canceled | past_due | trialing
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Reservado para integrar Stripe u otro proveedor más adelante — no se
    # usa todavía (pagos reales fuera de alcance de esta fase).
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    store: Mapped["Store"] = relationship(back_populates="subscription")  # noqa: F821
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")
