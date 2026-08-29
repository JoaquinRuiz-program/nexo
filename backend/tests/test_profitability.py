"""
Pruebas de app/domain/profitability.py — en particular, que nunca se
inventa un margen cuando falta un dato (costo o costos del canal).
"""

from __future__ import annotations

from app.domain.profitability import ChannelCosts, gross_margin, gross_margin_pct, net_margin, net_margin_pct


def test_margen_bruto_se_calcula_con_venta_y_costo():
    assert gross_margin(30000, 18000) == 12000


def test_margen_bruto_es_none_sin_costo():
    """Caso central del pedido del dueño: sin costo cargado, no hay margen
    — ni siquiera cero."""
    assert gross_margin(30000, None) is None


def test_margen_bruto_pct_se_calcula_sobre_el_precio_de_venta():
    assert gross_margin_pct(10000, 7000) == 30.0


def test_margen_bruto_pct_es_none_si_precio_es_cero():
    assert gross_margin_pct(0, 100) is None


def test_margen_neto_es_none_si_el_canal_no_tiene_costos_configurados():
    """No se asume ninguna comisión (ni 13% ni ningún otro número) cuando
    el canal no está configurado todavía."""
    sin_configurar = ChannelCosts()
    assert net_margin(10000, 7000, sin_configurar) is None
    assert net_margin_pct(10000, 7000, sin_configurar) is None


def test_margen_neto_descuenta_comision_envio_y_otros_costos():
    # Ejemplo del dueño: Libro B — venta $10.000, costo $7.000, ML+envío $2.700 -> margen $300
    costos_ml = ChannelCosts(commission_pct=12.0, shipping_cost=1500, other_fixed_cost=0)
    # comisión 12% de 10.000 = 1.200; + envío 1.500 = 2.700 total de costos de canal
    margen = net_margin(10000, 7000, costos_ml)
    assert margen == 300


def test_margen_neto_es_none_sin_costo_de_producto_aunque_el_canal_este_configurado():
    costos_ml = ChannelCosts(commission_pct=12.0)
    assert net_margin(10000, None, costos_ml) is None


def test_margen_neto_permite_detectar_producto_que_pierde_por_un_canal():
    """El caso que motivó todo esto: un producto rentable en tienda física
    puede no convenir por Mercado Libre."""
    costos_ml = ChannelCosts(commission_pct=13.0, shipping_cost=2000)
    margen_tienda = gross_margin(5000, 4200)  # $800 en tienda
    margen_ml = net_margin(5000, 4200, costos_ml)  # 13% de 5000 = 650 + 2000 envío = 2650
    assert margen_tienda == 800
    assert margen_ml == -1850
    assert margen_ml < margen_tienda
