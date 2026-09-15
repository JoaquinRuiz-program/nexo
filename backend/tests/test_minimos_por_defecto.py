"""Mínimos por defecto de "¿Conviene?" en Mercado Libre (14 de septiembre de
2026, decisión del dueño): 15 % y $3.000 si la empresa nunca guardó su
configuración; lo guardado por el usuario siempre manda."""

from __future__ import annotations

from datetime import datetime

from app.db.models import ChannelCostSettings
from app.db.models.channel_costs import umbrales_minimos


def test_sin_configuracion_rigen_los_minimos_por_defecto():
    assert umbrales_minimos(None) == (15.0, 3000.0)


def test_lo_que_guardo_el_usuario_manda():
    config = ChannelCostSettings(channel="mercadolibre", min_margin_pct=22.5, min_profit_clp=10000, updated_at=datetime(2026, 9, 14))
    assert umbrales_minimos(config) == (22.5, 10000.0)


def test_un_minimo_vaciado_por_el_usuario_no_se_exige():
    config = ChannelCostSettings(channel="mercadolibre", min_margin_pct=None, min_profit_clp=None, updated_at=datetime(2026, 9, 14))
    assert umbrales_minimos(config) == (None, None)
