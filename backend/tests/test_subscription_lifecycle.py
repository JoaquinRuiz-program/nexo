# -*- coding: utf-8 -*-
"""
Ciclo de vida de la suscripción — vencimiento, gracia, recordatorios y pausa.
13 de septiembre de 2026 (P1-1, la decisión de producto que estuvo pendiente).

Foco: la POLÍTICA (funciones puras) y el ORQUESTADOR con efectos mockeados —
nunca se llama a Mercado Libre de verdad.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Plan, Store, StoreSettings, Subscription, User
from app.domain.security import hash_password
from app.domain.subscription_lifecycle import (
    DIAS_GRACIA,
    EN_GRACIA,
    VENCIDA,
    VIGENTE,
    DatosVigencia,
    debe_pausar,
    estado_efectivo,
    recordatorio_pendiente,
)
from app.services.lifecycle import ejecutar_ciclo_de_vida


# ------------------------------------------------------------------
# Política pura — estado_efectivo
# ------------------------------------------------------------------

VENC = date(2026, 9, 20)  # el plan vence este día


def _vig(status="trialing", venc=VENC, hito=None):
    return DatosVigencia(status=status, current_period_end=venc, ultimo_hito_recordatorio=hito)


def test_dentro_del_periodo_esta_vigente():
    assert estado_efectivo(_vig(), date(2026, 9, 20)) == VIGENTE
    assert estado_efectivo(_vig(), date(2026, 9, 10)) == VIGENTE


def test_vencido_pero_dentro_de_la_gracia():
    assert estado_efectivo(_vig(), date(2026, 9, 21)) == EN_GRACIA        # día 1 de gracia
    assert estado_efectivo(_vig(), date(2026, 9, 24)) == EN_GRACIA        # día 4


def test_pasada_la_gracia_esta_vencida():
    # gracia = 5 días -> pausa el 25. El 25 ya es VENCIDA.
    assert estado_efectivo(_vig(), VENC + timedelta(days=DIAS_GRACIA)) == VENCIDA
    assert estado_efectivo(_vig(), date(2026, 9, 30)) == VENCIDA


def test_una_suscripcion_activa_nunca_se_considera_vencida():
    """Una paga al día se mantiene por el webhook de Mercado Pago; su fecha
    puede quedar vieja y NO por eso hay que pausarla."""
    vieja = _vig(status="active", venc=date(2020, 1, 1))
    assert estado_efectivo(vieja, date(2026, 9, 30)) == VIGENTE


# ------------------------------------------------------------------
# Recordatorios — 5, 3, 1 días antes de la pausa
# ------------------------------------------------------------------


def test_recordatorio_en_cada_hito():
    # pausa el 25; 5 días antes = 20, 3 antes = 22, 1 antes = 24
    assert recordatorio_pendiente(_vig(hito=None), date(2026, 9, 20)) == 5
    assert recordatorio_pendiente(_vig(hito=5), date(2026, 9, 22)) == 3
    assert recordatorio_pendiente(_vig(hito=3), date(2026, 9, 24)) == 1


def test_no_repite_un_hito_ya_enviado():
    assert recordatorio_pendiente(_vig(hito=5), date(2026, 9, 20)) is None
    assert recordatorio_pendiente(_vig(hito=3), date(2026, 9, 22)) is None


def test_dia_salteado_manda_el_hito_mas_urgente_no_uno_viejo():
    """Si el proceso no corrió y se pasó del hito de 5, manda el de 3 (el más
    urgente ya alcanzado), nunca el viejo de 5."""
    assert recordatorio_pendiente(_vig(hito=None), date(2026, 9, 23)) == 3


def test_fuera_de_la_gracia_no_hay_recordatorio():
    assert recordatorio_pendiente(_vig(), date(2026, 9, 10)) is None   # vigente
    assert recordatorio_pendiente(_vig(), date(2026, 9, 25)) is None   # ya vencida (se pausa)
    assert recordatorio_pendiente(_vig(), date(2026, 9, 19)) is None   # antes del vencimiento


def test_debe_pausar_solo_pasada_la_gracia():
    assert debe_pausar(_vig(), date(2026, 9, 24)) is False
    assert debe_pausar(_vig(), date(2026, 9, 25)) is True


# ------------------------------------------------------------------
# Orquestador — con efectos mockeados
# ------------------------------------------------------------------


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = Session(bind=engine, future=True)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _empresa_con_sub(db, *, email, status, venc, hito=None):
    ahora = datetime(2026, 9, 1)
    u = User(email=email, password_hash=hash_password("x"), full_name="Dueño", created_at=ahora, updated_at=ahora)
    db.add(u); db.flush()
    t = Store(owner=u, name=f"Empresa {email}", created_at=ahora)
    db.add(t); db.flush()
    db.add(StoreSettings(store=t, company_name="X", store_name="X"))
    plan = db.query(Plan).filter_by(code="basico").first()
    if plan is None:
        plan = Plan(code="basico", name="Nexo Básico", product_limit=200, publication_limit=150, price_demo_label="$80.000", monthly_price_clp=80000, is_active=True)
        db.add(plan); db.flush()
    db.add(Subscription(store=t, plan=plan, status=status, started_at=ahora, current_period_end=venc, ultimo_hito_recordatorio=hito))
    db.commit()
    return t


def _correr(db, hoy, *, pausadas_por_tienda=0):
    enviados = []

    async def pausar(store):
        return pausadas_por_tienda

    def enviar(para, asunto, cuerpo):
        enviados.append((para, asunto))

    res = asyncio.run(ejecutar_ciclo_de_vida(db, hoy, pausar_publicaciones=pausar, enviar_email=enviar))
    return res, enviados


def test_orquestador_manda_recordatorio_a_los_en_gracia(db_session):
    _empresa_con_sub(db_session, email="a@x.cl", status="trialing", venc=VENC)   # 5 días antes de pausa el 20
    res, enviados = _correr(db_session, date(2026, 9, 20))
    assert res["recordatorios"] == 1
    assert enviados[0][0] == "a@x.cl"
    sub = db_session.query(Subscription).one()
    assert sub.ultimo_hito_recordatorio == 5   # quedó registrado, no se repite


def test_orquestador_no_toca_a_las_vigentes_ni_a_las_activas(db_session):
    _empresa_con_sub(db_session, email="vig@x.cl", status="trialing", venc=date(2026, 10, 30))  # lejos
    _empresa_con_sub(db_session, email="paga@x.cl", status="active", venc=date(2020, 1, 1))     # vieja pero paga
    res, enviados = _correr(db_session, date(2026, 9, 20))
    assert res == {"recordatorios": 0, "empresas_pausadas": 0, "publicaciones_pausadas": 0}
    assert enviados == []


def test_orquestador_pausa_pasada_la_gracia_y_es_idempotente(db_session):
    _empresa_con_sub(db_session, email="venc@x.cl", status="trialing", venc=VENC)  # pausa el 25
    res, _ = _correr(db_session, date(2026, 9, 25), pausadas_por_tienda=3)
    assert res["empresas_pausadas"] == 1
    assert res["publicaciones_pausadas"] == 3
    sub = db_session.query(Subscription).one()
    assert sub.publicaciones_pausadas_por_vencimiento is True

    # Segunda corrida el mismo día: NO vuelve a pausar.
    res2, _ = _correr(db_session, date(2026, 9, 25), pausadas_por_tienda=3)
    assert res2["empresas_pausadas"] == 0


def test_si_falla_la_pausa_no_se_marca_y_se_reintenta(db_session):
    _empresa_con_sub(db_session, email="falla@x.cl", status="trialing", venc=VENC)

    async def pausar_que_falla(store):
        raise RuntimeError("Mercado Libre caído")

    def enviar(para, asunto, cuerpo):
        pass

    res = asyncio.run(ejecutar_ciclo_de_vida(db_session, date(2026, 9, 25), pausar_publicaciones=pausar_que_falla, enviar_email=enviar))
    assert res["empresas_pausadas"] == 0
    sub = db_session.query(Subscription).one()
    assert sub.publicaciones_pausadas_por_vencimiento is False  # no marcada -> reintenta mañana
