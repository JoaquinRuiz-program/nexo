"""
Planes y suscripciones.

6 de septiembre de 2026 — cobro real con Mercado Pago (ver
app/adapters/mercadopago.py, app/api/routes/pagos.py): `monthly_price_clp`
es el precio real en pesos chilenos, el único que se usa para calcular
montos a cobrar (nunca se parsea `price_demo_label`, que es solo el texto
que ve el cliente). Las columnas de Stripe quedan reservadas y nulas —
Nexo integró Mercado Pago, no Stripe, pero no hay razón para borrar
columnas ya migradas que no molestan a nadie.
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
    # 6 de septiembre de 2026 — precio REAL en CLP, mensual, sin IVA/recargos
    # (el único número que usa app/api/routes/pagos.py para calcular cuánto
    # cobrarle a Mercado Pago — price_demo_label es texto para mostrar,
    # nunca se parsea para cobrar). Nullable: un plan a medida ("empresarial",
    # precio a coordinar con el dueño) puede no tener un precio de catálogo.
    monthly_price_clp: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    # mensual | anual — solo tiene sentido cuando el pago es real (Mercado
    # Pago); una suscripción trial o asignada a mano por el admin no tiene
    # ciclo de cobro todavía, por eso nullable.
    billing_cycle: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # ID real de la suscripción recurrente en Mercado Pago (plan mensual,
    # ver POST /preapproval) — None hasta el primer pago real o si el ciclo
    # es anual (que no usa una suscripción recurrente de Mercado Pago, ver
    # docstring de app/adapters/mercadopago.py sobre por qué).
    mercadopago_preapproval_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # ID del último pago real aprobado en Mercado Pago — de un pago único
    # (ciclo anual) o de un cobro recurrente autorizado (ciclo mensual).
    # Sirve para auditoría/soporte ("¿este pago fue real? buscalo acá"),
    # nunca para decidir el estado de la suscripción (eso lo hace el
    # webhook, ver app/api/routes/pagos.py).
    mercadopago_last_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    store: Mapped["Store"] = relationship(back_populates="subscription")  # noqa: F821
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")
