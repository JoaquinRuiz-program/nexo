"""
Pruebas de app/domain/marketplace_stock.py — la decisión del dueño de no
controlar inventario físico, solo un tope manual para Mercado Libre.
"""

from __future__ import annotations

import pytest

from app.domain.marketplace_stock import (
    MarketplaceStockError,
    apply_sale,
    is_available_for_sale,
    set_manual_stock,
)


def test_producto_no_configurado_no_esta_disponible():
    """None = nunca se configuró un tope para ML -> no se puede vender por ese canal."""
    assert is_available_for_sale(None) is False


def test_producto_con_stock_en_cero_no_esta_disponible():
    """0 es un estado válido y distinto de None: "se ofrecía, ya no queda"."""
    assert is_available_for_sale(0) is False


def test_hay_disponibilidad_si_alcanza_para_la_cantidad_pedida():
    assert is_available_for_sale(5, quantity=3) is True
    assert is_available_for_sale(2, quantity=3) is False


def test_ejemplo_del_dueno_vender_una_unidad_baja_el_disponible():
    # Producto X: disponible ML = 5, se vende 1 -> disponible = 4.
    assert apply_sale(5, 1) == 4


def test_no_se_puede_vender_mas_de_lo_reservado():
    with pytest.raises(MarketplaceStockError):
        apply_sale(2, 3)


def test_no_se_puede_vender_si_no_esta_configurado():
    with pytest.raises(MarketplaceStockError):
        apply_sale(None, 1)


def test_no_se_puede_vender_una_cantidad_de_cero_o_negativa():
    with pytest.raises(ValueError):
        apply_sale(5, 0)
    with pytest.raises(ValueError):
        apply_sale(5, -1)


def test_vender_todo_lo_reservado_deja_en_cero_no_en_negativo():
    assert apply_sale(3, 3) == 0


def test_el_dueno_puede_modificar_manualmente_el_tope():
    # 5 -> 10 -> 0, exactamente el ejemplo del dueño.
    assert set_manual_stock(5) == 5
    assert set_manual_stock(10) == 10
    assert set_manual_stock(0) == 0


def test_poner_en_none_pausa_sin_ser_un_error():
    """Volver a "no configurado" (dejar de ofrecer del todo) es válido, no
    lo mismo que un valor inválido."""
    assert set_manual_stock(None) is None


def test_no_se_puede_configurar_un_tope_negativo():
    with pytest.raises(ValueError):
        set_manual_stock(-1)
