"""
Pruebas end-to-end de suscripciones — 5 de septiembre de 2026.

Cubre: una empresa nueva recibe plan automáticamente al registrarse (ver
app/domain/plans.py), un cliente solo ve/usa la suya, jamás la de otra
empresa, y solo el administrador de Nexo puede modificar plan/estado
(nunca el propio cliente, ni con un request manipulado).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Plan, Product, Store, StoreSettings, Subscription, User
from app.db.session import get_db
from app.domain.security import hash_password
from tests.auth_helpers import autenticar
from app.main import app

NOW = datetime(2026, 9, 5, 12, 0, 0)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    session = Session(bind=engine, future=True)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _crear_empresa(db_session, *, email, nombre_empresa, con_suscripcion=True, status="active", plan_kwargs=None):
    usuario = User(email=email, password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name=nombre_empresa, created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name=nombre_empresa, store_name=nombre_empresa))
    if con_suscripcion:
        datos_plan = {"product_limit": 5, "publication_limit": 5, **(plan_kwargs or {})}
        plan = Plan(code=f"plan-{tienda.name}", name="Plan de prueba", price_demo_label="Precio demo: $0", **datos_plan)
        db_session.add(plan)
        db_session.flush()
        db_session.add(Subscription(store=tienda, plan=plan, status=status, started_at=NOW, current_period_end=NOW.date()))
    db_session.commit()
    return usuario, tienda


def _crear_admin_nexo(db_session):
    admin = User(email="admin@nexo.cl", password_hash=hash_password("x"), full_name="Admin Nexo", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(admin)
    db_session.commit()
    return admin


# ------------------------------------------------------------------
# Registro asigna un plan automáticamente
# ------------------------------------------------------------------


def test_registro_asigna_una_suscripcion_trial_automaticamente(client, db_session):
    res = client.post("/api/auth/registro", json={
        "email": "nueva@empresa.cl", "password": "contraseña-segura", "full_name": "Nueva", "company_name": "Empresa Nueva",
    })
    assert res.status_code == 200, res.text

    tienda = db_session.query(Store).filter_by(name="Empresa Nueva").one()
    assert tienda.subscription is not None
    assert tienda.subscription.status == "trialing"
    assert tienda.subscription.plan is not None
    assert tienda.subscription.plan.code == "basico"


# ------------------------------------------------------------------
# GET /api/suscripcion — cada empresa ve únicamente la suya
# ------------------------------------------------------------------


def test_obtener_mi_suscripcion_devuelve_plan_estado_y_uso(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="a@empresa.cl", nombre_empresa="Empresa A", status="active")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.get("/api/suscripcion")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "active"
    assert body["plan"]["limiteProductos"] == 5
    assert body["uso"]["productos"] == 0


def test_obtener_mi_suscripcion_sin_suscripcion_no_inventa_un_plan(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="b@empresa.cl", nombre_empresa="Empresa B", con_suscripcion=False)
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.get("/api/suscripcion")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plan"] is None
    assert body["estado"] is None


def test_mi_suscripcion_nunca_expone_la_de_otra_empresa(client, db_session):
    _crear_empresa(db_session, email="c@empresa.cl", nombre_empresa="Empresa C", plan_kwargs={"product_limit": 999})
    usuario_d, tienda_d = _crear_empresa(db_session, email="d@empresa.cl", nombre_empresa="Empresa D", plan_kwargs={"product_limit": 3})
    autenticar(client, db_session, usuario_d, tienda_d, ahora=NOW)

    res = client.get("/api/suscripcion")
    assert res.status_code == 200, res.text
    assert res.json()["plan"]["limiteProductos"] == 3  # nunca 999 (la de la otra empresa)


# ------------------------------------------------------------------
# Solo el administrador de Nexo puede modificar plan/estado
# ------------------------------------------------------------------


def test_usuario_normal_no_puede_modificar_su_propia_suscripcion(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="e@empresa.cl", nombre_empresa="Empresa E")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    # No existe ningún endpoint de cliente para esto -- el único PUT vive
    # bajo /api/admin/*, protegido por require_nexo_admin.
    res = client.put(f"/api/admin/clientes/{tienda.id}/suscripcion", json={"estado": "active"})
    assert res.status_code == 404


def test_admin_puede_cambiar_plan_y_estado_de_una_empresa(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="f@empresa.cl", nombre_empresa="Empresa F", status="trialing")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)
    # El plan "pro" real lo siembra ensure_default_plans (ver
    # app/domain/plans.py) — GET /planes es lo que lo dispara desde el panel.
    assert client.get("/api/admin/planes").status_code == 200

    res = client.put(f"/api/admin/clientes/{tienda.id}/suscripcion", json={"planCode": "pro", "estado": "active"})
    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "active"
    assert res.json()["plan"] == "pro"

    db_session.refresh(tienda)
    assert tienda.subscription.status == "active"
    assert tienda.subscription.plan.code == "pro"


def test_admin_no_puede_poner_un_estado_invalido(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="g@empresa.cl", nombre_empresa="Empresa G")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/clientes/{tienda.id}/suscripcion", json={"estado": "algo_inventado"})
    assert res.status_code == 400


def test_admin_puede_asignar_una_primera_suscripcion_a_una_empresa_vieja_sin_ninguna(client, db_session):
    """6 de septiembre de 2026 — hallazgo real de la auditoría comercial:
    una empresa creada antes del sistema de planes (con_suscripcion=False,
    mismo caso que las tiendas reales de antes de esta fase) no tenía
    ninguna forma de recibir un plan desde el panel — quedaba bloqueada
    para siempre en "sin suscripción"."""
    _usuario, tienda = _crear_empresa(db_session, email="vieja@empresa.cl", nombre_empresa="Empresa Vieja", con_suscripcion=False)
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)
    assert client.get("/api/admin/planes").status_code == 200  # siembra los planes reales

    res = client.put(f"/api/admin/clientes/{tienda.id}/suscripcion", json={"planCode": "basico", "estado": "active"})
    assert res.status_code == 200, res.text
    assert res.json()["plan"] == "basico"
    assert res.json()["estado"] == "active"

    db_session.refresh(tienda)
    assert tienda.subscription is not None
    assert tienda.subscription.plan.code == "basico"


def test_admin_sin_indicar_plan_para_una_empresa_sin_suscripcion_da_400_claro(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="vieja2@empresa.cl", nombre_empresa="Empresa Vieja 2", con_suscripcion=False)
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/clientes/{tienda.id}/suscripcion", json={"estado": "active"})
    assert res.status_code == 400
    assert "ninguna suscripción" in res.json()["detail"]


# ------------------------------------------------------------------
# Límite de productos: nunca se puede manipular desde el frontend
# ------------------------------------------------------------------


def test_limite_de_productos_se_evalua_siempre_en_el_backend(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="h@empresa.cl", nombre_empresa="Empresa H", plan_kwargs={"product_limit": 1})
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    db_session.add(Product(store=tienda, internal_sku="YA-1", name="Ya existente", product_type="simple", created_at=NOW, updated_at=NOW))
    db_session.commit()

    import io
    import json as json_module
    csv = "SKU,Nombre,Precio\nNUEVO-1,Producto nuevo,1000\n"
    res = client.post(
        "/api/catalogo/importar/confirmar",
        files={"file": ("x.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"mapeo": json_module.dumps({"sku": "SKU", "nombre": "Nombre", "precio": "Precio"})},
    )
    assert res.status_code == 200, res.text
    assert res.json()["creados"] == 0
    assert res.json()["omitidos"] == 1
