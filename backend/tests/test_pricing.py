"""Pruebas de app/domain/pricing.py — función pura, sin red ni DB
(30 de agosto de 2026, FASE 5). Los números del ejemplo del dueño
(costo $8.000, comisión, margen 25%) se usan como caso de referencia, pero
el resultado se verifica con la fórmula real, nunca "a ojo"."""

from __future__ import annotations

from app.domain.competencia import AnalisisCompetencia
from app.domain.pricing import ESTADO_DATOS_INSUFICIENTES, ESTADO_RECOMENDACION, precio_vitrina, recomendar_precio
from app.domain.profitability import ChannelCosts


def test_precio_recomendado_es_deterministico_y_alcanza_el_margen_objetivo():
    # costo 8000, comisión 15%, envío 500, otros 0, margen objetivo 25%.
    channel_costs = ChannelCosts(commission_pct=15.0, shipping_cost=500.0, other_fixed_cost=0.0)
    resultado = recomendar_precio(costo=8000.0, channel_costs=channel_costs, margen_objetivo_pct=25.0)

    assert resultado.estado == ESTADO_RECOMENDACION
    # costos_fijos = 8000+500 = 8500; precio exacto = 8500 / (1 - 0.25 - 0.15) = 14.166,67
    # -> redondeado hacia arriba al precio terminado en 990: 14.990.
    assert resultado.precio_recomendado == 14990.0
    assert resultado.alcanza_margen_objetivo is True
    # El margen neto real se calcula con el precio redondeado: nunca bajo el 25%.
    assert resultado.margen_estimado_pct >= 25.0
    assert resultado.ganancia_estimada == resultado.margen_estimado_clp


def test_precio_vitrina_redondea_hacia_arriba_al_990():
    assert precio_vitrina(84133.93) == 84990.0
    assert precio_vitrina(84990.0) == 84990.0
    assert precio_vitrina(85000.0) == 85990.0
    assert precio_vitrina(500.0) == 990.0


def test_precio_minimo_rentable_es_el_punto_de_equilibrio():
    channel_costs = ChannelCosts(commission_pct=15.0, shipping_cost=500.0, other_fixed_cost=0.0)
    resultado = recomendar_precio(costo=8000.0, channel_costs=channel_costs, margen_objetivo_pct=25.0)

    # Al precio mínimo rentable, el margen neto tiene que dar ~0%.
    margen_en_el_minimo = resultado.precio_minimo_rentable - 8000 - (resultado.precio_minimo_rentable * 0.15) - 500
    assert abs(margen_en_el_minimo) < 1


def test_sin_costo_devuelve_datos_insuficientes_nunca_inventa():
    resultado = recomendar_precio(costo=None, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0)
    assert resultado.estado == ESTADO_DATOS_INSUFICIENTES
    assert "costo de compra" in resultado.faltantes
    assert resultado.precio_recomendado is None


def test_sin_canal_configurado_devuelve_datos_insuficientes():
    resultado = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(), margen_objetivo_pct=25.0)
    assert resultado.estado == ESTADO_DATOS_INSUFICIENTES
    assert "comisión/costos del canal" in resultado.faltantes


def test_sin_margen_objetivo_configurado_devuelve_datos_insuficientes():
    resultado = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=None)
    assert resultado.estado == ESTADO_DATOS_INSUFICIENTES
    assert "margen objetivo del canal" in resultado.faltantes


def test_sin_competencia_el_sistema_sigue_funcionando():
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0, analisis_competencia=None
    )
    assert resultado.estado == ESTADO_RECOMENDACION
    assert resultado.precio_recomendado is not None
    assert resultado.posicion_frente_a_competencia is None
    assert resultado.precio_mercado_ganador is None


def test_competencia_sin_ganador_no_calcula_posicion():
    sin_ganador = AnalisisCompetencia(hay_competencia=False)
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0, analisis_competencia=sin_ganador
    )
    assert resultado.posicion_frente_a_competencia is None


def test_posicion_frente_a_competencia_por_debajo_del_rango():
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=30000, rango_precio_minimo=25000, rango_precio_maximo=35000)
    # margen objetivo bajo -> precio recomendado por debajo del rango de competencia.
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=10.0, analisis_competencia=competencia
    )
    assert resultado.precio_recomendado < 25000
    assert resultado.posicion_frente_a_competencia == "por_debajo"


def test_posicion_frente_a_competencia_en_rango():
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=13990, rango_precio_minimo=13000, rango_precio_maximo=16000)
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0, shipping_cost=500.0), margen_objetivo_pct=25.0,
        analisis_competencia=competencia,
    )
    assert 13000 <= resultado.precio_recomendado <= 16000
    assert resultado.posicion_frente_a_competencia == "en_rango"


def test_posicion_frente_a_competencia_por_encima_del_rango():
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=9000, rango_precio_minimo=8000, rango_precio_maximo=10000)
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=40.0, analisis_competencia=competencia
    )
    assert resultado.precio_recomendado > 10000
    assert resultado.posicion_frente_a_competencia == "por_encima"


def test_margen_minimo_alcanzado():
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0, margen_minimo_pct=10.0
    )
    assert resultado.alcanza_margen_minimo is True


def test_margen_minimo_no_alcanzado():
    # margen objetivo bajo, mínimo exigido más alto que lo que el objetivo logra.
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=5.0, margen_minimo_pct=20.0
    )
    assert resultado.alcanza_margen_minimo is False


def test_sin_margen_minimo_configurado_no_calcula_nada():
    resultado = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0)
    assert resultado.alcanza_margen_minimo is None


def test_comision_100_por_ciento_o_mas_es_datos_insuficientes_nunca_infinito():
    resultado = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(commission_pct=100.0), margen_objetivo_pct=25.0)
    assert resultado.estado == ESTADO_DATOS_INSUFICIENTES


def test_margen_objetivo_mas_comision_imposible_recomienda_el_minimo_rentable():
    # comisión 80% + margen objetivo 30% = 110%, matemáticamente imposible.
    resultado = recomendar_precio(costo=1000.0, channel_costs=ChannelCosts(commission_pct=80.0), margen_objetivo_pct=30.0)
    assert resultado.estado == ESTADO_RECOMENDACION
    assert resultado.alcanza_margen_objetivo is False
    assert resultado.precio_recomendado == resultado.precio_minimo_rentable


def test_margen_objetivo_negativo_es_datos_insuficientes_nunca_calcula_con_perdida():
    # Hallazgo de QA (FASE 6): un margen objetivo negativo no está
    # validado por ningún caller — sin este guard, produciría un precio
    # recomendado con pérdida real sin que nadie lo marque como tal.
    resultado = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=-10.0)
    assert resultado.estado == ESTADO_DATOS_INSUFICIENTES
    assert any("no puede ser negativo" in f for f in resultado.faltantes)


def test_margen_minimo_negativo_es_datos_insuficientes():
    resultado = recomendar_precio(
        costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0, margen_minimo_pct=-5.0
    )
    assert resultado.estado == ESTADO_DATOS_INSUFICIENTES
    assert any("margen mínimo" in f and "no puede ser negativo" in f for f in resultado.faltantes)


def test_sin_costo_o_costo_cero_no_recomienda_un_precio_por_margen_objetivo():
    # 15 de septiembre de 2026: el costo $0 es un dato real para la ganancia
    # (rentabilidad.py::_fila), pero un precio "costo + margen objetivo" sobre
    # $0 no tiene sentido (daba $8.990 para algo que se vende a $80.000): sin
    # costo se mantiene el precio de venta del dueño.
    for costo in (None, 0.0):
        resultado = recomendar_precio(costo=costo, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0)
        assert resultado.estado == ESTADO_DATOS_INSUFICIENTES
        assert resultado.precio_recomendado is None
        assert "costo de compra" in resultado.faltantes


def test_clasificacion_es_un_campo_historico_el_motor_real_esta_en_decision_py():
    """FASE 6: el motor "¿conviene vender?" quedó en domain/decision.py
    (DecisionNegocio), no acá — este campo queda None siempre, a propósito."""
    resultado = recomendar_precio(costo=8000.0, channel_costs=ChannelCosts(commission_pct=15.0), margen_objetivo_pct=25.0)
    assert resultado.clasificacion is None
