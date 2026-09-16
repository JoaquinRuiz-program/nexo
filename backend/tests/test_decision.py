"""Pruebas de app/domain/decision.py — "¿Conviene?" (regla definitiva del
dueño, 14 de septiembre de 2026): decide la clasificación al precio REAL
(classify_product, la misma de Oportunidades); el margen objetivo solo arma
el precio recomendado y, si es imposible, un aviso que nunca cambia la
decisión. Usa pricing.py y catalog_selection.py reales."""

from __future__ import annotations

from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.competencia import AnalisisCompetencia
from app.domain.decision import AVISO_MARGEN_OBJETIVO_IMPOSIBLE, CONVIENE, NO_CONVIENE, REVISAR, _clp, evaluar_decision
from app.domain.pricing import recomendar_precio
from app.domain.profitability import ChannelCosts

CHANNEL = ChannelCosts(commission_pct=15.0, shipping_cost=500.0)


def _fila(*, precio=20000.0, ganancia=9000.0, margen_pct=45.0, tiene_costo=True, envio_resuelto=True):
    return {
        "precio": precio, "tieneCosto": tiene_costo, "mercadoLibreConfigurado": True,
        "margenMercadoLibreClp": ganancia, "margenMercadoLibrePct": margen_pct,
        # 16 de septiembre de 2026 — sin el envío de Mercado Libre no hay
        # decisión posible (ver test de más abajo y catalog_selection.py).
        "envioMlResuelto": envio_resuelto,
    }


def _decidir(fila, criterios, recomendacion, competencia=None):
    return evaluar_decision(
        classify_product(fila, criterios), recomendacion, competencia,
        precio_actual=fila.get("precio"), ganancia_actual=fila.get("margenMercadoLibreClp"),
        margen_actual_pct=fila.get("margenMercadoLibrePct"),
        hay_piso_configurado=criterios.min_margin_pct is not None or criterios.ganancia_minima_clp is not None,
    )


def _ml(**kw):
    return SelectionCriteria(channel="mercadolibre", require_marketplace_stock=False, **kw)


RECO_OK = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0)


def test_conviene_si_alcanza_el_margen_minimo_con_el_precio_real():
    resultado = _decidir(_fila(), _ml(min_margin_pct=20.0), RECO_OK)
    assert resultado.decision == CONVIENE
    assert resultado.precio_actual == 20000.0 and resultado.ganancia_actual == 9000.0
    assert "$20.000" in resultado.razon and "$9.000" in resultado.razon
    assert resultado.aviso_margen_objetivo is None


def test_sin_el_envio_de_mercado_libre_no_se_decide_nunca_conviene():
    """Regla estricta del dueño (16 de septiembre de 2026): con el envío sin
    resolver la respuesta es "revisar" (Faltan datos), aunque los números
    calculados sin envío dieran de sobra."""
    resultado = _decidir(_fila(envio_resuelto=False), _ml(min_margin_pct=20.0), RECO_OK)
    assert resultado.decision == REVISAR
    assert "costo de envío de Mercado Libre" in resultado.razon


def test_no_conviene_si_no_alcanza_margen_minimo_ni_ganancia_minima():
    resultado = _decidir(_fila(ganancia=2000.0, margen_pct=10.0), _ml(min_margin_pct=20.0, ganancia_minima_clp=5000.0), RECO_OK)
    assert resultado.decision == NO_CONVIENE


def test_conviene_por_ganancia_neta_minima_aunque_el_margen_pct_sea_bajo():
    resultado = _decidir(_fila(ganancia=6000.0, margen_pct=10.0), _ml(min_margin_pct=20.0, ganancia_minima_clp=5000.0), RECO_OK)
    assert resultado.decision == CONVIENE


def test_perdida_nunca_conviene():
    resultado = _decidir(_fila(ganancia=-500.0, margen_pct=-2.5), _ml(min_margin_pct=20.0, ganancia_minima_clp=0.0), RECO_OK)
    assert resultado.decision == NO_CONVIENE


def test_sin_piso_configurado_conviene_si_no_hay_perdida():
    resultado = _decidir(_fila(), _ml(), RECO_OK)
    assert resultado.decision == CONVIENE
    assert "no deja pérdida" in resultado.razon


def test_sin_datos_para_calcular_la_ganancia_es_revisar():
    resultado = _decidir(_fila(tiene_costo=False, ganancia=None, margen_pct=None), _ml(min_margin_pct=20.0), RECO_OK)
    assert resultado.decision == REVISAR


def test_margen_objetivo_imposible_solo_avisa_no_cambia_la_decision():
    imposible = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(commission_pct=80.0), margen_objetivo_pct=30.0)
    assert imposible.alcanza_margen_objetivo is False
    resultado = _decidir(_fila(), _ml(min_margin_pct=20.0), imposible)
    assert resultado.decision == CONVIENE
    assert resultado.aviso_margen_objetivo == AVISO_MARGEN_OBJETIVO_IMPOSIBLE


def test_el_precio_recomendado_no_decide_objetivo_menor_al_minimo():
    # Antes el mínimo se evaluaba al precio recomendado: con el precio real
    # bajo el mínimo, la decisión tiene que ser "no conviene".
    reco = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=60.0, margen_minimo_pct=50.0)
    resultado = _decidir(_fila(ganancia=9000.0, margen_pct=45.0), _ml(min_margin_pct=50.0), reco)
    assert resultado.decision == NO_CONVIENE


def test_falta_margen_objetivo_no_impide_decidir():
    sin_objetivo = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=None)
    resultado = _decidir(_fila(), _ml(min_margin_pct=20.0), sin_objetivo)
    assert resultado.decision == CONVIENE
    assert resultado.precio_recomendado is None
    assert "margen objetivo del canal" in resultado.faltantes


def test_la_competencia_no_cambia_la_decision():
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=9000, rango_precio_minimo=8000, rango_precio_maximo=10000)
    resultado = _decidir(_fila(), _ml(min_margin_pct=20.0), RECO_OK, competencia)
    assert resultado.decision == CONVIENE
    assert resultado.hay_competencia is True


def test_razon_siempre_es_texto_no_vacio():
    for fila, criterios in [
        (_fila(), _ml(min_margin_pct=20.0)),
        (_fila(ganancia=-1.0, margen_pct=-0.1), _ml()),
        (_fila(tiene_costo=False, ganancia=None, margen_pct=None), _ml()),
    ]:
        resultado = _decidir(fila, criterios, RECO_OK)
        assert isinstance(resultado.razon, str) and len(resultado.razon) > 0


def test_decision_es_pura_no_muta_los_objetos_de_entrada():
    fila = _fila()
    copia = dict(fila)
    _decidir(fila, _ml(min_margin_pct=20.0), RECO_OK)
    assert fila == copia


# ------------------------------------------------------------------
# Formato de moneda — 13 de septiembre de 2026 ("$25.806", nunca "$25,806").
# ------------------------------------------------------------------


def test_los_montos_van_en_formato_chileno():
    assert _clp(25806) == "$25.806"
    assert _clp(1234567) == "$1.234.567"
    assert _clp(990) == "$990"
    assert _clp(25806.4) == "$25.806"  # sin decimales


def test_la_razon_que_ve_el_cliente_usa_punto_de_miles():
    razon = _decidir(_fila(precio=125000.0, ganancia=40000.0, margen_pct=32.0), _ml(min_margin_pct=20.0), RECO_OK).razon
    assert "$125.000" in razon and "," not in razon.split("$")[1][:10]
