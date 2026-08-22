"""
Pruebas de planes y suscripciones — sin ningún cobro real (las columnas de
Stripe quedan reservadas y vacías en esta fase).
"""

from __future__ import annotations

from app.db.models import Plan, Subscription


def test_plan_tiene_limite_de_productos_y_precio_marcado_como_demo(a_plan):
    assert a_plan.product_limit == 100
    assert "demo" in a_plan.price_demo_label.lower()


def test_plan_enterprise_puede_no_tener_limite(db_session):
    plan = Plan(code="enterprise", name="Enterprise", product_limit=None, price_demo_label="Precio demo: personalizado", features=[])
    db_session.add(plan)
    db_session.commit()
    assert plan.product_limit is None


def test_suscripcion_vincula_tienda_y_plan_sin_datos_de_pago_reales(a_subscription):
    assert a_subscription.status == "active"
    assert a_subscription.plan.code == "starter"
    # Reservado para Stripe, pero vacío — no se implementa cobro real todavía.
    assert a_subscription.stripe_customer_id is None
    assert a_subscription.stripe_subscription_id is None


def test_una_tienda_tiene_a_lo_sumo_una_suscripcion_activa(a_store, a_subscription):
    assert a_store.subscription is not None
    assert a_store.subscription.id == a_subscription.id
