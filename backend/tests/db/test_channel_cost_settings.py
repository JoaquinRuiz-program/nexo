"""
Pruebas de ChannelCostSettings: un canal por tienda, costos siempre
opcionales (no configurar un canal es un estado válido, no un error).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import ChannelCostSettings


def test_se_puede_configurar_un_canal(db_session, a_store, now):
    costos = ChannelCostSettings(
        store=a_store,
        channel="mercadolibre",
        commission_pct=12.5,
        shipping_cost=2500,
        other_fixed_cost=0,
        updated_at=now,
    )
    db_session.add(costos)
    db_session.commit()

    assert costos.id is not None
    assert costos.commission_pct == 12.5


def test_un_canal_sin_costos_configurados_es_valido(db_session, a_store, now):
    """Ningún costo es obligatorio — un canal puede existir "reservado"
    sin ningún valor todavía, y eso no es un error de datos."""
    costos = ChannelCostSettings(store=a_store, channel="mercadolibre", updated_at=now)
    db_session.add(costos)
    db_session.commit()

    assert costos.commission_pct is None
    assert costos.shipping_cost is None


def test_no_se_puede_configurar_el_mismo_canal_dos_veces_en_la_misma_tienda(db_session, a_store, now):
    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=12, updated_at=now))
    db_session.commit()

    db_session.add(ChannelCostSettings(store=a_store, channel="mercadolibre", commission_pct=15, updated_at=now))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
