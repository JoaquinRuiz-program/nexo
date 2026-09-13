"""Pruebas de app/domain/decision.py — motor "¿conviene vender?", función
pura (30 de agosto de 2026, FASE 6). Usa domain/pricing.py real
(recomendar_precio) para construir los RecomendacionPrecio de cada caso, en
vez de armarlos a mano, para no perder de vista cómo se comporta pricing.py
realmente (p.ej. que margen_estimado_pct siempre iguala margen_objetivo_pct
cuando alcanza_margen_objetivo=True)."""

from __future__ import annotations

from app.domain.competencia import AnalisisCompetencia
from app.domain.decision import CONVIENE, NO_CONVIENE, REVISAR, _clp, evaluar_decision
from app.domain.pricing import recomendar_precio
from app.domain.profitability import ChannelCosts

CHANNEL = ChannelCosts(commission_pct=15.0, shipping_cost=500.0)


def test_conviene_rentable_y_competitivo_en_rango():
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=13990, rango_precio_minimo=8000, rango_precio_maximo=16000)
    recomendacion = recomendar_precio(
        costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=10.0, analisis_competencia=competencia
    )
    resultado = evaluar_decision(recomendacion, competencia)
    assert resultado.decision == CONVIENE
    assert resultado.hay_competencia is True
    assert "objetivo" in resultado.razon


def test_conviene_precio_por_debajo_de_competencia_no_se_penaliza_ser_mas_barato():
    # Ser más barato que el rango de competencia y seguir siendo rentable es
    # una señal buena, no debe convertirse en "revisar" ni "no conviene".
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=30000, rango_precio_minimo=25000, rango_precio_maximo=35000)
    recomendacion = recomendar_precio(
        costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=10.0, margen_minimo_pct=5.0, analisis_competencia=competencia
    )
    assert recomendacion.posicion_frente_a_competencia == "por_debajo"
    resultado = evaluar_decision(recomendacion, competencia)
    assert resultado.decision == CONVIENE


def test_conviene_sin_competencia_pero_margen_minimo_configurado_y_ok():
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=10.0)
    resultado = evaluar_decision(recomendacion, analisis_competencia=None)
    assert resultado.decision == CONVIENE
    assert "competencia" in resultado.razon.lower()


def test_no_conviene_margen_objetivo_matematicamente_imposible():
    recomendacion = recomendar_precio(costo=1000.0, channel_costs=ChannelCosts(commission_pct=80.0), margen_objetivo_pct=30.0)
    assert recomendacion.alcanza_margen_objetivo is False
    resultado = evaluar_decision(recomendacion)
    assert resultado.decision == NO_CONVIENE


def test_no_conviene_no_alcanza_margen_minimo():
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=5.0, margen_minimo_pct=20.0)
    assert recomendacion.alcanza_margen_objetivo is True
    assert recomendacion.alcanza_margen_minimo is False
    resultado = evaluar_decision(recomendacion)
    assert resultado.decision == NO_CONVIENE


def test_no_conviene_tiene_prioridad_sobre_objetivo_alcanzado_config_contradictoria():
    # margen mínimo configurado por encima del objetivo: alcanza_margen_objetivo
    # puede dar True y alcanza_margen_minimo False al mismo tiempo — la
    # regla 3 (mínimo no alcanzado) tiene prioridad absoluta.
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=50.0)
    assert recomendacion.alcanza_margen_objetivo is True
    assert recomendacion.alcanza_margen_minimo is False
    resultado = evaluar_decision(recomendacion)
    assert resultado.decision == NO_CONVIENE


def test_revisar_sin_margen_minimo_configurado_y_sin_dato_de_competencia():
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0)
    assert recomendacion.alcanza_margen_minimo is None
    resultado = evaluar_decision(recomendacion, analisis_competencia=None)
    assert resultado.decision == REVISAR


def test_revisar_sin_margen_minimo_y_competencia_consultada_sin_ganador_cuenta_como_sin_dato():
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0)
    sin_ganador = AnalisisCompetencia(hay_competencia=False)
    resultado = evaluar_decision(recomendacion, sin_ganador)
    assert resultado.decision == REVISAR


def test_revisar_precio_recomendado_por_encima_del_rango_de_competencia():
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=9000, rango_precio_minimo=8000, rango_precio_maximo=10000)
    recomendacion = recomendar_precio(
        costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=40.0, margen_minimo_pct=10.0, analisis_competencia=competencia
    )
    assert recomendacion.posicion_frente_a_competencia == "por_encima"
    resultado = evaluar_decision(recomendacion, competencia)
    assert resultado.decision == REVISAR


def test_revisar_datos_insuficientes_de_pricing_nunca_inventa_una_decision():
    recomendacion = recomendar_precio(costo=None, channel_costs=CHANNEL, margen_objetivo_pct=25.0)
    resultado = evaluar_decision(recomendacion)
    assert resultado.decision == REVISAR
    assert "costo de compra" in resultado.faltantes
    assert "costo de compra" in resultado.razon


def test_revisar_margen_objetivo_negativo_propaga_datos_insuficientes():
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=-10.0)
    resultado = evaluar_decision(recomendacion)
    assert resultado.decision == REVISAR
    assert resultado.precio_recomendado is None


def test_costo_cero_no_rompe_la_decision():
    recomendacion = recomendar_precio(costo=0.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=10.0)
    resultado = evaluar_decision(recomendacion)
    assert resultado.decision == CONVIENE


def test_razon_siempre_es_texto_no_vacio():
    for recomendacion, competencia in [
        (recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=10.0), None),
        (recomendar_precio(costo=None, channel_costs=CHANNEL, margen_objetivo_pct=25.0), None),
        (recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=5.0, margen_minimo_pct=20.0), None),
    ]:
        resultado = evaluar_decision(recomendacion, competencia)
        assert isinstance(resultado.razon, str) and len(resultado.razon) > 0


def test_decision_es_pura_no_muta_los_objetos_de_entrada():
    recomendacion = recomendar_precio(costo=8000.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=10.0)
    competencia = AnalisisCompetencia(hay_competencia=True, precio_ganador=13990, rango_precio_minimo=8000, rango_precio_maximo=16000)
    snapshot_recomendacion = recomendacion
    snapshot_competencia = competencia
    evaluar_decision(recomendacion, competencia)
    assert recomendacion == snapshot_recomendacion
    assert competencia == snapshot_competencia


# ------------------------------------------------------------------
# Formato de moneda — 13 de septiembre de 2026. Estos textos los lee el
# cliente en la pantalla de producto; antes usaban "{:,.0f}", que produce
# el formato ingles ("$25,806") y quedaba inconsistente con el resto de la
# aplicacion, que muestra pesos chilenos ("$25.806").
# ------------------------------------------------------------------


def test_los_montos_van_en_formato_chileno():
    assert _clp(25806) == "$25.806"
    assert _clp(1234567) == "$1.234.567"
    assert _clp(990) == "$990"
    assert _clp(25806.4) == "$25.806"  # sin decimales


def test_la_razon_que_ve_el_cliente_usa_punto_de_miles():
    competencia = AnalisisCompetencia(hay_competencia=False, precio_ganador=None, rango_precio_minimo=None, rango_precio_maximo=None)
    recomendacion = recomendar_precio(
        costo=12500.0, channel_costs=CHANNEL, margen_objetivo_pct=25.0, margen_minimo_pct=10.0, analisis_competencia=competencia
    )
    razon = evaluar_decision(recomendacion, competencia).razon
    assert "," not in razon.split("$")[1][:10]  # ningun separador de miles con coma
