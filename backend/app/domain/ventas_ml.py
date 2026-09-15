"""Métricas de ventas de Mercado Libre a partir de las ventas REALES
importadas (tabla `orders`/`order_items`, ver POST /api/mercadolibre/importar-ventas)
— 15 de septiembre de 2026. Antes el Dashboard y la pantalla de Mercado Libre
mostraban $0 fijo en modo real aunque hubiera ventas importadas.

Funciones puras (sin red ni DB). Nunca se inventa un dato: Mercado Libre no
informa en la importación si un pedido fue enviado o entregado, así que esos
contadores quedan en None ("sin datos"), nunca en 0.

Una venta cancelada, o cuyo dinero Mercado Libre devolvió al comprador
(devolución "refunded"), no suma a ingresos, pedidos ni productos vendidos —
mismo criterio que el panel del administrador."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

ESTADO_CANCELADO = "cancelado"
RANGOS = ("7d", "30d", "mes")


@dataclass(frozen=True)
class VentaItem:
    sku: str
    nombre: str
    cantidad: int
    subtotal: float


@dataclass(frozen=True)
class Venta:
    external_id: str
    fecha: datetime
    estado: str
    total: float
    reembolsada: bool = False
    items: list[VentaItem] = field(default_factory=list)

    @property
    def efectiva(self) -> bool:
        return self.estado != ESTADO_CANCELADO and not self.reembolsada

    @property
    def unidades(self) -> int:
        return sum(i.cantidad for i in self.items)


def desde_de_rango(rango: str, hoy: date) -> date:
    if rango == "7d":
        return hoy - timedelta(days=6)
    if rango == "mes":
        return hoy.replace(day=1)
    return hoy - timedelta(days=29)  # "30d" por defecto


def _sumar(ventas: list[Venta]) -> tuple[float, int, int]:
    efectivas = [v for v in ventas if v.efectiva]
    return sum(v.total for v in efectivas), len(efectivas), sum(v.unidades for v in efectivas)


def resumen_ventas(ventas: list[Venta], hoy: date) -> dict:
    ayer = hoy - timedelta(days=1)
    hace7 = hoy - timedelta(days=6)
    ventas_hoy, pedidos_hoy, _ = _sumar([v for v in ventas if v.fecha.date() == hoy])
    ventas_ayer, pedidos_ayer, _ = _sumar([v for v in ventas if v.fecha.date() == ayer])
    ventas_7, pedidos_7, _ = _sumar([v for v in ventas if hace7 <= v.fecha.date() <= hoy])
    ventas_mes, pedidos_mes, unidades_mes = _sumar([v for v in ventas if v.fecha.year == hoy.year and v.fecha.month == hoy.month])
    return {
        "ventasHoy": ventas_hoy, "pedidosHoy": pedidos_hoy,
        "ventasAyer": ventas_ayer, "pedidosAyer": pedidos_ayer,
        "ventasUltimos7Dias": ventas_7, "pedidosUltimos7Dias": pedidos_7,
        "ventasMes": ventas_mes, "pedidosMes": pedidos_mes,
        "productosVendidosMes": unidades_mes,
        "ticketPromedioMes": round(ventas_mes / pedidos_mes) if pedidos_mes else 0,
        # Mercado Libre no informa el envío en la importación: sin datos, nunca 0.
        "pedidosPendientes": None, "pedidosEnviados": None, "pedidosEntregados": None,
        "pedidosCancelados": sum(1 for v in ventas if v.estado == ESTADO_CANCELADO),
    }


def grafico_ventas(ventas: list[Venta], rango: str, hoy: date) -> list[dict]:
    desde = desde_de_rango(rango, hoy)
    por_dia = {desde + timedelta(days=i): [0.0, 0] for i in range((hoy - desde).days + 1)}
    for v in ventas:
        if v.efectiva and v.fecha.date() in por_dia:
            por_dia[v.fecha.date()][0] += v.total
            por_dia[v.fecha.date()][1] += 1
    return [{"fecha": d.isoformat(), "ingresos": ingresos, "pedidos": pedidos} for d, (ingresos, pedidos) in por_dia.items()]


def mas_vendidos(ventas: list[Venta], rango: str, hoy: date, limite: int) -> list[dict]:
    desde = desde_de_rango(rango, hoy)
    por_producto: dict[tuple[str, str], dict] = {}
    for v in ventas:
        if not v.efectiva or not (desde <= v.fecha.date() <= hoy):
            continue
        for item in v.items:
            fila = por_producto.setdefault((item.sku, item.nombre), {"sku": item.sku, "nombre": item.nombre, "cantidad": 0, "ingresos": 0.0})
            fila["cantidad"] += item.cantidad
            fila["ingresos"] += item.subtotal
    return sorted(por_producto.values(), key=lambda f: (-f["cantidad"], -f["ingresos"]))[:limite]


def _nombre_pedido(v: Venta) -> str:
    if not v.items:
        return "Sin ítems"
    if len(v.items) == 1:
        return v.items[0].nombre
    return f"{v.items[0].nombre} y {len(v.items) - 1} más"


def pedidos(ventas: list[Venta], *, search: str, estado: str, producto: str, page: int, page_size: int) -> dict:
    filas = sorted(ventas, key=lambda v: v.fecha, reverse=True)
    if estado != "todos":
        filas = [v for v in filas if v.estado == estado]
    if producto != "todos":
        filas = [v for v in filas if any(i.nombre == producto for i in v.items)]
    q = search.strip().lower()
    if q:
        filas = [v for v in filas if q in v.external_id.lower() or any(q in i.sku.lower() or q in i.nombre.lower() for i in v.items)]
    total = len(filas)
    total_pages = max(1, -(-total // page_size))
    page = min(max(1, page), total_pages)
    inicio = (page - 1) * page_size
    return {
        "rows": [
            {
                "externalId": v.external_id, "productoNombre": _nombre_pedido(v), "sku": v.items[0].sku if v.items else "",
                "cantidad": v.unidades, "total": v.total, "estado": v.estado, "reembolsada": v.reembolsada,
                "fecha": v.fecha.isoformat(),
            }
            for v in filas[inicio: inicio + page_size]
        ],
        "total": total, "page": page, "totalPages": total_pages,
        # Nombres distintos de productos vendidos, para el filtro "Producto".
        "productos": sorted({i.nombre for v in ventas for i in v.items}),
    }
