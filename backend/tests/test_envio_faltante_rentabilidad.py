"""Regla estricta del envío (16 de septiembre de 2026, pedido del dueño:
"no puedes ver el envío antes de decir si es conveniente o no").

Con costo de envío disponible se calcula normal; sin él, Nexo NO dice
"Conviene" ni "No conviene" — dice "Faltan datos" y explica qué falta. Un
envío desconocido nunca se reemplaza por $0. Ojo con la distinción, que es
la que pidió el dueño: un costo de COMPRA vacío sí es dato válido (costo
considerado $0), un ENVÍO desconocido no.

Ninguna prueba llama a la API real de Mercado Libre.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db.models import MercadoLibreShippingEstimate, ProductVariant
from app.domain.catalog_selection import SelectionCriteria, classify_product
from app.domain.ml_shipping import MOTIVO_ESTIMACION_VENCIDA, MOTIVO_SIN_ESTIMACION
from app.domain.profitability import ChannelCosts, net_margin
from tests.test_publicaciones_endpoint import (  # noqa: F401 — fixtures
    CONFIGURED_SETTINGS,
    _producto_publicable,
    a_store,
    client,
    cuenta_ml_conectada,
    db_session,
)
from tests.test_rentabilidad import _publicacion_ml

CATEGORIA = "MLC180937"
CRITERIOS_ML = SelectionCriteria(channel="mercadolibre", min_margin_pct=15.0, ganancia_minima_clp=3000.0)


def _configurar_canal(client, **extra):
    """Canal Mercado Libre con comisión de respaldo, SIN envío manual: el
    envío lo tiene que traer Mercado Libre (real o estimado)."""
    client.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 10, "target_margin_pct": 30, "min_margin_pct": 15, **extra})


def _producto(db_session, tienda, *, sku, precio, costo, categoria=CATEGORIA):
    """Sin envío resuelto: cada prueba decide qué dato de envío existe."""
    variant_id = _producto_publicable(db_session, tienda, sku=sku, precio=precio, costo=costo, envio_ml_resuelto=False)
    variante = db_session.query(ProductVariant).filter_by(id=variant_id).one()
    variante.product.ml_category_id = categoria
    variante.product.ml_category_name = "Categoría de prueba"
    if costo is None:
        variante.cost_price = None
    db_session.commit()
    return variant_id


def _estimacion(db_session, tienda, *, precio, costo, obligatorio=True, motivo=None, dias_de_antiguedad=0, categoria=CATEGORIA):
    db_session.add(MercadoLibreShippingEstimate(
        store_id=tienda.id, category_id=categoria, price=precio, shipping_cost=costo, mandatory=obligatorio,
        dimensions="5x15x15,300", unavailable_reason=motivo,
        fetched_at=datetime.now() - timedelta(days=dias_de_antiguedad),
    ))
    db_session.commit()


def _fila(client, sku):
    return next(f for f in client.get("/api/rentabilidad").json()["productos"] if f["sku"] == sku)


def _oportunidad(client, sku):
    productos = client.get("/api/seleccion", params={"canal": "mercadolibre"}).json()["productos"]
    return next(p for p in productos if p["sku"] == sku)


# ------------------------------------------------------------------
# 1 y 2. Con el envío disponible se calcula normal
# ------------------------------------------------------------------


def test_con_envio_disponible_se_calcula_normal_y_el_veredicto_es_definitivo(client, db_session, a_store):
    _configurar_canal(client)
    _producto(db_session, a_store, sku="ENV-OK", precio=20000, costo=5000)
    _estimacion(db_session, a_store, precio=20000, costo=3050)

    fila = _fila(client, "ENV-OK")
    assert fila["envioMlFuente"] == "estimado_ml"
    assert fila["envioMlResuelto"] is True
    # 20.000 − 10 % comisión − 3.050 envío − 5.000 costo
    assert fila["margenMercadoLibreClp"] == pytest.approx(9950.0)
    assert _oportunidad(client, "ENV-OK")["clasificacion"] == "rentable"


def test_sin_costo_de_compra_pero_con_envio_se_calcula_con_costo_cero(client, db_session, a_store):
    """El costo de compra vacío SÍ es un dato válido para el cálculo (costo
    considerado $0). El envío desconocido no — no son equivalentes."""
    _configurar_canal(client)
    _producto(db_session, a_store, sku="SIN-COSTO", precio=20000, costo=None)
    _estimacion(db_session, a_store, precio=20000, costo=3050)

    fila = _fila(client, "SIN-COSTO")
    assert fila["tieneCosto"] is False
    assert fila["costo"] is None
    # 20.000 − 10 % comisión − 3.050 envío − 0 de costo
    assert fila["margenMercadoLibreClp"] == pytest.approx(14950.0)
    assert _oportunidad(client, "SIN-COSTO")["clasificacion"] == "rentable"


def test_envio_real_de_cero_es_un_dato_valido_y_se_calcula_normal(client, db_session, a_store):
    """$0 solo vale cuando de verdad significa "el vendedor no paga envío"."""
    _configurar_canal(client)
    variant_id = _producto(db_session, a_store, sku="ENV-CERO", precio=20000, costo=5000)
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    _publicacion_ml(db_session, a_store, producto, costo_envio=0)

    fila = _fila(client, "ENV-CERO")
    assert fila["envioMlFuente"] == "mercadolibre"
    assert fila["costoEnvioMl"] == 0.0
    assert fila["envioMlResuelto"] is True
    assert fila["margenMercadoLibreClp"] == pytest.approx(13000.0)  # 20.000 − 2.000 − 5.000
    assert _oportunidad(client, "ENV-CERO")["clasificacion"] == "rentable"


# ------------------------------------------------------------------
# 3, 4 y 5. Sin envío: "Faltan datos", nunca un veredicto
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "preparar, motivo_esperado",
    [
        # Estimación todavía no consultada (o categoría sin detectar): no hay fila.
        (lambda db, tienda: None, None),
        # Mercado Libre respondió sin un costo válido / la consulta falló.
        (lambda db, tienda: _estimacion(db, tienda, precio=20000, costo=None, obligatorio=None, motivo=MOTIVO_SIN_ESTIMACION), MOTIVO_SIN_ESTIMACION),
        # Estimación vencida que no se pudo actualizar.
        (lambda db, tienda: _estimacion(db, tienda, precio=20000, costo=3050, dias_de_antiguedad=40), MOTIVO_ESTIMACION_VENCIDA),
    ],
    ids=["sin_estimacion", "consulta_fallida", "estimacion_vencida"],
)
def test_sin_envio_no_hay_rentabilidad_ni_veredicto(client, db_session, a_store, preparar, motivo_esperado):
    _configurar_canal(client)
    _producto(db_session, a_store, sku="SIN-ENVIO", precio=20000, costo=5000)
    preparar(db_session, a_store)

    fila = _fila(client, "SIN-ENVIO")
    assert fila["envioMlResuelto"] is False
    assert fila["envioMlFuente"] == "no_disponible"
    assert fila["costoEnvioMl"] is None
    # Lo importante: NO hay margen calculado con un envío supuesto de $0.
    assert fila["margenMercadoLibreClp"] is None
    assert fila["margenMercadoLibrePct"] is None
    if motivo_esperado is not None:
        assert fila["envioMlMotivo"] == motivo_esperado

    oportunidad = _oportunidad(client, "SIN-ENVIO")
    assert oportunidad["clasificacion"] == "sin_datos"
    assert oportunidad["razon"].startswith("Falta el costo de envío de Mercado Libre para calcular la rentabilidad.")

    decision = client.get(f"/api/publicaciones/{fila['id']}/mercadolibre/decision").json()
    assert decision["decision"] == "revisar"
    assert "costo de envío de Mercado Libre" in decision["faltantes"]


def test_el_envio_manual_de_configuracion_no_reemplaza_al_de_mercado_libre(client, db_session, a_store):
    """Antes, con un envío manual cargado el margen salía "provisional" pero
    el veredicto igual decía "Conviene". Ahora el manual no decide."""
    _configurar_canal(client, shipping_cost=2000)
    _producto(db_session, a_store, sku="ENV-MANUAL", precio=20000, costo=5000)

    fila = _fila(client, "ENV-MANUAL")
    assert fila["envioMlResuelto"] is False
    assert fila["margenMercadoLibreClp"] is None
    assert _oportunidad(client, "ENV-MANUAL")["clasificacion"] == "sin_datos"


# ------------------------------------------------------------------
# 7 y 8. Nada de lo que muestra rentabilidad dice "Conviene" sin el envío
# ------------------------------------------------------------------


def test_sin_envio_no_es_una_oportunidad_publicable(client, db_session, a_store, cuenta_ml_conectada, monkeypatch):
    monkeypatch.setattr("app.api.routes.publicaciones.get_settings", lambda: CONFIGURED_SETTINGS)
    _configurar_canal(client)
    variant_id = _producto(db_session, a_store, sku="NO-PUBLICABLE", precio=20000, costo=5000)

    resumen = client.get("/api/seleccion", params={"canal": "mercadolibre"}).json()["resumen"]
    assert resumen["rentables"] == 0
    assert resumen["sinDatos"] == 1

    res = client.post(
        f"/api/publicaciones/{variant_id}/mercadolibre/confirmar",
        json={"category_id": CATEGORIA, "condition": "new", "listing_type": "classic", "attributes": {}},
    )
    assert res.status_code == 400
    assert "costo de envío de Mercado Libre" in res.json()["detail"]


def test_ninguna_pantalla_dice_conviene_cuando_falta_el_envio(client, db_session, a_store):
    _configurar_canal(client)
    variant_id = _producto(db_session, a_store, sku="PANTALLAS", precio=20000, costo=5000)

    # Dashboard
    assert client.get("/api/dashboard/resumen").json()["rentabilidad"]["productosRentables"] == 0
    # Columna "Decisión" de Oportunidades (lote)
    lote = client.get("/api/publicaciones/mercadolibre/decision-lote").json()
    assert [d["decision"] for d in lote if d["variantId"] == variant_id] == ["revisar"]
    # Paso "¿Conviene?" del flujo de publicación
    assert client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision").json()["decision"] == "revisar"
    # Precio recomendado: tampoco se recomienda un precio que ignora el envío
    precio = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    assert precio["estado"] == "datos_insuficientes"
    assert "costo de envío de Mercado Libre" in precio["faltantes"]
    assert precio["precioRecomendado"] is None


# ------------------------------------------------------------------
# El fondo del asunto: un envío que falta no es un envío de $0
# ------------------------------------------------------------------


def test_net_margin_no_convierte_un_envio_desconocido_en_cero():
    conocido = ChannelCosts(commission_pct=10.0, shipping_cost=0.0)
    desconocido = ChannelCosts(commission_pct=10.0, shipping_cost=None, shipping_unknown=True)
    assert net_margin(20000.0, 5000.0, conocido) == pytest.approx(13000.0)
    assert net_margin(20000.0, 5000.0, desconocido) is None


def test_una_fila_sin_el_dato_del_envio_nunca_se_clasifica_como_rentable():
    """Estricto por defecto: si la fila no dice que el envío está resuelto,
    es dato faltante (nunca "rentable" por descarte)."""
    fila = {"id": 1, "precio": 20000.0, "mercadoLibreConfigurado": True, "margenMercadoLibreClp": 9000.0, "margenMercadoLibrePct": 45.0}
    assert classify_product(fila, CRITERIOS_ML)["clasificacion"] == "sin_datos"
    assert classify_product({**fila, "envioMlResuelto": False}, CRITERIOS_ML)["clasificacion"] == "sin_datos"
    assert classify_product({**fila, "envioMlResuelto": True}, CRITERIOS_ML)["clasificacion"] == "rentable"
