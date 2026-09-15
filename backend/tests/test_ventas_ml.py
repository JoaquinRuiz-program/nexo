"""Pruebas de app/domain/ventas_ml.py — métricas de ventas reales de Mercado
Libre, funciones puras (15 de septiembre de 2026)."""

from __future__ import annotations

from datetime import date, datetime

from app.domain.ventas_ml import Venta, VentaItem, grafico_ventas, mas_vendidos, pedidos, resumen_ventas

HOY = date(2026, 9, 15)


def _venta(ext, fecha, total, *, estado="recibido", reembolsada=False, items=()):
    return Venta(external_id=ext, fecha=fecha, estado=estado, total=total, reembolsada=reembolsada, items=list(items))


VENTAS = [
    _venta("1", datetime(2026, 9, 15, 10), 10000, items=[VentaItem("A-1", "Producto A", 2, 10000)]),
    _venta("2", datetime(2026, 9, 14, 9), 5000, items=[VentaItem("B-1", "Producto B", 1, 5000)]),
    _venta("3", datetime(2026, 9, 15, 11), 7000, estado="cancelado", items=[VentaItem("A-1", "Producto A", 1, 7000)]),
    _venta("4", datetime(2026, 9, 10, 11), 3000, reembolsada=True, items=[VentaItem("A-1", "Producto A", 1, 3000)]),
    _venta("5", datetime(2026, 8, 31, 23), 9000, items=[VentaItem("C-1", "Producto C", 1, 9000), VentaItem("B-1", "Producto B", 1, 0)]),
]


def test_resumen_suma_solo_ventas_efectivas():
    r = resumen_ventas(VENTAS, HOY)
    assert (r["ventasHoy"], r["pedidosHoy"]) == (10000, 1)
    assert (r["ventasAyer"], r["pedidosAyer"]) == (5000, 1)
    assert (r["ventasUltimos7Dias"], r["pedidosUltimos7Dias"]) == (15000, 2)
    # Mes en curso: sin la cancelada, sin la reembolsada y sin la de agosto.
    assert (r["ventasMes"], r["pedidosMes"], r["productosVendidosMes"]) == (15000, 2, 3)
    assert r["ticketPromedioMes"] == 7500
    assert r["pedidosCancelados"] == 1


def test_resumen_no_inventa_estados_de_envio():
    r = resumen_ventas(VENTAS, HOY)
    assert r["pedidosPendientes"] is None and r["pedidosEnviados"] is None and r["pedidosEntregados"] is None


def test_grafico_un_punto_por_dia_sin_canceladas():
    puntos = grafico_ventas(VENTAS, "7d", HOY)
    assert len(puntos) == 7
    assert puntos[0]["fecha"] == "2026-09-09"
    assert puntos[-1] == {"fecha": "2026-09-15", "ingresos": 10000, "pedidos": 1}


def test_mas_vendidos_por_cantidad():
    top = mas_vendidos(VENTAS, "30d", HOY, 10)
    assert [(p["sku"], p["cantidad"]) for p in top] == [("A-1", 2), ("B-1", 2), ("C-1", 1)]
    assert mas_vendidos(VENTAS, "mes", HOY, 1)[0]["sku"] == "A-1"


def test_pedidos_filtra_busca_y_pagina():
    todos = pedidos(VENTAS, search="", estado="todos", producto="todos", page=1, page_size=10)
    assert [f["externalId"] for f in todos["rows"]] == ["3", "1", "2", "4", "5"]
    assert todos["rows"][-1]["productoNombre"] == "Producto C y 1 más"
    assert todos["productos"] == ["Producto A", "Producto B", "Producto C"]
    assert [f["externalId"] for f in pedidos(VENTAS, search="", estado="cancelado", producto="todos", page=1, page_size=10)["rows"]] == ["3"]
    assert [f["externalId"] for f in pedidos(VENTAS, search="b-1", estado="todos", producto="todos", page=1, page_size=10)["rows"]] == ["2", "5"]
    assert [f["externalId"] for f in pedidos(VENTAS, search="", estado="todos", producto="Producto C", page=1, page_size=10)["rows"]] == ["5"]
    pagina = pedidos(VENTAS, search="", estado="todos", producto="todos", page=9, page_size=2)
    assert (pagina["page"], pagina["totalPages"], pagina["total"], len(pagina["rows"])) == (3, 3, 5, 1)


def test_sin_ventas():
    r = resumen_ventas([], HOY)
    assert r["ventasMes"] == 0 and r["ticketPromedioMes"] == 0
    assert pedidos([], search="", estado="todos", producto="todos", page=1, page_size=10) == {"rows": [], "total": 0, "page": 1, "totalPages": 1, "productos": []}
