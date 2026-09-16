"""Análisis de rentabilidad en vivo (16 de septiembre de 2026, pedido del
dueño: al subir el Excel, obtener automáticamente el costo de envío de
Mercado Libre de cada producto, sin peso ni medidas, sin que la pantalla
parezca congelada). Ver services/analisis_rentabilidad_stream.py.

No reimplementa ninguna llamada a Mercado Libre: orquesta con progreso los
mismos servicios ya probados en test_mercadolibre_endpoints.py y
test_envio_estimado.py — acá se prueba el streaming y que el resultado final
coincide con /api/seleccion (misma regla en toda la aplicación)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.db.models import ChannelCostSettings
from app.services import analisis_rentabilidad_stream as stream_mod
from app.services.analisis_rentabilidad_stream import analizar_catalogo_stream
from app.services.ml_comisiones import _tiendas_en_curso
from tests.test_publicaciones_endpoint import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    _producto_publicable,
    a_store,
    client,
    cuenta_ml_conectada,
    db_session,
)


def _lineas(texto: str) -> list[dict]:
    return [json.loads(linea) for linea in texto.strip().split("\n") if linea.strip()]


def test_sin_cuenta_conectada_devuelve_un_evento_de_error(client, a_store, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    res = client.post("/api/mercadolibre/analisis-rentabilidad/stream")
    assert res.status_code == 200  # el error viaja DENTRO del stream, nunca como HTTP 4xx/5xx
    eventos = _lineas(res.text)
    assert eventos[0] == {"tipo": "error", "mensaje": "Conecta Mercado Libre en Integraciones para analizar el envío y la rentabilidad con datos reales."}


@respx.mock
def test_analiza_un_producto_y_coincide_con_seleccion(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    # _producto_publicable ya deja la categoría y el envío de Mercado Libre
    # resueltos (ver tests/test_publicaciones_endpoint.py) — acá solo falta
    # la comisión real, que sí es una llamada nueva a Mercado Libre.
    _producto_publicable(db_session, a_store, sku="ANALISIS-1", precio=20000, costo=8000)
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/listing_prices.*").mock(
        return_value=httpx.Response(
            200,
            json=[{
                "listing_type_id": "gold_special", "listing_type_name": "Clásica",
                "sale_fee_amount": 2000, "sale_fee_details": {"fixed_fee": 0, "percentage_fee": 10},
            }],
        )
    )

    res = client.post("/api/mercadolibre/analisis-rentabilidad/stream")

    assert res.status_code == 200
    eventos = _lineas(res.text)
    assert eventos[0] == {"tipo": "inicio"}
    tipos = [e["tipo"] for e in eventos]
    assert "producto" in tipos and "resumen" in tipos

    producto = next(e for e in eventos if e["tipo"] == "producto" and e["sku"] == "ANALISIS-1")
    assert producto["comisionObtenida"] is True
    assert producto["envioObtenido"] is True
    # 20.000 − 8.000 − 10% de comisión (2.000) − envío (comprador paga, $0)
    assert producto["clasificacion"] == "rentable"

    resumen = next(e for e in eventos if e["tipo"] == "resumen")
    assert resumen["conviene"] == 1
    assert resumen["total"] == 1

    # La MISMA regla en toda la aplicación: el resumen tiene que coincidir
    # con lo que ya calcula /api/seleccion sobre los mismos datos.
    seleccion = client.get("/api/seleccion", params={"canal": "mercadolibre"}).json()
    assert seleccion["resumen"]["rentables"] == resumen["conviene"]


@respx.mock
def test_producto_sin_envio_resuelto_termina_en_faltan_datos(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """El análisis nunca inventa un envío: si Mercado Libre no lo resuelve
    (acá, sin categoría detectable), el producto queda "sin_datos" — igual
    que en Oportunidades."""
    monkeypatch.setattr("app.api.routes.mercadolibre.get_settings", lambda: CONFIGURED_SETTINGS)
    _producto_publicable(
        db_session, a_store, sku="SIN-CATEGORIA", precio=15000, costo=5000, ml_category_id=None, envio_ml_resuelto=False,
    )
    respx.get(url__regex=r"https://api\.mercadolibre\.com/sites/MLC/domain_discovery/search.*").mock(
        return_value=httpx.Response(200, json=[])  # Mercado Libre no encuentra categoría
    )

    res = client.post("/api/mercadolibre/analisis-rentabilidad/stream")

    eventos = _lineas(res.text)
    producto = next(e for e in eventos if e["tipo"] == "producto" and e["sku"] == "SIN-CATEGORIA")
    assert producto["envioObtenido"] is False
    assert producto["clasificacion"] == "sin_datos"
    resumen = next(e for e in eventos if e["tipo"] == "resumen")
    assert resumen["faltanDatos"] == 1
    assert resumen["conviene"] == 0


@pytest.mark.asyncio
async def test_espera_una_corrida_ya_en_curso_en_vez_de_fallar(db_session, a_store, cuenta_ml_conectada, monkeypatch):
    """Si el disparo automático del import ya está corriendo para esta
    empresa (mismo guardia que actualizar_comisiones_en_segundo_plano), el
    análisis en vivo espera en vez de mostrar un error — y si se pasa el
    tope de espera, igual termina clasificando con lo que ya haya."""
    monkeypatch.setattr(stream_mod, "LATIDO_SEGUNDOS", 0.01)
    monkeypatch.setattr(stream_mod, "ESPERA_MAXIMA_SEGUNDOS", 0.03)
    _producto_publicable(db_session, a_store, sku="EN-CURSO", precio=10000, costo=4000)

    _tiendas_en_curso.add(a_store.id)
    try:
        eventos = [e async for e in analizar_catalogo_stream(db_session, a_store, CONFIGURED_SETTINGS)]
        # La corrida "ya en curso" (de otra parte) nunca la tocó este
        # análisis: seguía marcada exactamente como la dejó el test.
        assert a_store.id in _tiendas_en_curso
    finally:
        _tiendas_en_curso.discard(a_store.id)

    tipos = [e["tipo"] for e in eventos]
    assert "consultando_ml" in tipos  # esperó, mostrando progreso
    assert "producto" in tipos and "resumen" in tipos  # y terminó clasificando igual
