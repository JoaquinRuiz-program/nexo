"""
Pruebas end-to-end de Ayuda y soporte — 5 de septiembre de 2026. Foco
explícito: aislamiento total entre empresas (un cliente jamás ve ni
modifica la solicitud de otra) y que el admin de Nexo sí ve todas.
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
from app.db.models import Store, StoreSettings, SupportTicket, User
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


def _crear_empresa(db_session, *, email, nombre_empresa):
    usuario = User(email=email, password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name=nombre_empresa, created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name=nombre_empresa, store_name=nombre_empresa))
    db_session.commit()
    return usuario, tienda


def _crear_admin_nexo(db_session):
    admin = User(email="admin@nexo.cl", password_hash=hash_password("x"), full_name="Admin Nexo", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(admin)
    db_session.commit()
    return admin


def test_crear_solicitud_de_soporte(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="a@empresa.cl", nombre_empresa="Empresa A")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.post("/api/soporte/solicitudes", json={
        "category": "publicar", "subject": "No puedo publicar", "description": "Me da error al confirmar.",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estado"] == "abierto"
    assert body["categoria"] == "publicar"


def test_categoria_invalida_es_rechazada(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="b@empresa.cl", nombre_empresa="Empresa B")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.post("/api/soporte/solicitudes", json={
        "category": "categoria-inventada", "subject": "X", "description": "Y",
    })
    assert res.status_code == 422


def test_listar_mis_solicitudes_nunca_incluye_las_de_otra_empresa(client, db_session):
    usuario_a, tienda_a = _crear_empresa(db_session, email="c@empresa.cl", nombre_empresa="Empresa C")
    usuario_b, tienda_b = _crear_empresa(db_session, email="d@empresa.cl", nombre_empresa="Empresa D")
    db_session.add(SupportTicket(store=tienda_a, user=usuario_a, category="otro", subject="De A", description="x", status="abierto", created_at=NOW, updated_at=NOW))
    db_session.add(SupportTicket(store=tienda_b, user=usuario_b, category="otro", subject="De B", description="x", status="abierto", created_at=NOW, updated_at=NOW))
    db_session.commit()

    autenticar(client, db_session, usuario_a, tienda_a, ahora=NOW)
    res = client.get("/api/soporte/solicitudes")
    assert res.status_code == 200
    asuntos = {s["asunto"] for s in res.json()}
    assert asuntos == {"De A"}


def test_no_puede_leer_el_detalle_de_una_solicitud_de_otra_empresa(client, db_session):
    usuario_a, tienda_a = _crear_empresa(db_session, email="e@empresa.cl", nombre_empresa="Empresa E")
    usuario_b, tienda_b = _crear_empresa(db_session, email="f@empresa.cl", nombre_empresa="Empresa F")
    ticket_b = SupportTicket(store=tienda_b, user=usuario_b, category="otro", subject="De B", description="x", status="abierto", created_at=NOW, updated_at=NOW)
    db_session.add(ticket_b)
    db_session.commit()

    autenticar(client, db_session, usuario_a, tienda_a, ahora=NOW)
    res = client.get(f"/api/soporte/solicitudes/{ticket_b.id}")
    assert res.status_code == 404


def test_usuario_normal_no_puede_acceder_al_soporte_admin(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="g@empresa.cl", nombre_empresa="Empresa G")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    assert client.get("/api/admin/soporte/solicitudes").status_code == 404


def test_admin_ve_todas_las_solicitudes_y_puede_responder_y_cerrar(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="h@empresa.cl", nombre_empresa="Empresa H")
    ticket = SupportTicket(store=tienda, user=usuario, category="cuenta", subject="Problema de cuenta", description="Detalle", status="abierto", created_at=NOW, updated_at=NOW)
    db_session.add(ticket)
    db_session.commit()
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res_listar = client.get("/api/admin/soporte/solicitudes")
    assert res_listar.status_code == 200
    assert len(res_listar.json()) == 1
    assert res_listar.json()[0]["empresa"]["nombre"] == "Empresa H"

    res_responder = client.put(f"/api/admin/soporte/solicitudes/{ticket.id}", json={"respuesta": "Ya lo revisamos.", "estado": "resuelto"})
    assert res_responder.status_code == 200, res_responder.text
    assert res_responder.json()["estado"] == "resuelto"
    assert res_responder.json()["respuestaAdmin"] == "Ya lo revisamos."

    # El cliente ve la respuesta.
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    res_cliente = client.get(f"/api/soporte/solicitudes/{ticket.id}")
    assert res_cliente.json()["respuestaAdmin"] == "Ya lo revisamos."
    assert res_cliente.json()["estado"] == "resuelto"


def test_responder_sin_estado_explicito_mueve_de_abierto_a_en_revision(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="i@empresa.cl", nombre_empresa="Empresa I")
    ticket = SupportTicket(store=tienda, user=usuario, category="otro", subject="X", description="Y", status="abierto", created_at=NOW, updated_at=NOW)
    db_session.add(ticket)
    db_session.commit()
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/soporte/solicitudes/{ticket.id}", json={"respuesta": "Estamos viendo esto."})
    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "en_revision"
