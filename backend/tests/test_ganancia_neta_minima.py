"""
Ganancia neta mínima por unidad (14 de septiembre de 2026, pedido del dueño):
un producto conviene si alcanza el margen mínimo (%) O la ganancia neta mínima
($). Caso real: Notebook HP a $499.990 con costo $350.000 y comisión 19% deja
$54.992 (11,0%) — bajo un margen mínimo de 22,5% quedaba "no conviene".
"""

from __future__ import annotations

from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.pricing import recomendar_precio
from app.domain.profitability import ChannelCosts

NOTEBOOK = {"tieneCosto": True, "mercadoLibreConfigurado": True, "margenMercadoLibreClp": 54992.0, "margenMercadoLibrePct": 11.0}


def _ml(**kwargs) -> SelectionCriteria:
    return SelectionCriteria(channel="mercadolibre", **kwargs)


def test_sin_ganancia_minima_el_notebook_sigue_sin_convenir():
    res = classify_product(NOTEBOOK, _ml(min_margin_pct=22.5))
    assert res["clasificacion"] == "margen_bajo"
    assert res["razon"] == "El margen estimado (11.0%) está por debajo del mínimo pedido (22.5%)."


def test_con_ganancia_minima_alcanzada_conviene_aunque_el_margen_sea_bajo():
    assert classify_product(NOTEBOOK, _ml(min_margin_pct=22.5, ganancia_minima_clp=30000))["clasificacion"] == "rentable"


def test_si_no_alcanza_ninguno_de_los_dos_el_motivo_nombra_ambos():
    res = classify_product(NOTEBOOK, _ml(min_margin_pct=22.5, ganancia_minima_clp=60000))
    assert res["clasificacion"] == "margen_bajo"
    assert res["razon"] == (
        "El margen estimado (11.0%) está por debajo del mínimo pedido (22.5%) "
        "y la ganancia ($54.992) no llega a la ganancia neta mínima ($60.000)."
    )


def test_solo_ganancia_minima_configurada_tambien_filtra():
    barato = {**NOTEBOOK, "margenMercadoLibreClp": 340.0, "margenMercadoLibrePct": 43.0}
    res = classify_product(barato, _ml(ganancia_minima_clp=1000))
    assert res["clasificacion"] == "margen_bajo"
    assert res["razon"] == "La ganancia estimada ($340) no llega a la ganancia neta mínima ($1.000)."


def test_un_producto_con_perdida_nunca_se_rescata_por_ganancia_minima():
    perdida = {**NOTEBOOK, "margenMercadoLibreClp": -5000.0, "margenMercadoLibrePct": -1.0}
    assert classify_product(perdida, _ml(min_margin_pct=22.5, ganancia_minima_clp=0))["clasificacion"] == "no_rentable"


def test_precio_recomendado_alcanza_el_piso_por_ganancia_minima():
    canal = ChannelCosts(commission_pct=19.0)
    sin = recomendar_precio(costo=350000, channel_costs=canal, margen_objetivo_pct=12.0, margen_minimo_pct=22.5)
    con = recomendar_precio(costo=350000, channel_costs=canal, margen_objetivo_pct=12.0, margen_minimo_pct=22.5, ganancia_minima_clp=30000)
    assert sin.alcanza_margen_minimo is False
    assert con.alcanza_margen_minimo is True  # ~$60.870 de ganancia >= $30.000
    assert con.margen_estimado_pct == sin.margen_estimado_pct  # el piso no cambia el precio


def test_ganancia_minima_negativa_es_un_dato_mal_configurado():
    res = recomendar_precio(costo=1000, channel_costs=ChannelCosts(commission_pct=10.0), margen_objetivo_pct=20.0, ganancia_minima_clp=-1)
    assert "ganancia neta mínima del canal (no puede ser negativa)" in res.faltantes
