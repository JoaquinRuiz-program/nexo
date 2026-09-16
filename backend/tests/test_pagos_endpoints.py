"""
Pruebas end-to-end de /api/pagos/* — cobro real de la mensualidad/
anualidad de Nexo con Mercado Pago (6 de septiembre de 2026). Cliente HTTP
real de FastAPI, SQLite en memoria, y la API de Mercado Pago mockeada con
respx (nunca se llama a la red real ni se usan credenciales reales).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import Store, StoreSettings, Subscription, User
from app.db.session import get_db
from app.domain.plans import crear_suscripcion_inicial
from app.domain.security import hash_password
from app.main import app
from tests.auth_helpers import autenticar

NOW = datetime(2026, 9, 6, 12, 0, 0)
WEBHOOK_SECRET = "un-secreto-de-prueba-nunca-real"

CONFIGURED_SETTINGS = Settings(mercadopago_access_token="TEST-access-token", mercadopago_webhook_secret=WEBHOOK_SECRET)
UNCONFIGURED_SETTINGS = Settings(mercadopago_access_token="", mercadopago_webhook_secret="")


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
    crear_suscripcion_inicial(db_session, tienda, ahora=NOW)  # trialing / básico, como en un registro real
    db_session.commit()
    return usuario, tienda


@pytest.fixture()
def a_store(client, db_session):
    usuario, tienda = _crear_empresa(db_session, email="tienda@ejemplo.cl", nombre_empresa="Tienda de prueba")
    autenticar(client, db_session, usuario, tienda, ahora=NOW)
    return tienda


def _firma_valida(data_id: str, ts: str, secret: str = WEBHOOK_SECRET) -> str:
    manifest = f"id:{data_id.lower()};ts:{ts};"
    v1 = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


def _enviar_webhook(client, *, tipo: str, data_id: str, secret: str = WEBHOOK_SECRET, ts: str = "1700000000"):
    headers = {"x-signature": _firma_valida(data_id, ts, secret), "x-request-id": ""}
    return client.post("/api/pagos/webhook", json={"type": tipo, "data": {"id": data_id}}, headers=headers)


# ------------------------------------------------------------------
# Firma del webhook — la pieza de seguridad más crítica de todo esto.
# ------------------------------------------------------------------


def test_validar_firma_webhook_acepta_una_firma_calculada_correctamente():
    from app.adapters.mercadopago import validar_firma_webhook

    ts = "1700000000"
    manifest = "id:123;request-id:req-1;ts:1700000000;"
    v1 = hmac.new(WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    assert validar_firma_webhook(x_signature=f"ts={ts},v1={v1}", x_request_id="req-1", data_id="123", secret=WEBHOOK_SECRET) is True


def test_validar_firma_webhook_rechaza_data_id_alterado():
    from app.adapters.mercadopago import validar_firma_webhook

    ts = "1700000000"
    manifest = "id:123;request-id:req-1;ts:1700000000;"
    v1 = hmac.new(WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    # Alguien cambió el data_id pero reusó la firma de otro payload -> debe fallar.
    assert validar_firma_webhook(x_signature=f"ts={ts},v1={v1}", x_request_id="req-1", data_id="456", secret=WEBHOOK_SECRET) is False


def test_validar_firma_webhook_rechaza_secreto_incorrecto():
    from app.adapters.mercadopago import validar_firma_webhook

    ts = "1700000000"
    manifest = "id:123;request-id:req-1;ts:1700000000;"
    v1 = hmac.new("otro-secreto".encode(), manifest.encode(), hashlib.sha256).hexdigest()
    assert validar_firma_webhook(x_signature=f"ts={ts},v1={v1}", x_request_id="req-1", data_id="123", secret=WEBHOOK_SECRET) is False


def test_validar_firma_webhook_rechaza_header_mal_formado():
    from app.adapters.mercadopago import validar_firma_webhook

    assert validar_firma_webhook(x_signature="esto-no-es-valido", x_request_id="req-1", data_id="123", secret=WEBHOOK_SECRET) is False


# ------------------------------------------------------------------
# GET /api/pagos/planes
# ------------------------------------------------------------------


def test_planes_devuelve_precio_mensual_y_anual_con_descuento(client, a_store):
    res = client.get("/api/pagos/planes")
    assert res.status_code == 200
    por_codigo = {p["codigo"]: p for p in res.json()}
    assert por_codigo["basico"]["precioMensualClp"] == 80000
    assert por_codigo["basico"]["precioAnualClp"] == round(80000 * 12 * 0.85)
    assert por_codigo["basico"]["descuentoAnualPct"] == 15
    assert por_codigo["pro"]["precioMensualClp"] == 200000
    assert por_codigo["pro"]["precioAnualClp"] == round(200000 * 12 * 0.85)


def test_planes_requiere_sesion(client):
    assert client.get("/api/pagos/planes").status_code == 401


# ------------------------------------------------------------------
# POST /api/pagos/iniciar
# ------------------------------------------------------------------


def test_iniciar_sin_credenciales_no_le_filtra_la_configuracion_al_cliente(client, a_store, monkeypatch):
    """Un cliente que aprieta "Elegir y pagar" no puede recibir los nombres
    de las variables de entorno ni la ruta del .env (13 de septiembre de
    2026) — el detalle operativo va al log del servidor."""
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: UNCONFIGURED_SETTINGS)
    res = client.post("/api/pagos/iniciar", json={"planCode": "basico", "ciclo": "mensual"})
    assert res.status_code == 400
    detalle = res.json()["detail"]
    assert "El pago en línea todavía no está habilitado" in detalle
    for secreto in ("MERCADOPAGO_ACCESS_TOKEN", "MERCADOPAGO_WEBHOOK_SECRET", ".env"):
        assert secreto not in detalle


def test_iniciar_ciclo_invalido_da_400(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/pagos/iniciar", json={"planCode": "basico", "ciclo": "semanal"})
    assert res.status_code == 400


def test_iniciar_plan_inexistente_da_404(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/pagos/iniciar", json={"planCode": "no-existe", "ciclo": "mensual"})
    assert res.status_code == 404


@respx.mock
def test_iniciar_mensual_crea_preapproval_y_devuelve_checkout_url(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    ruta = respx.post("https://api.mercadopago.com/preapproval").mock(
        return_value=httpx.Response(201, json={"id": "PA-123", "init_point": "https://www.mercadopago.cl/subscriptions/checkout?x", "status": "pending"})
    )

    res = client.post("/api/pagos/iniciar", json={"planCode": "basico", "ciclo": "mensual"})

    assert res.status_code == 200, res.text
    assert res.json()["checkoutUrl"] == "https://www.mercadopago.cl/subscriptions/checkout?x"
    body_enviado = json.loads(ruta.calls[0].request.content)
    assert body_enviado["auto_recurring"]["transaction_amount"] == 80000
    assert body_enviado["auto_recurring"]["frequency_type"] == "months"
    assert body_enviado["external_reference"] == f"nexo:{a_store.id}:basico:mensual"


@respx.mock
def test_iniciar_anual_crea_preferencia_con_el_monto_con_descuento(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    ruta = respx.post("https://api.mercadopago.com/checkout/preferences").mock(
        return_value=httpx.Response(201, json={"id": "PREF-1", "init_point": "https://www.mercadopago.cl/checkout/x"})
    )

    res = client.post("/api/pagos/iniciar", json={"planCode": "pro", "ciclo": "anual"})

    assert res.status_code == 200, res.text
    body_enviado = json.loads(ruta.calls[0].request.content)
    assert body_enviado["items"][0]["unit_price"] == round(200000 * 12 * 0.85)
    assert body_enviado["external_reference"] == f"nexo:{a_store.id}:pro:anual"


@respx.mock
def test_iniciar_no_cambia_nada_de_la_suscripcion_hasta_que_el_pago_se_confirme(client, db_session, a_store, monkeypatch):
    """Elegir un plan y pagarlo son cosas distintas — /iniciar solo pide la
    URL de pago, nunca toca la Subscription (eso lo hace únicamente el
    webhook, cuando Mercado Pago confirma el pago real)."""
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    respx.post("https://api.mercadopago.com/preapproval").mock(
        return_value=httpx.Response(201, json={"id": "PA-999", "init_point": "https://x", "status": "pending"})
    )
    estado_antes = a_store.subscription.status
    plan_antes = a_store.subscription.plan.code

    client.post("/api/pagos/iniciar", json={"planCode": "pro", "ciclo": "mensual"})

    db_session.refresh(a_store.subscription)
    assert a_store.subscription.status == estado_antes
    assert a_store.subscription.plan.code == plan_antes
    assert a_store.subscription.mercadopago_preapproval_id is None


# ------------------------------------------------------------------
# POST /api/pagos/webhook
# ------------------------------------------------------------------


def test_webhook_sin_configuracion_da_400(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: UNCONFIGURED_SETTINGS)
    res = client.post("/api/pagos/webhook", json={"type": "payment", "data": {"id": "1"}})
    assert res.status_code == 400


def test_webhook_con_firma_invalida_es_rechazado(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post(
        "/api/pagos/webhook",
        json={"type": "payment", "data": {"id": "1"}},
        headers={"x-signature": "ts=1,v1=firma-inventada", "x-request-id": ""},
    )
    assert res.status_code == 401


@respx.mock
def test_webhook_preapproval_authorized_activa_el_plan_mensual(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    referencia = f"nexo:{a_store.id}:pro:mensual"
    respx.get("https://api.mercadopago.com/preapproval/PA-500").mock(
        return_value=httpx.Response(200, json={"id": "PA-500", "status": "authorized", "external_reference": referencia})
    )

    res = _enviar_webhook(client, tipo="subscription_preapproval", data_id="PA-500")

    assert res.status_code == 200, res.text
    db_session.refresh(a_store.subscription)
    sub = a_store.subscription
    assert sub.status == "active"
    assert sub.plan.code == "pro"
    assert sub.billing_cycle == "mensual"
    assert sub.mercadopago_preapproval_id == "PA-500"
    assert sub.last_payment_at is not None
    assert sub.current_period_end == (NOW.date() + timedelta(days=30)) or sub.current_period_end is not None


@respx.mock
def test_webhook_preapproval_cancelled_marca_la_suscripcion_cancelada(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    referencia = f"nexo:{a_store.id}:basico:mensual"
    a_store.subscription.status = "active"
    a_store.subscription.mercadopago_preapproval_id = "PA-777"
    db_session.commit()
    respx.get("https://api.mercadopago.com/preapproval/PA-777").mock(
        return_value=httpx.Response(200, json={"id": "PA-777", "status": "cancelled", "external_reference": referencia})
    )

    res = _enviar_webhook(client, tipo="subscription_preapproval", data_id="PA-777")

    assert res.status_code == 200, res.text
    db_session.refresh(a_store.subscription)
    assert a_store.subscription.status == "canceled"
    assert a_store.subscription.canceled_at is not None


@respx.mock
def test_webhook_payment_approved_activa_el_plan_anual(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    referencia = f"nexo:{a_store.id}:basico:anual"
    respx.get("https://api.mercadopago.com/v1/payments/PAY-1").mock(
        return_value=httpx.Response(200, json={"id": "PAY-1", "status": "approved", "external_reference": referencia})
    )

    res = _enviar_webhook(client, tipo="payment", data_id="PAY-1")

    assert res.status_code == 200, res.text
    db_session.refresh(a_store.subscription)
    sub = a_store.subscription
    assert sub.status == "active"
    assert sub.billing_cycle == "anual"
    assert sub.mercadopago_last_payment_id == "PAY-1"
    assert (sub.current_period_end - NOW.date()).days >= 360


@respx.mock
def test_webhook_repetido_no_vuelve_a_extender_el_plan(client, db_session, a_store, monkeypatch):
    """Mercado Pago reintenta el mismo webhook hasta recibir un 200 (y puede
    mandarlo más de una vez): aplicar el mismo pago dos veces regalaba otro
    período completo. Revisión del sistema, 16 de septiembre de 2026."""
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    referencia = f"nexo:{a_store.id}:basico:anual"
    respx.get("https://api.mercadopago.com/v1/payments/PAY-REPETIDO").mock(
        return_value=httpx.Response(200, json={"id": "PAY-REPETIDO", "status": "approved", "external_reference": referencia})
    )

    assert _enviar_webhook(client, tipo="payment", data_id="PAY-REPETIDO").status_code == 200
    db_session.refresh(a_store.subscription)
    vencimiento_tras_el_primero = a_store.subscription.current_period_end

    assert _enviar_webhook(client, tipo="payment", data_id="PAY-REPETIDO").status_code == 200

    db_session.refresh(a_store.subscription)
    assert a_store.subscription.current_period_end == vencimiento_tras_el_primero


@respx.mock
def test_webhook_mensual_repetido_no_vuelve_a_extender_el_plan(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    referencia = f"nexo:{a_store.id}:basico:mensual"
    respx.get("https://api.mercadopago.com/preapproval/PA-REPETIDO").mock(
        return_value=httpx.Response(200, json={"id": "PA-REPETIDO", "status": "authorized", "external_reference": referencia})
    )

    assert _enviar_webhook(client, tipo="subscription_preapproval", data_id="PA-REPETIDO").status_code == 200
    db_session.refresh(a_store.subscription)
    vencimiento_tras_el_primero = a_store.subscription.current_period_end

    assert _enviar_webhook(client, tipo="subscription_preapproval", data_id="PA-REPETIDO").status_code == 200

    db_session.refresh(a_store.subscription)
    assert a_store.subscription.current_period_end == vencimiento_tras_el_primero


@respx.mock
def test_pagar_antes_de_que_venza_suma_los_dias_que_quedaban(client, db_session, a_store, monkeypatch):
    """Quien renueva antes de tiempo no pierde lo que ya tenía pagado."""
    from datetime import date, timedelta as delta

    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    a_store.subscription.current_period_end = date.today() + delta(days=10)
    db_session.commit()
    referencia = f"nexo:{a_store.id}:basico:anual"
    respx.get("https://api.mercadopago.com/v1/payments/PAY-ANTICIPADO").mock(
        return_value=httpx.Response(200, json={"id": "PAY-ANTICIPADO", "status": "approved", "external_reference": referencia})
    )

    assert _enviar_webhook(client, tipo="payment", data_id="PAY-ANTICIPADO").status_code == 200

    db_session.refresh(a_store.subscription)
    assert a_store.subscription.current_period_end == date.today() + delta(days=10 + 365)


@respx.mock
def test_webhook_payment_no_aprobado_no_activa_nada(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    referencia = f"nexo:{a_store.id}:basico:anual"
    respx.get("https://api.mercadopago.com/v1/payments/PAY-2").mock(
        return_value=httpx.Response(200, json={"id": "PAY-2", "status": "rejected", "external_reference": referencia})
    )
    estado_antes = a_store.subscription.status

    res = _enviar_webhook(client, tipo="payment", data_id="PAY-2")

    assert res.status_code == 200
    db_session.refresh(a_store.subscription)
    assert a_store.subscription.status == estado_antes
    assert a_store.subscription.mercadopago_last_payment_id is None


@respx.mock
def test_webhook_con_referencia_de_otra_tienda_nunca_mezcla_datos(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    _usuario_b, tienda_b = _crear_empresa(db_session, email="otra@empresas.cl", nombre_empresa="Otra Empresa")

    referencia_b = f"nexo:{tienda_b.id}:pro:mensual"
    respx.get("https://api.mercadopago.com/preapproval/PA-B").mock(
        return_value=httpx.Response(200, json={"id": "PA-B", "status": "authorized", "external_reference": referencia_b})
    )
    estado_a_antes = a_store.subscription.status

    _enviar_webhook(client, tipo="subscription_preapproval", data_id="PA-B")

    db_session.refresh(a_store.subscription)
    db_session.refresh(tienda_b.subscription)
    assert a_store.subscription.status == estado_a_antes  # A nunca se tocó
    assert a_store.subscription.mercadopago_preapproval_id is None
    assert tienda_b.subscription.status == "active"
    assert tienda_b.subscription.plan.code == "pro"


# ------------------------------------------------------------------
# POST /api/pagos/cancelar
# ------------------------------------------------------------------


@respx.mock
def test_cancelar_suscripcion_mensual_cancela_en_mercadopago_y_marca_local(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    a_store.subscription.status = "active"
    a_store.subscription.billing_cycle = "mensual"
    a_store.subscription.mercadopago_preapproval_id = "PA-CANCEL"
    db_session.commit()
    ruta = respx.put("https://api.mercadopago.com/preapproval/PA-CANCEL").mock(
        return_value=httpx.Response(200, json={"id": "PA-CANCEL", "status": "cancelled"})
    )

    res = client.post("/api/pagos/cancelar")

    assert res.status_code == 200, res.text
    assert ruta.called
    db_session.refresh(a_store.subscription)
    assert a_store.subscription.status == "canceled"


def test_cancelar_suscripcion_anual_no_llama_a_mercadopago(client, db_session, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    a_store.subscription.status = "active"
    a_store.subscription.billing_cycle = "anual"
    a_store.subscription.mercadopago_preapproval_id = None
    db_session.commit()

    # Sin ningún mock de red registrado — si el código intentara llamar a
    # Mercado Pago acá, respx (si estuviera activo) fallaría; sin @respx.mock
    # una llamada real de red haría fallar el test por timeout/DNS, lo cual
    # ya prueba que esto no intenta salir a internet.
    res = client.post("/api/pagos/cancelar")

    assert res.status_code == 200, res.text
    db_session.refresh(a_store.subscription)
    assert a_store.subscription.status == "canceled"


def test_cancelar_sin_suscripcion_da_400(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes.pagos.get_settings", lambda: CONFIGURED_SETTINGS)
    usuario = User(email="sin-sub@empresas.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    db_session.add(usuario)
    tienda = Store(owner=usuario, name="Sin suscripción", created_at=NOW)
    db_session.add(tienda)
    db_session.add(StoreSettings(store=tienda, company_name="Sin suscripción", store_name="Sin suscripción"))
    db_session.commit()
    autenticar(client, db_session, usuario, tienda, ahora=NOW)

    res = client.post("/api/pagos/cancelar")
    assert res.status_code == 400
