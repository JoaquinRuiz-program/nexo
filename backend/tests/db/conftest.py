"""
Fixtures para las pruebas del modelo de datos. Cada prueba corre contra una
base SQLite en memoria completamente aislada (no contra el archivo
`libreria_central.db` real, y por supuesto sin tocar WooCommerce ni
Mercado Libre) — se crea el esquema completo desde los modelos antes de
cada prueba y se descarta al terminar.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    Plan,
    Store,
    StoreSettings,
    Subscription,
    User,
    UserPreferences,
)
from app.db.session import build_engine
from app.domain.security import hash_password


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: ANN001
    """SQLite ignora las claves foráneas por defecto — sin esto, las
    pruebas de integridad referencial no probarían nada de verdad."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def db_session():
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(bind=engine, future=True)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def now():
    return datetime(2026, 8, 22, 12, 0, 0)


@pytest.fixture()
def a_user(db_session, now):
    user = User(
        email="dueno@lalibreriaonlineoficial.cl",
        password_hash=hash_password("una-contraseña-segura"),
        full_name="Joaquín Ruiz",
        status="active",
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    db_session.add(UserPreferences(user=user, theme="auto"))
    db_session.commit()
    return user


@pytest.fixture()
def a_store(db_session, a_user, now):
    store = Store(owner=a_user, name="La Librería Online", created_at=now)
    db_session.add(store)
    db_session.add(StoreSettings(store=store, company_name="Librería Central", store_name="La Librería Online"))
    db_session.commit()
    return store


@pytest.fixture()
def a_plan(db_session):
    plan = Plan(
        code="starter",
        name="Starter",
        product_limit=100,
        price_demo_label="Precio demo: $9.990",
        features=["Hasta 100 productos", "Sincronización básica"],
    )
    db_session.add(plan)
    db_session.commit()
    return plan


@pytest.fixture()
def a_subscription(db_session, a_store, a_plan, now):
    sub = Subscription(
        store=a_store,
        plan=a_plan,
        status="active",
        started_at=now,
        current_period_end=(now + timedelta(days=30)).date(),
    )
    db_session.add(sub)
    db_session.commit()
    return sub
