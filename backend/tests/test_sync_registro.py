"""
Registro real de sincronizaciones con Mercado Libre en SyncJob/SyncLog
(services/sync_registro.py, 14 de septiembre de 2026).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Store, SyncJob, User
from app.domain.security import hash_password
from app.services.sync_registro import DIRECCION_ML_STOCK, registrar_fallo, registrar_sincronizacion

NOW = datetime(2026, 9, 14, 12, 0, 0)


@pytest.fixture()
def db():
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
def tienda(db):
    usuario = User(email="sync@test.cl", password_hash=hash_password("x"), full_name="Dueño", created_at=NOW, updated_at=NOW)
    tienda = Store(owner=usuario, name="Tienda", created_at=NOW)
    db.add_all([usuario, tienda])
    db.commit()
    return tienda


@pytest.mark.parametrize(
    "afectados, errores, estado",
    [(3, [], "success"), (2, [(None, "falló una")], "partial_error"), (0, [(None, "falló todo")], "error")],
)
def test_el_estado_sale_de_lo_que_realmente_paso(db, tienda, afectados, errores, estado):
    job = registrar_sincronizacion(db, tienda.id, direccion=DIRECCION_ML_STOCK, productos_afectados=afectados, inicio=NOW, errores=errores)
    db.commit()
    assert job.status == estado
    assert job.products_affected == afectados
    assert job.finished_at is not None
    assert [log.message for log in job.logs if log.level == "error"] == [m for _, m in errores]


def test_las_advertencias_no_cuentan_como_error(db, tienda):
    job = registrar_sincronizacion(
        db, tienda.id, direccion="ml_importar_ventas", productos_afectados=1, inicio=NOW, advertencias=[(None, "SKU fuera del catálogo")]
    )
    db.commit()
    assert job.status == "success"
    assert [(log.level, log.message) for log in job.logs] == [("warning", "SKU fuera del catálogo")]


def test_registrar_fallo_deja_una_sincronizacion_con_error_y_hace_commit(db, tienda):
    registrar_fallo(db, tienda.id, DIRECCION_ML_STOCK, "No se pudo actualizar el stock en Mercado Libre (HTTPException).")
    db.rollback()  # lo registrado ya quedó guardado
    job = db.query(SyncJob).one()
    assert (job.status, job.products_affected, job.direction) == ("error", 0, "ml_stock")
    assert job.logs[0].message.startswith("No se pudo actualizar el stock")
