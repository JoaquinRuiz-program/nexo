"""
Pruebas de app/domain/marketplace_orders.py — sobre todo, que NUNCA se
extrae información personal del comprador aunque venga en el payload real
de Mercado Libre, y que la comisión nunca se inventa.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.marketplace_orders import map_ml_order, map_order_status


def _pedido_real_de_ejemplo(**overrides):
    """Forma real de un pedido de GET /orders/search de Mercado Libre —
    incluye el objeto "buyer" completo a propósito, para poder probar que
    map_ml_order nunca lo toca."""
    base = {
        "id": 2000012345678,
        "date_created": "2026-08-24T10:15:00.000-04:00",
        "status": "paid",
        "total_amount": 12990.0,
        "buyer": {
            "id": 987654321,
            "nickname": "COMPRADOR_TEST",
            "first_name": "Nombre real",
            "last_name": "Apellido real",
            "email": "comprador@ejemplo.cl",
            "phone": {"number": "912345678"},
        },
        "order_items": [
            {
                "item": {"id": "MLC123456789", "title": "Cien años de soledad", "seller_sku": "LIB-001"},
                "quantity": 1,
                "unit_price": 12990.0,
                "sale_fee": 1300.0,
            }
        ],
    }
    base.update(overrides)
    return base


def test_mapea_los_campos_basicos_del_pedido():
    fila = map_ml_order(_pedido_real_de_ejemplo())

    assert fila["external_order_id"] == "2000012345678"
    assert fila["order_date"] == datetime.fromisoformat("2026-08-24T10:15:00.000-04:00")
    assert fila["status"] == "recibido"
    assert fila["total_amount"] == 12990.0


def test_nunca_extrae_datos_del_comprador():
    fila = map_ml_order(_pedido_real_de_ejemplo())

    assert "buyer" not in fila
    serializado = str(fila)
    assert "comprador@ejemplo.cl" not in serializado
    assert "Nombre real" not in serializado
    assert "912345678" not in serializado


@pytest.mark.parametrize(
    "estado_ml, esperado",
    [("paid", "recibido"), ("confirmed", "recibido"), ("cancelled", "cancelado"), ("", "recibido")],
)
def test_mapeo_de_estados(estado_ml, esperado):
    assert map_order_status(estado_ml) == esperado


def test_comision_es_la_suma_real_de_sale_fee_por_item():
    pedido = _pedido_real_de_ejemplo(
        order_items=[
            {"item": {"id": "A", "seller_sku": "LIB-001"}, "quantity": 1, "unit_price": 10000, "sale_fee": 1200},
            {"item": {"id": "B", "seller_sku": "LIB-002"}, "quantity": 2, "unit_price": 5000, "sale_fee": 600},
        ]
    )
    fila = map_ml_order(pedido)
    assert fila["commission_amount"] == 1800.0


def test_comision_es_none_si_ml_no_la_informo_nunca_un_cero_inventado():
    pedido = _pedido_real_de_ejemplo(
        order_items=[{"item": {"id": "A", "seller_sku": "LIB-001"}, "quantity": 1, "unit_price": 10000, "sale_fee": None}]
    )
    fila = map_ml_order(pedido)
    assert fila["commission_amount"] is None


def test_extrae_sku_de_seller_custom_field_si_no_hay_seller_sku():
    pedido = _pedido_real_de_ejemplo(
        order_items=[
            {
                "item": {"id": "A", "seller_custom_field": "LIB-VIEJO-001"},
                "quantity": 1,
                "unit_price": 10000,
                "sale_fee": 1000,
            }
        ]
    )
    fila = map_ml_order(pedido)
    assert fila["items"][0]["sku"] == "LIB-VIEJO-001"


def test_sin_sku_de_ningun_tipo_queda_none_no_se_inventa():
    pedido = _pedido_real_de_ejemplo(
        order_items=[{"item": {"id": "A"}, "quantity": 1, "unit_price": 10000, "sale_fee": 1000}]
    )
    fila = map_ml_order(pedido)
    assert fila["items"][0]["sku"] is None


def test_sin_date_created_lanza_error_en_vez_de_inventar_una_fecha():
    pedido = _pedido_real_de_ejemplo(date_created=None)
    with pytest.raises(ValueError):
        map_ml_order(pedido)
