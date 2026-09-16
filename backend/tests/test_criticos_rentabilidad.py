"""
Críticos 1 a 3 de REVISION_EXPERIENCIA.md (15 de septiembre de 2026):
comisión real por defecto en todas las pantallas, Dashboard con la misma
regla que Oportunidades y envío manual desde un precio de venta.
"""

from __future__ import annotations

from datetime import datetime

from app.api.routes.rentabilidad import aplicar_envio_real_ml, preferencia_efectiva
from app.db.models import ChannelCostSettings, MercadoLibreShippingEstimate, ProductVariant
from app.domain.ml_fees import ListingFee
from app.domain.ml_shipping import MOTIVO_BAJO_EL_MINIMO_DEL_DUENO
from app.domain.profitability import ChannelCosts
from tests.test_publicaciones_endpoint import (  # noqa: F401 — fixtures
    _agregar_comision_ml_real,
    _configurar_margen,
    _envio_ml_resuelto,
    _producto_publicable,
    a_store,
    client,
    db_session,
)


# ------------------------------------------------------------------
# 1. Comisión real por defecto
# ------------------------------------------------------------------


def test_sin_preferencia_se_usa_el_tipo_recomendado_con_comision_real():
    comisiones = {
        "classic": ListingFee(listing_type_name="gold_special", percentage_fee=10.0, fixed_fee=0.0, sale_fee_amount=2000.0),
        "premium": ListingFee(listing_type_name="gold_pro", percentage_fee=15.0, fixed_fee=0.0, sale_fee_amount=3000.0),
    }
    pref, recomendacion = preferencia_efectiva(None, 20000.0, 8000.0, comisiones, ChannelCosts(commission_pct=40.0), 25.0)
    assert pref in ("classic", "premium")
    assert recomendacion is not None


def test_con_preferencia_manual_se_respeta_y_sin_comision_real_no_hay_tipo():
    assert preferencia_efectiva("premium", 20000.0, 8000.0, {}, ChannelCosts(commission_pct=15.0), 25.0) == ("premium", None)
    assert preferencia_efectiva(None, 20000.0, 8000.0, {}, ChannelCosts(commission_pct=15.0), 25.0) == (None, None)


def test_precio_recomendado_y_decision_usan_la_comision_real_sin_preferencia(client, db_session, a_store):
    variant_id = _producto_publicable(db_session, a_store, sku="REAL-AUTO", costo=8000, precio=20000)
    producto = db_session.query(ProductVariant).filter_by(id=variant_id).one().product
    producto.ml_category_id = "MLC180937"
    db_session.commit()
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_special", percentage_fee=10.0)
    _agregar_comision_ml_real(db_session, a_store, category_id="MLC180937", price=20000, listing_type_id="gold_pro", percentage_fee=16.0)
    canal = db_session.query(ChannelCostSettings).filter_by(store_id=a_store.id, channel="mercadolibre").one()
    canal.commission_pct = 50.0  # respaldo absurdo: no debe usarse
    canal.listing_type_pref = None
    db_session.commit()
    _configurar_margen(db_session, a_store, objetivo=25.0, minimo=10.0)

    precio = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    decision = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/decision").json()

    assert precio["comisionMlFuente"] == "real"
    assert decision["comisionMlFuente"] == "real"
    assert decision["decision"] == "conviene"


# ------------------------------------------------------------------
# 2. Dashboard con la misma regla que Oportunidades
# ------------------------------------------------------------------


def test_dashboard_cuenta_solo_los_que_convienen_en_mercado_libre(client, db_session, a_store):
    _producto_publicable(db_session, a_store, sku="DASH-SI", costo=8000, precio=20000)   # 20000-8000-3000 = 9000 (45 %)
    # 20000-18000-3000 = -1000: pierde plata en Mercado Libre aunque venta − compra sea +2000.
    _producto_publicable(db_session, a_store, sku="DASH-NO", costo=18000, precio=20000)

    rent = client.get("/api/dashboard/resumen").json()["rentabilidad"]

    assert rent["productosConCosto"] == 2
    assert rent["productosRentables"] == 1  # venta − compra daría 2


# ------------------------------------------------------------------
# 3. Envío manual desde un precio de venta
# ------------------------------------------------------------------


def _estimacion_ml(costo: float, obligatorio: bool = True) -> MercadoLibreShippingEstimate:
    """Estimación vigente de Mercado Libre, sin pasar por la base."""
    return MercadoLibreShippingEstimate(
        category_id="MLC180937", price=0, shipping_cost=costo, mandatory=obligatorio,
        dimensions="5x15x15,300", fetched_at=datetime.now(),
    )


def test_el_envio_de_ml_no_se_descuenta_bajo_el_precio_indicado():
    """El umbral "envío desde $X" se aplica al envío que informa Mercado Libre.
    16 de septiembre de 2026: el envío manual de Configuración ya no completa
    el cálculo — sin dato de Mercado Libre, el envío queda desconocido."""
    costos = ChannelCosts(commission_pct=14.0, shipping_cost=3500.0)
    bajo, datos_bajo = aplicar_envio_real_ml(costos, None, precio=4990.0, envio_desde_clp=20000.0, estimacion=_estimacion_ml(3500.0))
    alto, _ = aplicar_envio_real_ml(costos, None, precio=29990.0, envio_desde_clp=20000.0, estimacion=_estimacion_ml(3500.0))
    sin_umbral, _ = aplicar_envio_real_ml(costos, None, precio=4990.0, estimacion=_estimacion_ml(3500.0))
    assert bajo.shipping_cost == 0.0
    assert datos_bajo["envioMlMotivo"] == MOTIVO_BAJO_EL_MINIMO_DEL_DUENO
    assert alto.shipping_cost == 3500.0
    assert sin_umbral.shipping_cost == 3500.0

    # Solo el envío manual: dato faltante, no un envío de $0.
    solo_manual, datos = aplicar_envio_real_ml(costos, None, precio=29990.0)
    assert solo_manual.shipping_unknown is True and solo_manual.shipping_cost is None
    assert datos["envioMlResuelto"] is False


def test_oportunidades_aplica_el_umbral_de_envio(client, db_session, a_store):
    _producto_publicable(db_session, a_store, sku="ENV-BARATO", costo=2000, precio=4990)
    _envio_ml_resuelto(db_session, a_store, categoria="MLC180937", precio=4990, costo=3500)
    canal = db_session.query(ChannelCostSettings).filter_by(store_id=a_store.id, channel="mercadolibre").one()
    canal.shipping_cost = 3500
    db_session.commit()

    sin_umbral = next(p for p in client.get("/api/seleccion", params={"canal": "mercadolibre"}).json()["productos"] if p["sku"] == "ENV-BARATO")
    canal.shipping_min_price_clp = 20000
    db_session.commit()
    con_umbral = next(p for p in client.get("/api/seleccion", params={"canal": "mercadolibre"}).json()["productos"] if p["sku"] == "ENV-BARATO")

    assert sin_umbral["margenMercadoLibreClp"] < 0            # 4990 - 2000 - 748,5 - 3500
    assert con_umbral["margenMercadoLibreClp"] == 4990 - 2000 - 748.5


def test_configuracion_guarda_el_umbral_de_envio(client, a_store):
    res = client.put("/api/configuracion/canales/mercadolibre", json={"commission_pct": 14, "shipping_cost": 3500, "shipping_min_price_clp": 19990})
    assert res.status_code == 200, res.text
    assert res.json()["shippingMinPriceClp"] == 19990.0
