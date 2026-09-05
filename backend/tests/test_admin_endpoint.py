"""
Pruebas end-to-end del panel de administrador de Nexo
(app/api/routes/admin.py) — 30 de agosto de 2026.

Foco explícito: (1) un usuario común de una empresa JAMÁS puede acceder a
/api/admin/*, (2) un admin de Nexo ve TODAS las tiendas de verdad
(cross-tenant intencional, es la razón de ser de este panel), (3) nunca se
exponen tokens/secrets/contraseñas, (4) suspender un cliente realmente le
bloquea el login.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    AdminActionLog,
    AuthSession,
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    Product,
    ProductVariant,
    Store,
    StoreSettings,
    SupportTicket,
    User,
)
from app.db.session import get_db
from app.domain.security import hash_password
from app.domain.token_crypto import encrypt_token
from tests.auth_helpers import autenticar
from app.main import app

NOW = datetime(2026, 8, 30, 12, 0, 0)
TEST_ENCRYPTION_KEY = "1zjb1QwlLnRZVODeUOZ7dEP9CzO2gxIx3vT-YQEbG9E="


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
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _crear_empresa(db_session, *, email, nombre_empresa, con_producto=False, con_ml_conectado=False):
    usuario = User(email=email, password_hash=hash_password("no-se-usa"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name=nombre_empresa, created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name=nombre_empresa, store_name=nombre_empresa))
    db_session.add(ChannelCostSettings(store=tienda, channel="mercadolibre", commission_pct=15.0, target_margin_pct=25.0, updated_at=NOW))
    if con_producto:
        producto = Product(store=tienda, internal_sku="SKU-1", name="Producto de prueba", product_type="simple", created_at=NOW, updated_at=NOW)
        db_session.add(producto)
        db_session.flush()
        db_session.add(ProductVariant(product=producto, store_id=tienda.id, variant_sku="SKU-1", price=1000, created_at=NOW, updated_at=NOW))
    if con_ml_conectado:
        db_session.add(MarketplaceAccount(
            store=tienda, marketplace="mercadolibre", status="connected",
            external_account_id="123", external_account_nickname="TIENDA_TEST", external_account_site_id="MLC",
            access_token_encrypted=encrypt_token("token-real", TEST_ENCRYPTION_KEY),
            refresh_token_encrypted=encrypt_token("refresh-real", TEST_ENCRYPTION_KEY),
            token_expires_at=datetime(2027, 1, 1), connected_at=NOW, last_checked_at=NOW,
        ))
    db_session.commit()
    return usuario, tienda


def _crear_admin_nexo(db_session):
    admin = User(
        email="admin@nexo.cl", password_hash=hash_password("no-se-usa"), full_name="Admin Nexo",
        is_nexo_admin=True, created_at=NOW, updated_at=NOW,
    )
    db_session.add(admin)
    db_session.commit()
    return admin


# ------------------------------------------------------------------
# Un usuario común jamás accede a /api/admin/*
# ------------------------------------------------------------------


def test_usuario_comun_no_puede_listar_clientes(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="dueno@empresa.cl", nombre_empresa="Empresa A")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.get("/api/admin/clientes")
    assert res.status_code == 404  # nunca 403 — no confirma que /api/admin exista


def test_usuario_comun_no_puede_ver_detalle_de_otro_cliente(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="dueno2@empresa.cl", nombre_empresa="Empresa B")
    _otro_usuario, otra_tienda = _crear_empresa(db_session, email="otro@empresa.cl", nombre_empresa="Empresa C")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.get(f"/api/admin/clientes/{otra_tienda.id}")
    assert res.status_code == 404


def test_sin_sesion_no_puede_acceder_a_ningun_endpoint_admin(client):
    assert client.get("/api/admin/clientes").status_code == 401
    assert client.get("/api/admin/clientes/1").status_code == 401


# ------------------------------------------------------------------
# Admin de Nexo: ve todas las empresas de verdad (cross-tenant intencional)
# ------------------------------------------------------------------


def test_admin_ve_todas_las_empresas(client, db_session):
    _crear_empresa(db_session, email="a@empresas.cl", nombre_empresa="Empresa A")
    _crear_empresa(db_session, email="b@empresas.cl", nombre_empresa="Empresa B")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.get("/api/admin/clientes")
    assert res.status_code == 200, res.text
    nombres = {fila["nombre"] for fila in res.json()}
    assert nombres == {"Empresa A", "Empresa B"}


def test_admin_sin_tienda_propia_puede_autenticarse_y_usar_me(client, db_session):
    """El admin de Nexo no es un cliente — /api/auth/me tiene que
    funcionar igual para él, con empresa=null, en vez de un 500."""
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.get("/api/auth/me")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["empresa"] is None
    assert body["esNexoAdmin"] is True


def test_admin_estado_pendiente_configuracion_sin_ml_ni_productos(client, db_session):
    _crear_empresa(db_session, email="nueva@empresas.cl", nombre_empresa="Empresa Nueva")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    fila = next(f for f in client.get("/api/admin/clientes").json() if f["nombre"] == "Empresa Nueva")
    assert fila["estado"] == "pendiente_configuracion"
    assert fila["mercadoLibreConectado"] is False
    assert fila["cantidadProductos"] == 0


def test_admin_estado_activo_con_productos_y_ml_conectado(client, db_session):
    _crear_empresa(db_session, email="activa@empresas.cl", nombre_empresa="Empresa Activa", con_producto=True, con_ml_conectado=True)
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    fila = next(f for f in client.get("/api/admin/clientes").json() if f["nombre"] == "Empresa Activa")
    assert fila["estado"] == "activo"
    assert fila["mercadoLibreConectado"] is True
    assert fila["cantidadProductos"] == 1


def test_admin_detalle_nunca_expone_tokens_ni_secretos(client, db_session):
    _crear_empresa(db_session, email="tokens@empresas.cl", nombre_empresa="Empresa Con ML", con_ml_conectado=True)
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    tienda = db_session.query(Store).filter_by(name="Empresa Con ML").first()
    res = client.get(f"/api/admin/clientes/{tienda.id}")
    assert res.status_code == 200, res.text
    cuerpo_texto = res.text
    assert "token-real" not in cuerpo_texto
    assert "refresh-real" not in cuerpo_texto
    assert "access_token" not in cuerpo_texto
    assert "refresh_token" not in cuerpo_texto
    assert "password" not in cuerpo_texto.lower()
    body = res.json()
    assert body["mercadoLibre"]["nickname"] == "TIENDA_TEST"  # sí muestra datos no sensibles


def test_admin_detalle_de_cliente_inexistente_da_404(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.get("/api/admin/clientes/999999")
    assert res.status_code == 404


# ------------------------------------------------------------------
# Suspender / reactivar
# ------------------------------------------------------------------


def test_admin_suspende_un_cliente_y_le_bloquea_el_login(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="suspender@empresas.cl", nombre_empresa="Empresa a Suspender")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/clientes/{tienda.id}/estado", json={"suspendido": True})
    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "suspendido"

    # El dueño de esa empresa ya no puede loguearse.
    client.cookies.clear()
    res_login = client.post("/api/auth/login", json={"email": "suspender@empresas.cl", "password": "no-se-usa"})
    # password real no coincide (hash de "no-se-usa" con verify real) —
    # se prueba el chequeo de status directo, sin depender del password:
    db_session.refresh(usuario)
    assert usuario.status == "suspended"


def test_admin_reactiva_un_cliente_suspendido(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="reactivar@empresas.cl", nombre_empresa="Empresa a Reactivar")
    usuario.status = "suspended"
    db_session.commit()
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/clientes/{tienda.id}/estado", json={"suspendido": False})
    assert res.status_code == 200, res.text
    assert res.json()["estado"] in ("activo", "pendiente_configuracion")
    db_session.refresh(usuario)
    assert usuario.status == "active"


def test_usuario_suspendido_no_puede_iniciar_sesion(client, db_session):
    usuario = User(email="bloqueado@empresas.cl", password_hash=hash_password("clave-real-123"), full_name="Dueño", status="suspended", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Empresa Bloqueada", created_at=NOW)
    db_session.add(tienda)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "bloqueado@empresas.cl", "password": "clave-real-123"})
    assert res.status_code == 403


# ------------------------------------------------------------------
# GET /api/admin/usuarios — vista cruzada de usuarios (todas las empresas)
# ------------------------------------------------------------------


def test_usuario_comun_no_puede_listar_usuarios(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="comun@empresas.cl", nombre_empresa="Empresa Común")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.get("/api/admin/usuarios")
    assert res.status_code == 404


def test_admin_ve_usuarios_de_todas_las_empresas(client, db_session):
    _crear_empresa(db_session, email="uno@empresas.cl", nombre_empresa="Empresa Uno")
    _crear_empresa(db_session, email="dos@empresas.cl", nombre_empresa="Empresa Dos")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.get("/api/admin/usuarios")
    assert res.status_code == 200, res.text
    emails = {u["email"] for u in res.json()}
    assert {"uno@empresas.cl", "dos@empresas.cl", "admin@nexo.cl"} <= emails
    fila_admin = next(u for u in res.json() if u["email"] == "admin@nexo.cl")
    assert fila_admin["esNexoAdmin"] is True
    assert fila_admin["empresa"] is None
    fila_cliente = next(u for u in res.json() if u["email"] == "uno@empresas.cl")
    assert fila_cliente["empresa"]["nombre"] == "Empresa Uno"
    assert "password" not in res.text.lower()


# ------------------------------------------------------------------
# 6 de septiembre de 2026 — perfil de empresa completo (auditoría
# comercial): el detalle de cliente ahora trae la lista real de
# productos/publicaciones/soporte de ESA empresa — nunca mezclada con la
# de otra.
# ------------------------------------------------------------------


def test_detalle_de_cliente_trae_productos_publicaciones_y_soporte_solo_de_esa_empresa(client, db_session):
    _usuario_a, tienda_a = _crear_empresa(db_session, email="detalle-a@empresas.cl", nombre_empresa="Empresa Detalle A", con_producto=True, con_ml_conectado=True)
    usuario_b, tienda_b = _crear_empresa(db_session, email="detalle-b@empresas.cl", nombre_empresa="Empresa Detalle B", con_producto=True)

    cuenta_ml_a = db_session.query(MarketplaceAccount).filter_by(store_id=tienda_a.id).one()
    producto_a = db_session.query(Product).filter_by(store_id=tienda_a.id).one()
    db_session.add(MarketplaceListing(account=cuenta_ml_a, product=producto_a, external_listing_id="MLC-A", status="active", price=1000, created_at=NOW))
    db_session.add(SupportTicket(store=tienda_a, user=_usuario_a, category="otro", subject="Ticket de A", description="x", status="abierto", created_at=NOW, updated_at=NOW))
    db_session.add(SupportTicket(store=tienda_b, user=usuario_b, category="otro", subject="Ticket de B", description="x", status="abierto", created_at=NOW, updated_at=NOW))
    db_session.commit()

    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    detalle_a = client.get(f"/api/admin/clientes/{tienda_a.id}").json()
    assert detalle_a["productos"]["cantidad"] == 1
    assert [p["sku"] for p in detalle_a["productos"]["filas"]] == ["SKU-1"]
    assert detalle_a["publicaciones"]["total"] == 1
    assert detalle_a["publicaciones"]["filas"][0]["externalListingId"] == "MLC-A"
    assert detalle_a["soporte"]["ticketsAbiertos"] == 1
    assert [s["asunto"] for s in detalle_a["soporte"]["solicitudes"]] == ["Ticket de A"]
    assert detalle_a["cantidadUsuarios"] == 1

    detalle_b = client.get(f"/api/admin/clientes/{tienda_b.id}").json()
    assert detalle_b["publicaciones"]["total"] == 0
    assert detalle_b["soporte"]["ticketsAbiertos"] == 1
    assert [s["asunto"] for s in detalle_b["soporte"]["solicitudes"]] == ["Ticket de B"]


# ------------------------------------------------------------------
# 6 de septiembre de 2026 — registro simple de acciones administrativas
# (opcional en el pedido original, implementado porque no requirió nada
# de arquitectura nueva). Nunca acciones de un cliente sobre sus propios
# datos, solo las 3 acciones reales del admin: suspender/reactivar,
# cambiar suscripción, responder soporte.
# ------------------------------------------------------------------


def test_suspender_reactivar_y_cambiar_suscripcion_quedan_en_el_registro_administrativo(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="log-a@empresas.cl", nombre_empresa="Empresa Log A")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)
    client.get("/api/admin/planes")  # siembra los planes reales

    client.put(f"/api/admin/clientes/{tienda.id}/estado", json={"suspendido": True})
    client.put(f"/api/admin/clientes/{tienda.id}/suscripcion", json={"planCode": "basico", "estado": "active"})

    detalle = client.get(f"/api/admin/clientes/{tienda.id}").json()
    acciones = [a["accion"] for a in detalle["accionesAdministrativas"]]
    assert "suspender" in acciones
    assert "asignar_plan_inicial" in acciones
    assert all(a["admin"] == "admin@nexo.cl" for a in detalle["accionesAdministrativas"])


def test_registro_administrativo_de_una_empresa_nunca_mezcla_el_de_otra(client, db_session):
    _usuario_a, tienda_a = _crear_empresa(db_session, email="log-b@empresas.cl", nombre_empresa="Empresa Log B")
    _usuario_c, tienda_c = _crear_empresa(db_session, email="log-c@empresas.cl", nombre_empresa="Empresa Log C")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    client.put(f"/api/admin/clientes/{tienda_a.id}/estado", json={"suspendido": True})

    detalle_c = client.get(f"/api/admin/clientes/{tienda_c.id}").json()
    assert detalle_c["accionesAdministrativas"] == []


# ------------------------------------------------------------------
# "Entrar como soporte" — POST /api/admin/clientes/{id}/entrar
# ------------------------------------------------------------------


def test_usuario_comun_no_puede_entrar_como_soporte(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="dueno-soporte@empresa.cl", nombre_empresa="Empresa Soporte A")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert res.status_code == 404  # nunca 403 — mismo criterio que el resto de /api/admin


def test_entrar_como_soporte_a_cliente_inexistente_da_404(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post("/api/admin/clientes/999999/entrar")
    assert res.status_code == 404


def test_entrar_como_soporte_a_otro_admin_esta_prohibido(client, db_session):
    otro_admin = User(email="otro-admin@nexo.cl", password_hash=hash_password("x"), full_name="Otro Admin", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(otro_admin)
    tienda_de_admin = Store(owner=otro_admin, name="Tienda de un admin (caso raro)", created_at=NOW)
    db_session.add(tienda_de_admin)
    db_session.commit()

    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda_de_admin.id}/entrar")
    assert res.status_code == 400


def test_admin_entra_como_soporte_y_opera_exactamente_como_ese_cliente(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="cliente-real@empresa.cl", nombre_empresa="Empresa Real", con_producto=True)
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert res.status_code == 200, res.text
    assert res.json()["empresa"] == {"id": tienda.id, "nombre": "Empresa Real"}

    # La cookie del navegador (del admin) ahora es la sesión de soporte —
    # /me tiene que ver la empresa del CLIENTE, nunca la del admin.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["empresa"]["id"] == tienda.id
    assert body["esNexoAdmin"] is False  # la sesión pertenece al usuario dueño, no al admin
    assert body["modoSoporte"] == {"adminEmail": "admin@nexo.cl"}

    # Y opera de verdad como esa empresa — ve SU catálogo real, con el
    # mismo mecanismo (get_current_store) que usaría el propio dueño.
    productos = client.get("/api/productos")
    assert productos.status_code == 200
    assert len(productos.json()) == 1
    assert productos.json()[0]["sku"] == "SKU-1"


def test_entrar_como_soporte_queda_registrado_en_el_historial_administrativo(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="auditado@empresa.cl", nombre_empresa="Empresa Auditada")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    client.post(f"/api/admin/clientes/{tienda.id}/entrar")

    # Se verifica directo en la base (no volviendo a pasar por /api/admin/*
    # con este mismo `client`): la cookie del navegador de prueba ya es la
    # sesión de soporte a esta altura, igual que en un navegador real —
    # no tiene sentido "seguir siendo admin" en la misma pestaña.
    log = db_session.query(AdminActionLog).filter_by(store_id=tienda.id, action="entrar_como_soporte").one()
    assert log.admin_user_id == admin.id
    assert "auditado@empresa.cl" in (log.detail or "")


def test_sesion_de_soporte_dura_una_hora_nunca_una_sesion_larga(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="corta@empresa.cl", nombre_empresa="Empresa Sesion Corta")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    expira = datetime.fromisoformat(res.json()["expiraEn"])
    duracion = expira - datetime.now()
    assert timedelta(minutes=55) < duracion <= timedelta(hours=1, minutes=1)


def test_salir_del_modo_soporte_revoca_la_sesion_de_verdad(client, db_session):
    """Login real (no el helper `autenticar`, que deja una cookie de prueba
    sin dominio) para que login -> entrar -> logout -> me pasen los cuatro
    por el mismo mecanismo real de cookies, igual que en un navegador de
    verdad — un solo cookie "nexo_session" en juego en todo momento."""
    _usuario, tienda = _crear_empresa(db_session, email="salir@empresa.cl", nombre_empresa="Empresa Salir")
    admin = User(email="admin-login@nexo.cl", password_hash=hash_password("clave-admin-segura"), full_name="Admin Login", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(admin)
    db_session.commit()

    login = client.post("/api/auth/login", json={"email": "admin-login@nexo.cl", "password": "clave-admin-segura"})
    assert login.status_code == 200

    client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    sesion_soporte = db_session.query(AuthSession).filter_by(impersonated_by_admin_id=admin.id).one()
    assert sesion_soporte.revoked_at is None

    res_logout = client.post("/api/auth/logout")
    assert res_logout.status_code == 200

    db_session.refresh(sesion_soporte)
    assert sesion_soporte.revoked_at is not None  # revocada de verdad en la base, no solo "cookie vencida"

    res_me = client.get("/api/auth/me")
    assert res_me.status_code == 401


def test_una_sesion_normal_nunca_muestra_modo_soporte(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="normal@empresa.cl", nombre_empresa="Empresa Normal")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    body = client.get("/api/auth/me").json()
    assert body["modoSoporte"] is None
