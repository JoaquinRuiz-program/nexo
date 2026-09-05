"""
Planes por defecto de Nexo y helpers de límites — 5 de septiembre de 2026.

Hasta ahora `plans`/`subscriptions` existían en el modelo (ver
app/db/models/subscriptions.py) pero NINGUNA tienda real tenía una fila de
`Subscription` asignada (ni siquiera la tienda de prueba) — ni el registro
ni ningún otro flujo la creaba. Este módulo es el único lugar que define
"qué planes existen" (nunca hardcodeado en dos lugares distintos) y "qué
hacer cuando una tienda no tiene suscripción todavía" (dato viejo, previo a
este cambio — nunca se rompe una tienda existente por no tener una).

Nombres de estado que usa esta fase (evitando renombrar lo que ya usaba
admin.py y los tests, ver Subscription.status): "trialing", "active",
"past_due", "canceled", "expired" — el pedido original habla de
trial/active/past_due/cancelled/expired; se mantiene el vocabulario que ya
estaba en código (trialing/canceled, con una sola "l") para no forzar una
migración de datos ni tocar comparaciones ya escritas en admin.py.

6 de septiembre de 2026 — precios comerciales reales (ya no "de ejemplo"):
Nexo Básico $80.000 CLP/mes y Nexo Pro $200.000 CLP/mes, definidos por el
dueño. Se sacó el plan "empresarial" de la siembra automática — un tercer
plan a medida (precio a coordinar, sin límites fijos) es una decisión
comercial que todavía no se tomó, no algo que este archivo deba inventar;
queda como recomendación en el reporte, no como código. El campo
`price_demo_label` del modelo sigue llamándose así (columna ya migrada,
renombrarla no aporta nada funcional) pero ahora guarda el precio REAL,
nunca un valor de ejemplo — es lo único que ve el cliente."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MarketplaceAccount, MarketplaceListing, Plan, Product, Store, Subscription

ESTADOS_VALIDOS = ("trialing", "active", "past_due", "canceled", "expired")

DIAS_TRIAL = 14

# Límites configurables (viven en la tabla `plans`, esto solo los siembra
# la primera vez que no existe ninguno — un admin puede editarlos después
# sin tocar código). Pensados para que el salto de $80.000 a $200.000
# tenga una razón real: no es "lo mismo más caro" — Pro multiplica por 5
# el techo de productos/publicaciones (para el vendedor que ya superó el
# catálogo chico) y suma soporte prioritario.
DEFAULT_PLANS = [
    {
        "code": "basico",
        "name": "Nexo Básico",
        "product_limit": 200,
        "publication_limit": 150,
        "price_demo_label": "$80.000 CLP/mes",
        "features": ["Hasta 200 productos", "Hasta 150 publicaciones activas en Mercado Libre", "Conexión con Mercado Libre", "Soporte por email"],
    },
    {
        "code": "pro",
        "name": "Nexo Pro",
        "product_limit": 1000,
        "publication_limit": 800,
        "price_demo_label": "$200.000 CLP/mes",
        "features": ["Hasta 1.000 productos", "Hasta 800 publicaciones activas en Mercado Libre", "Soporte prioritario", "Pensado para catálogos en crecimiento"],
    },
]


def ensure_default_plans(db: Session) -> dict[str, Plan]:
    """Idempotente (mismo criterio que seed_demo.py): crea los planes que
    todavía no existan por `code`, nunca duplica ni pisa uno ya editado a
    mano desde el panel de administrador."""
    planes_por_code = {p.code: p for p in db.query(Plan).all()}
    for datos in DEFAULT_PLANS:
        if datos["code"] in planes_por_code:
            continue
        plan = Plan(**datos)
        db.add(plan)
        planes_por_code[datos["code"]] = plan
    db.flush()
    return planes_por_code


def crear_suscripcion_inicial(db: Session, store: Store, *, ahora: datetime | None = None) -> Subscription:
    """Toda tienda nueva recibe una suscripción trial al plan básico —
    nunca queda una tienda sin suscripción (ver docstring del módulo)."""
    ahora = ahora or datetime.now()
    planes = ensure_default_plans(db)
    plan_inicial = planes.get("basico") or next(iter(planes.values()))
    suscripcion = Subscription(
        store=store,
        plan=plan_inicial,
        status="trialing",
        started_at=ahora,
        current_period_end=(ahora + timedelta(days=DIAS_TRIAL)).date(),
    )
    db.add(suscripcion)
    return suscripcion


def limite_alcanzado(cantidad_actual: int, limite: int | None) -> bool:
    """`None` es "sin límite" en todo el modelo de planes — nunca una
    comparación numérica directa que trate None como 0."""
    return limite is not None and cantidad_actual >= limite


def resumen_suscripcion(db: Session, store: Store) -> dict:
    """Único lugar que arma "plan + estado + uso" de una empresa — lo usan
    tanto GET /api/suscripcion (pantalla "Mi plan") como GET
    /api/dashboard/resumen (para el aviso de "cerca del límite"), para que
    los dos números salgan siempre de la misma cuenta, nunca de dos
    consultas que puedan desincronizarse."""
    sub = store.subscription
    cantidad_productos = db.query(func.count(Product.id)).filter(Product.store_id == store.id).scalar() or 0
    cantidad_publicaciones = (
        db.query(func.count(MarketplaceListing.id))
        .join(MarketplaceAccount)
        .filter(MarketplaceAccount.store_id == store.id, MarketplaceListing.status.in_(["active", "paused"]))
        .scalar()
        or 0
    )
    if sub is None or sub.plan is None:
        # Dato viejo (tienda creada antes de este cambio) — nunca se
        # inventa un plan, se responde honesto en vez de un 500.
        return {
            "plan": None,
            "estado": None,
            "fechaInicio": None,
            "fechaRenovacion": None,
            "uso": {"productos": cantidad_productos, "publicaciones": cantidad_publicaciones},
        }
    return {
        "plan": {
            "codigo": sub.plan.code,
            "nombre": sub.plan.name,
            "limiteProductos": sub.plan.product_limit,
            "limitePublicaciones": sub.plan.publication_limit,
            "precio": sub.plan.price_demo_label,
            "features": sub.plan.features,
        },
        "estado": sub.status,
        "fechaInicio": sub.started_at.isoformat(),
        "fechaRenovacion": sub.current_period_end.isoformat(),
        "uso": {"productos": cantidad_productos, "publicaciones": cantidad_publicaciones},
    }
