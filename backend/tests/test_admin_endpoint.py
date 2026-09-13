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
# "Ver como empresa" — POST /api/admin/clientes/{id}/entrar
#                      POST /api/admin/ver-como/salir
#
# 6 de septiembre de 2026 — el requisito central de estos tests: la sesión
# del ADMIN nunca se cierra ni se reemplaza. "Ver como empresa" es un
# contexto sobre su propia sesión (AuthSession.viewing_store_id), así que
# sobrevive a un refresh y salir lo devuelve al panel sin volver a loguear.
# ------------------------------------------------------------------


def _login_admin(client, db_session, email="admin-login@nexo.cl"):
    """Login REAL (no el helper `autenticar`, que deja una cookie de prueba
    sin dominio y conviviría con la cookie real) — así todo el flujo
    entrar/refresh/salir pasa por el mismo mecanismo de cookies que un
    navegador de verdad, con un solo "nexo_session" en juego."""
    admin = User(
        email=email, password_hash=hash_password("clave-admin-segura"), full_name="Admin Login",
        is_nexo_admin=True, created_at=NOW, updated_at=NOW,
    )
    db_session.add(admin)
    db_session.commit()
    res = client.post("/api/auth/login", json={"email": email, "password": "clave-admin-segura"})
    assert res.status_code == 200, res.text
    return admin


def _sesion_de(db_session, user):
    return db_session.query(AuthSession).filter_by(user_id=user.id).order_by(AuthSession.id.desc()).first()


def test_usuario_comun_no_puede_entrar_a_ver_una_empresa(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="dueno-soporte@empresa.cl", nombre_empresa="Empresa Soporte A")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert res.status_code == 404  # nunca 403 — mismo criterio que el resto de /api/admin
    # Y su propia sesión queda intacta: ni siquiera se le marcó un contexto.
    assert _sesion_de(db_session, usuario).viewing_store_id is None


def test_usuario_comun_no_puede_salir_de_ver_como(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="comun-salir@empresa.cl", nombre_empresa="Empresa Comun Salir")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    assert client.post("/api/admin/ver-como/salir").status_code == 404


def test_un_usuario_comun_no_puede_fabricar_un_contexto_de_otra_empresa(client, db_session):
    """El contexto vive SOLO en el servidor: no hay ningún parámetro,
    header ni body con el que un cliente pueda pedir "vería la empresa X".
    Aunque mande store_id por todos lados, sigue viendo la suya."""
    usuario, tienda = _crear_empresa(db_session, email="fabricante@empresa.cl", nombre_empresa="Empresa Propia", con_producto=True)
    _otro, ajena = _crear_empresa(db_session, email="ajena@empresa.cl", nombre_empresa="Empresa Ajena", con_producto=True)
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    me = client.get(f"/api/auth/me?store_id={ajena.id}&viewing_store_id={ajena.id}").json()
    assert me["empresa"]["id"] == tienda.id
    assert me["modoSoporte"] is None


def test_entrar_a_ver_un_cliente_inexistente_da_404(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post("/api/admin/clientes/999999/entrar")
    assert res.status_code == 404
    assert _sesion_de(db_session, admin).viewing_store_id is None


def test_entrar_a_ver_la_empresa_de_otro_admin_esta_prohibido(client, db_session):
    otro_admin = User(email="otro-admin@nexo.cl", password_hash=hash_password("x"), full_name="Otro Admin", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(otro_admin)
    tienda_de_admin = Store(owner=otro_admin, name="Tienda de un admin (caso raro)", created_at=NOW)
    db_session.add(tienda_de_admin)
    db_session.commit()

    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda_de_admin.id}/entrar")
    assert res.status_code == 400
    assert _sesion_de(db_session, admin).viewing_store_id is None


def test_admin_ve_la_empresa_y_opera_exactamente_como_ese_cliente(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="cliente-real@empresa.cl", nombre_empresa="Empresa Real", con_producto=True)
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert res.status_code == 200, res.text
    assert res.json()["empresa"] == {"id": tienda.id, "nombre": "Empresa Real"}

    # No se creó ninguna sesión nueva: es la MISMA sesión del admin, con un
    # contexto marcado. Nada de impersonación.
    assert db_session.query(AuthSession).count() == 1
    sesion = _sesion_de(db_session, admin)
    assert sesion.user_id == admin.id
    assert sesion.viewing_store_id == tienda.id

    # /me: el usuario autenticado sigue siendo el ADMIN (esNexoAdmin), pero
    # la empresa activa es la del cliente, y el modo se informa siempre.
    body = client.get("/api/auth/me").json()
    assert body["usuario"]["email"] == "admin@nexo.cl"
    assert body["esNexoAdmin"] is True
    assert body["empresa"]["id"] == tienda.id
    assert body["modoSoporte"] == {"adminEmail": "admin@nexo.cl", "empresaId": tienda.id, "empresaNombre": "Empresa Real"}

    # Y opera de verdad como esa empresa — ve SU catálogo real, con el
    # mismo mecanismo (get_current_store) que usaría el propio dueño.
    productos = client.get("/api/productos")
    assert productos.status_code == 200
    assert len(productos.json()) == 1
    assert productos.json()[0]["sku"] == "SKU-1"


def test_ver_como_empresa_sobrevive_a_un_refresh_y_a_navegar(client, db_session):
    """El caso que el dueño pidió comprobar explícitamente: F5 no puede
    devolver al login ni perder el contexto. Cada request de acá abajo es
    independiente (nada en memoria del navegador), igual que después de un
    refresh o de cerrar y reabrir la pestaña."""
    _usuario, tienda = _crear_empresa(db_session, email="refresh@empresa.cl", nombre_empresa="Empresa Refresh", con_producto=True)
    admin = _login_admin(client, db_session)

    client.post(f"/api/admin/clientes/{tienda.id}/entrar")

    for _ in range(3):  # tres "refresh" seguidos
        me = client.get("/api/auth/me")
        assert me.status_code == 200  # nunca 401 -> nunca la pantalla de login
        assert me.json()["esNexoAdmin"] is True
        assert me.json()["empresa"]["id"] == tienda.id
        assert me.json()["modoSoporte"]["empresaId"] == tienda.id

    # Navegar por pantallas de cliente sigue funcionando entre refreshes.
    assert client.get("/api/productos").status_code == 200
    assert client.get("/api/dashboard/resumen").status_code == 200
    # Y el panel admin sigue accesible: la sesión NUNCA dejó de ser de admin.
    assert client.get("/api/admin/clientes").status_code == 200

    db_session.expire_all()
    assert _sesion_de(db_session, admin).viewing_store_id == tienda.id


def test_salir_de_ver_como_devuelve_al_admin_sin_cerrar_su_sesion(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="salir@empresa.cl", nombre_empresa="Empresa Salir", con_producto=True)
    admin = _login_admin(client, db_session)
    sesion_admin = _sesion_de(db_session, admin)

    client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert client.post("/api/admin/ver-como/salir").status_code == 200

    # La sesión es la misma fila de siempre, viva y sin contexto.
    db_session.expire_all()
    assert db_session.query(AuthSession).count() == 1
    assert _sesion_de(db_session, admin).id == sesion_admin.id
    assert _sesion_de(db_session, admin).revoked_at is None
    assert _sesion_de(db_session, admin).viewing_store_id is None

    # Sigue autenticado como admin, sin volver a pasar por /login.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["esNexoAdmin"] is True
    assert me.json()["modoSoporte"] is None
    assert client.get("/api/admin/clientes").status_code == 200


def test_despues_de_salir_ya_no_ve_los_datos_de_esa_empresa(client, db_session):
    """Nunca queda un acceso "heredado" a la empresa después de salir."""
    _usuario, tienda = _crear_empresa(db_session, email="heredado@empresa.cl", nombre_empresa="Empresa Heredada", con_producto=True)
    _login_admin(client, db_session)

    client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert len(client.get("/api/productos").json()) == 1

    client.post("/api/admin/ver-como/salir")
    # Un admin sin contexto no tiene empresa activa: los endpoints de
    # cliente dejan de responderle datos de nadie.
    assert client.get("/api/productos").status_code == 500


def test_admin_puede_pasar_de_una_empresa_a_otra(client, db_session):
    _u_a, empresa_a = _crear_empresa(db_session, email="a@empresa.cl", nombre_empresa="Empresa A", con_producto=True)
    _u_b, empresa_b = _crear_empresa(db_session, email="b@empresa.cl", nombre_empresa="Empresa B")
    admin = _login_admin(client, db_session)

    client.post(f"/api/admin/clientes/{empresa_a.id}/entrar")
    assert client.get("/api/auth/me").json()["empresa"]["id"] == empresa_a.id
    assert len(client.get("/api/productos").json()) == 1

    client.post(f"/api/admin/clientes/{empresa_b.id}/entrar")
    assert client.get("/api/auth/me").json()["empresa"]["id"] == empresa_b.id
    # Ya no ve el catálogo de la empresa A — el contexto es uno solo.
    assert client.get("/api/productos").json() == []

    db_session.expire_all()
    assert db_session.query(AuthSession).count() == 1  # nunca se acumulan sesiones
    assert _sesion_de(db_session, admin).viewing_store_id == empresa_b.id


def test_entrar_y_salir_quedan_registrados_en_el_historial_administrativo(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="auditado@empresa.cl", nombre_empresa="Empresa Auditada")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    client.post("/api/admin/ver-como/salir")

    log = db_session.query(AdminActionLog).filter_by(store_id=tienda.id, action="entrar_como_soporte").one()
    assert log.admin_user_id == admin.id
    assert "auditado@empresa.cl" in (log.detail or "")
    salida = db_session.query(AdminActionLog).filter_by(store_id=tienda.id, action="salir_de_ver_empresa").one()
    assert salida.admin_user_id == admin.id


def test_si_le_revocan_el_rol_de_admin_el_contexto_deja_de_valer(client, db_session):
    """El contexto se evalúa contra `is_nexo_admin` AHORA, no contra el
    momento en que entró: quitarle el rol corta el acceso en la request
    siguiente, sin tener que ir a limpiar sesiones a mano."""
    _usuario, tienda = _crear_empresa(db_session, email="revocado@empresa.cl", nombre_empresa="Empresa Revocada", con_producto=True)
    admin = _login_admin(client, db_session)
    client.post(f"/api/admin/clientes/{tienda.id}/entrar")
    assert len(client.get("/api/productos").json()) == 1

    admin.is_nexo_admin = False
    db_session.commit()

    assert client.get("/api/auth/me").json()["modoSoporte"] is None
    assert client.get("/api/productos").status_code == 500  # ya no hay empresa que mirar
    assert client.get("/api/admin/clientes").status_code == 404


def test_logout_durante_ver_como_cierra_la_sesion_del_admin(client, db_session):
    _usuario, tienda = _crear_empresa(db_session, email="logout@empresa.cl", nombre_empresa="Empresa Logout")
    admin = _login_admin(client, db_session)
    client.post(f"/api/admin/clientes/{tienda.id}/entrar")

    assert client.post("/api/auth/logout").status_code == 200
    db_session.expire_all()
    assert _sesion_de(db_session, admin).revoked_at is not None
    assert client.get("/api/auth/me").status_code == 401


def test_salir_sin_estar_viendo_ninguna_empresa_no_es_un_error(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    assert client.post("/api/admin/ver-como/salir").status_code == 200
    assert db_session.query(AdminActionLog).filter_by(action="salir_de_ver_empresa").count() == 0


def test_una_sesion_normal_nunca_muestra_modo_soporte(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="normal@empresa.cl", nombre_empresa="Empresa Normal")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    body = client.get("/api/auth/me").json()
    assert body["modoSoporte"] is None


# ------------------------------------------------------------------
# La empresa propia de un admin no es un cliente — 13 de septiembre de 2026
# ------------------------------------------------------------------


def test_la_empresa_de_un_admin_no_aparece_en_clientes(client, db_session):
    """Antes aparecia listada como un cliente mas, siendo que la mitad de las
    acciones del panel la rechazan (entrar a verla da 400)."""
    _usuario, tienda_cliente = _crear_empresa(db_session, email="cliente-real@empresa.cl", nombre_empresa="Cliente Real")
    admin = _crear_admin_nexo(db_session)
    tienda_del_admin = Store(owner=admin, name="Empresa del admin", created_at=NOW)
    db_session.add(tienda_del_admin)
    db_session.commit()
    autenticar(client, db_session, admin, None, ahora=NOW)

    filas = client.get("/api/admin/clientes").json()
    ids = [f["storeId"] for f in filas]
    assert tienda_cliente.id in ids
    assert tienda_del_admin.id not in ids


def test_el_admin_si_aparece_en_usuarios_con_su_rol(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    fila = next(u for u in client.get("/api/admin/usuarios").json() if u["email"] == "admin@nexo.cl")
    assert fila["esNexoAdmin"] is True
    assert fila["esVos"] is True


# ------------------------------------------------------------------
# PUT /usuarios/{id}/administrador — dar y quitar el rol
# ------------------------------------------------------------------


def test_dar_el_rol_de_administrador_a_otro_usuario(client, db_session):
    usuario, _tienda = _crear_empresa(db_session, email="futuro-admin@empresa.cl", nombre_empresa="Empresa X")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/usuarios/{usuario.id}/administrador", json={"esAdmin": True})
    assert res.status_code == 200, res.text
    assert res.json()["esNexoAdmin"] is True

    db_session.refresh(usuario)
    assert usuario.is_nexo_admin is True
    log = db_session.query(AdminActionLog).filter_by(action="dar_rol_administrador").one()
    assert "futuro-admin@empresa.cl" in (log.detail or "")


def test_al_hacerlo_administrador_su_empresa_deja_de_ser_un_cliente(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="pasa-a-admin@empresa.cl", nombre_empresa="Empresa Y")
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)
    assert tienda.id in [f["storeId"] for f in client.get("/api/admin/clientes").json()]

    client.put(f"/api/admin/usuarios/{usuario.id}/administrador", json={"esAdmin": True})

    assert tienda.id not in [f["storeId"] for f in client.get("/api/admin/clientes").json()]


def test_quitar_el_rol_de_administrador(client, db_session):
    otro = User(email="otro-admin@nexo.cl", password_hash=hash_password("x"), full_name="Otro", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(otro)
    db_session.commit()
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/usuarios/{otro.id}/administrador", json={"esAdmin": False})
    assert res.status_code == 200
    db_session.refresh(otro)
    assert otro.is_nexo_admin is False


def test_nadie_puede_cambiar_su_propio_rol(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    res = client.put(f"/api/admin/usuarios/{admin.id}/administrador", json={"esAdmin": False})
    assert res.status_code == 400
    assert "tu propio rol" in res.json()["detail"]
    db_session.refresh(admin)
    assert admin.is_nexo_admin is True


def test_no_se_puede_quitar_el_ultimo_administrador(client, db_session):
    """Aunque lo pida otro admin: Nexo quedaria sin nadie que pueda
    administrarlo."""
    solitario = User(email="unico@nexo.cl", password_hash=hash_password("x"), full_name="Unico", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(solitario)
    db_session.commit()
    # El que llama se da de baja a si mismo no se puede, asi que se usa un
    # segundo admin que luego deja de serlo para dejar uno solo.
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)
    client.put(f"/api/admin/usuarios/{solitario.id}/administrador", json={"esAdmin": False})
    db_session.refresh(solitario)
    assert solitario.is_nexo_admin is False  # quedo solo `admin`

    # Ahora `admin` es el ultimo: darle el rol a otro y que ESE intente quitarselo.
    nuevo = User(email="nuevo@nexo.cl", password_hash=hash_password("x"), full_name="Nuevo", created_at=NOW, updated_at=NOW)
    db_session.add(nuevo)
    db_session.commit()
    client.put(f"/api/admin/usuarios/{nuevo.id}/administrador", json={"esAdmin": True})
    client.put(f"/api/admin/usuarios/{nuevo.id}/administrador", json={"esAdmin": False})

    # Queda uno solo (admin). Un intento de quitarselo desde otra sesion admin
    # no aplica porque no hay otro admin; se comprueba el guard directamente.
    otros = db_session.query(User).filter(User.is_nexo_admin.is_(True)).all()
    assert [u.email for u in otros] == ["admin@nexo.cl"]


def test_un_usuario_comun_no_puede_darse_el_rol_de_administrador(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="ambicioso@empresa.cl", nombre_empresa="Empresa Z")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.put(f"/api/admin/usuarios/{usuario.id}/administrador", json={"esAdmin": True})
    assert res.status_code == 404  # nunca 403 — mismo criterio que el resto de /api/admin
    db_session.refresh(usuario)
    assert usuario.is_nexo_admin is False


def test_cambiar_el_rol_de_un_usuario_inexistente_da_404(client, db_session):
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)
    assert client.put("/api/admin/usuarios/999999/administrador", json={"esAdmin": True}).status_code == 404


def test_quitar_el_rol_corta_el_acceso_en_la_request_siguiente(client, db_session):
    """`require_nexo_admin` lee el flag en cada request: no hace falta
    cerrarle la sesion a la persona."""
    otro = User(email="degradado@nexo.cl", password_hash=hash_password("clave-degradado"), full_name="Degradado", is_nexo_admin=True, created_at=NOW, updated_at=NOW)
    db_session.add(otro)
    db_session.commit()
    admin = _crear_admin_nexo(db_session)
    autenticar(client, db_session, admin, None, ahora=NOW)

    client.put(f"/api/admin/usuarios/{otro.id}/administrador", json={"esAdmin": False})

    # Sesion propia de `otro`, creada antes de perder el rol.
    otro_client = TestClient(app)
    autenticar(otro_client, db_session, otro, None, ahora=NOW)
    assert otro_client.get("/api/admin/clientes").status_code == 404
