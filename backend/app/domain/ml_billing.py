"""
Lógica pura de la conciliación de comisiones con la facturación de Mercado
Libre (14 de septiembre de 2026). Formato de `details` según la doc oficial
"Billing Reports by Orders and Packs": cada detalle trae `charge_info`
(detail_amount, detail_type, detail_sub_type) e `items_info` (item_type).
"""

from __future__ import annotations

SUBTIPO_CARGO_VENTA = "CV"
SUBTIPO_CARGO_ENVIO = "CXD"
# Redondeos de Mercado Libre: hasta $1 de diferencia se considera que coincide.
TOLERANCIA_CLP = 1.0

COINCIDE = "coincide"
DIFERENCIA = "diferencia"
SIN_ESTIMACION = "sin_estimacion"
SIN_FACTURAR = "sin_facturar"


def resumir_cargos(detalles: list | None) -> dict:
    venta = envio = otros = 0.0
    hay_cargos = False
    for detalle in detalles or []:
        info = (detalle or {}).get("charge_info") or {}
        if info.get("detail_type") != "CHARGE" or info.get("detail_amount") is None:
            continue
        hay_cargos = True
        monto = float(info["detail_amount"])
        subtipo = info.get("detail_sub_type")
        if subtipo == SUBTIPO_CARGO_VENTA:
            venta += monto
        elif subtipo == SUBTIPO_CARGO_ENVIO:
            envio += monto
        else:
            otros += monto
    return {"hay_cargos": hay_cargos, "cargo_venta": round(venta, 2), "cargo_envio": round(envio, 2), "otros_cargos": round(otros, 2)}


def tipo_de_publicacion(detalles: list | None) -> str | None:
    """El item_type de la venta si es uno solo; None si no viene o hay varios
    (no se adivina cuál corresponde a cada ítem)."""
    tipos = {
        item.get("item_type")
        for detalle in detalles or []
        for item in ((detalle or {}).get("items_info") or [])
        if item.get("item_type")
    }
    return tipos.pop() if len(tipos) == 1 else None


def estado_conciliacion(hay_cargos: bool, cargo_venta: float, comision_estimada: float | None) -> str:
    if not hay_cargos:
        return SIN_FACTURAR
    if comision_estimada is None:
        return SIN_ESTIMACION
    return COINCIDE if abs(cargo_venta - comision_estimada) <= TOLERANCIA_CLP else DIFERENCIA
