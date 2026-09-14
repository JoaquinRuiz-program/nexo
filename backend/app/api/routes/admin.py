"""
Panel de administrador de Nexo (dueño de la plataforma) — 30 de agosto de
2026, etapa "preparación para primer cliente real".

Segunda capa de usuario, separada de un cliente normal: un administrador de
Nexo puede ver TODAS las empresas (agregado + lo necesario para soporte).
Un cliente normal jamás llega acá — todo endpoint de este router depende
de `require_nexo_admin` (ver app/api/deps.py), nunca de `get_current_store`
(un admin de Nexo no tiene una "empresa activa" en el sentido de un
cliente).

Regla explícita (pedido del dueño): nunca se muestra ni se expone
access_token/refresh_token/client_secret/contraseñas/password_hash — ni
siquiera acá. Cada función de este archivo arma su propio dict de
respuesta a mano, campo por campo, nunca serializa un modelo completo.

"Estado del cliente" se CALCULA a partir de datos que ya existen — no hay
ninguna columna nueva de estado (decisión confirmada con el dueño, ver
database-architect): Suspendido = User.status == "suspended" (ya existía,
ahora también se aplica en el login, ver auth.py); Trial = existe una
Subscription con status "trialing"; Pendiente de configuración = sin
cuenta de Mercado Libre conectada Y sin ningún producto cargado; Activo =
cualquier otro caso. "Última actividad" se deriva de la sesión más
reciente del usuario dueño (AuthSession.created_at) — no existe ninguna
columna de "last_seen" dedicada, y agregar una requeriría escribir en
cada request; esto alcanza sin ese costo.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_session, require_nexo_admin
from app.domain.admin_overview import PERIODOS, SEVERIDAD_ORDEN, motivos_de_atencion, rango_de_periodo, serie_temporal, variacion_pct
from app.api.routes.productos_db import build_producto_fila
from app.db.models import (
    AdminActionLog,
    AuthSession,
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    Order,
    OrderItem,
    Plan,
    Product,
    ProductVariant,
    Store,
    StoreSettings,
    Subscription,
    SupportTicket,
    User,
)
from app.db.models.support import ESTADOS_VALIDOS as ESTADOS_SOPORTE_VALIDOS
from app.db.session import get_db
from app.domain.plans import ESTADOS_VALIDOS, ensure_default_plans

router = APIRouter(prefix="/api/admin", tags=["admin"])

ESTADO_SUSPENDIDO = "suspendido"
ESTADO_TRIAL = "trial"
ESTADO_PENDIENTE_CONFIGURACION = "pendiente_configuracion"
ESTADO_ACTIVO = "activo"


def _estado_cliente(store: Store, cantidad_productos: int, ml_conectado: bool) -> str:
    if store.owner.status == "suspended":
        return ESTADO_SUSPENDIDO
    if store.subscription is not None and store.subscription.status == "trialing":
        return ESTADO_TRIAL
    if not ml_conectado and cantidad_productos == 0:
        return ESTADO_PENDIENTE_CONFIGURACION
    return ESTADO_ACTIVO


def _ultima_actividad(db: Session, user_id: int) -> datetime | None:
    return db.query(func.max(AuthSession.created_at)).filter(AuthSession.user_id == user_id).scalar()


def _cuenta_ml_de(store: Store) -> MarketplaceAccount | None:
    # Hoy es "mercadolibre" siempre — mismo criterio que el resto del
    # backend (marketplace es texto libre, preparado para otros canales,
    # nunca un enum cerrado a un solo valor).
    return next((c for c in store.marketplace_accounts if c.marketplace == "mercadolibre"), None)


def _registrar_accion_admin(db: Session, admin: User, action: str, *, store_id: int | None = None, detail: str | None = None) -> None:
    """Registro simple de auditoría (6 de septiembre de 2026) — no hace
    commit acá: cuelga del mismo commit que ya hace el endpoint que llama,
    para que la acción y su registro sean atómicos (si uno falla, el otro
    tampoco queda guardado)."""
    db.add(AdminActionLog(admin_user_id=admin.id, store_id=store_id, action=action, detail=detail, created_at=datetime.now()))


@router.get("/clientes")
def listar_clientes(db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)) -> list[dict]:
    """13 de septiembre de 2026 — la empresa propia de un administrador de
    Nexo NO aparece en "Clientes". Antes si aparecia, y quedaba listada como
    un cliente mas siendo que la mitad de las acciones del panel la rechazan
    (entrar_a_ver_empresa responde 400 sobre la cuenta de un admin). El
    administrador figura en la pestana "Usuarios" con su rol; para ver su
    propia empresa entra a su cuenta como cualquier otro usuario."""
    tiendas = (
        db.query(Store)
        .join(User, Store.owner_user_id == User.id)
        .filter(User.is_nexo_admin.is_(False))
        .order_by(Store.created_at.desc())
        .all()
    )
    filas = []
    for tienda in tiendas:
        cantidad_productos = db.query(func.count(Product.id)).filter(Product.store_id == tienda.id).scalar() or 0
        cuenta_ml = _cuenta_ml_de(tienda)
        ml_conectado = cuenta_ml is not None and cuenta_ml.status == "connected"
        filas.append({
            "storeId": tienda.id,
            "nombre": tienda.name,
            "usuarioPrincipal": {"id": tienda.owner.id, "email": tienda.owner.email, "nombre": tienda.owner.full_name},
            "fechaRegistro": tienda.created_at.isoformat(),
            "estado": _estado_cliente(tienda, cantidad_productos, ml_conectado),
            "mercadoLibreConectado": ml_conectado,
            "cantidadProductos": cantidad_productos,
            "ultimaActividad": (lambda ts: ts.isoformat() if ts else None)(_ultima_actividad(db, tienda.owner_user_id)),
            "plan": tienda.subscription.plan.name if (tienda.subscription and tienda.subscription.plan) else None,
        })
    return filas


# ------------------------------------------------------------------
# Overview / Business Intelligence global (14 de septiembre de 2026).
# GLOBAL a toda la plataforma, SOLO para is_nexo_admin (require_nexo_admin) —
# nunca scopeado a una empresa desde afuera; el aislamiento multiempresa se
# mantiene porque un admin de EMPRESA jamás llega a este router. Todas las
# cifras salen de datos reales; sin datos, 0 o null (nunca inventadas).
# ------------------------------------------------------------------

CANALES_OVERVIEW = ("todos", "mercadolibre")
# Una venta cancelada no es una venta: nunca suma al GMV ni al margen.
_ESTADOS_VENTA_EXCLUIDOS = ("cancelado",)
_MAX_EMPRESAS_PIE = 6  # más que esto se agrupan en "Otros" para que el pie siga legible


def _ids_empresas_cliente(db: Session) -> list[int]:
    """store_id de las EMPRESAS CLIENTE (dueño no-admin). La empresa propia de
    un admin de Nexo nunca entra en las métricas de negocio."""
    return [sid for (sid,) in db.query(Store.id).join(User, Store.owner_user_id == User.id).filter(User.is_nexo_admin.is_(False)).all()]


def _filtros_orden(ids_cliente: list[int], desde: date | None, hasta: date, empresa_id: int | None, canal: str) -> list:
    hasta_dt = datetime.combine(hasta + timedelta(days=1), time.min)  # fin exclusivo (todo el día `hasta`)
    filtros = [Order.store_id.in_(ids_cliente), Order.status.notin_(_ESTADOS_VENTA_EXCLUIDOS), Order.order_date < hasta_dt]
    if desde is not None:
        filtros.append(Order.order_date >= datetime.combine(desde, time.min))
    if empresa_id is not None:
        filtros.append(Order.store_id == empresa_id)
    if canal and canal != "todos":
        filtros.append(Order.channel == canal)
    return filtros


def _metricas_ventas(db: Session, filtros: list) -> dict:
    """GMV, comisiones, costos, margen y unidades de un conjunto de órdenes.
    `costos` solo suma los ítems con costo conocido; `itemsSinCosto` cuenta los
    que no lo tienen, para que el frontend pueda avisar que el margen es
    parcial en vez de mostrarlo como si fuera exacto."""
    gmv, num = db.query(func.coalesce(func.sum(Order.total_amount), 0.0), func.count(Order.id)).filter(*filtros).one()
    comisiones = db.query(func.coalesce(func.sum(Order.commission_amount), 0.0)).filter(*filtros).scalar() or 0.0

    item_rows = (
        db.query(OrderItem.quantity, ProductVariant.cost_price)
        .join(Order, OrderItem.order_id == Order.id)
        .outerjoin(ProductVariant, OrderItem.variant_id == ProductVariant.id)
        .filter(*filtros)
        .all()
    )
    unidades = sum(q or 0 for q, _ in item_rows)
    costos = 0.0
    items_sin_costo = 0
    for q, cost in item_rows:
        if cost is None:
            items_sin_costo += 1
        else:
            costos += float(cost) * (q or 0)

    gmv_f = float(gmv or 0.0)
    margen = gmv_f - float(comisiones) - costos
    return {
        "gmv": round(gmv_f, 2),
        "ventas": int(num or 0),
        "comisiones": round(float(comisiones), 2),
        "costos": round(costos, 2),
        "margen": round(margen, 2) if num else 0.0,
        "unidades": int(unidades),
        "itemsSinCosto": items_sin_costo,
    }


@router.get("/overview")
def overview(
    periodo: str = Query("30d"),
    empresa: int | None = Query(None, description="store_id de una empresa, o vacío = todas"),
    canal: str = Query("todos"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_nexo_admin),
) -> dict:
    """Panel de Business Intelligence del admin de Nexo. Un único endpoint que
    devuelve todo lo que pinta el Overview, ya filtrado por período/empresa/
    canal — para que el frontend no tenga que orquestar N llamadas."""
    if periodo not in PERIODOS:
        raise HTTPException(status_code=400, detail=f"Período inválido. Usá uno de: {', '.join(PERIODOS)}.")
    if canal not in CANALES_OVERVIEW:
        raise HTTPException(status_code=400, detail=f"Canal inválido. Usá uno de: {', '.join(CANALES_OVERVIEW)}.")

    hoy = date.today()
    rango = rango_de_periodo(periodo, hoy)
    ids_cliente = _ids_empresas_cliente(db)

    # Filtro de empresa: solo vale si es una empresa cliente real.
    empresa_id = empresa if (empresa is not None and empresa in ids_cliente) else None

    if not ids_cliente:
        # Plataforma sin ninguna empresa cliente todavía — todo en cero, honesto.
        return {
            "periodo": periodo, "canal": canal, "empresa": empresa_id,
            "generadoEn": datetime.now().isoformat(),
            "kpis": {}, "ventasPorEmpresa": [], "ventasEnElTiempo": [], "margenEnElTiempo": [], "margenEnElTiempoParcial": False,
            "topEmpresas": [], "mercadoLibre": {}, "crecimiento": {}, "atencion": [], "hayEmpresas": False,
        }

    filtros = _filtros_orden(ids_cliente, rango.desde, rango.hasta, empresa_id, canal)
    filtros_prev = (
        _filtros_orden(ids_cliente, rango.desde_prev, rango.hasta_prev, empresa_id, canal)
        if rango.desde_prev is not None
        else None
    )

    m = _metricas_ventas(db, filtros)
    m_prev = _metricas_ventas(db, filtros_prev) if filtros_prev else None

    # -------- KPIs --------
    empresas_scope = [empresa_id] if empresa_id is not None else ids_cliente
    productos_gestionados = db.query(func.count(Product.id)).filter(Product.store_id.in_(empresas_scope)).scalar() or 0
    publicaciones_activas = (
        db.query(func.count(MarketplaceListing.id))
        .join(MarketplaceAccount, MarketplaceListing.account_id == MarketplaceAccount.id)
        .filter(MarketplaceAccount.store_id.in_(empresas_scope), MarketplaceListing.status == "active")
        .scalar()
        or 0
    )
    # Empresas activas: cliente no suspendido (User.status != suspended).
    empresas_activas = (
        db.query(func.count(Store.id))
        .join(User, Store.owner_user_id == User.id)
        .filter(Store.id.in_(empresas_scope), User.status != "suspended")
        .scalar()
        or 0
    )
    # Usuarios activos: los que iniciaron sesión dentro del período (dato real,
    # de AuthSession) — null si el período no tiene límite inferior ("todo").
    if rango.desde is not None:
        usuarios_activos = (
            db.query(func.count(func.distinct(AuthSession.user_id)))
            .filter(AuthSession.created_at >= datetime.combine(rango.desde, time.min))
            .scalar()
            or 0
        )
    else:
        usuarios_activos = db.query(func.count(func.distinct(AuthSession.user_id))).scalar() or 0

    margen_pct = round(m["margen"] / m["gmv"] * 100.0, 1) if m["gmv"] > 0 else None

    kpis = {
        "gmv": {"valor": m["gmv"], "variacionPct": variacion_pct(m["gmv"], m_prev["gmv"]) if m_prev else None},
        "margenGenerado": {"valor": m["margen"], "variacionPct": variacion_pct(m["margen"], m_prev["margen"]) if m_prev and m_prev["margen"] else None, "parcial": m["itemsSinCosto"] > 0},
        "margenPromedioPct": margen_pct,
        "ventas": {"valor": m["ventas"], "variacionPct": variacion_pct(m["ventas"], m_prev["ventas"]) if m_prev else None},
        "unidades": m["unidades"],
        "empresasActivas": int(empresas_activas),
        "productosGestionados": int(productos_gestionados),
        "publicacionesActivas": int(publicaciones_activas),
        "usuariosActivos": int(usuarios_activos),
    }

    # -------- Ventas por empresa (pie) --------
    por_empresa = (
        db.query(Order.store_id, Store.name, func.coalesce(func.sum(Order.total_amount), 0.0), func.count(Order.id))
        .join(Store, Store.id == Order.store_id)
        .filter(*filtros)
        .group_by(Order.store_id, Store.name)
        .all()
    )
    por_empresa = sorted(por_empresa, key=lambda r: float(r[2]), reverse=True)
    total_ventas = sum(float(r[2]) for r in por_empresa) or 0.0
    ventas_por_empresa: list[dict] = []
    for store_id, nombre, monto, cnt in por_empresa[:_MAX_EMPRESAS_PIE]:
        ventas_por_empresa.append({
            "storeId": store_id, "nombre": nombre, "monto": round(float(monto), 2),
            "pct": round(float(monto) / total_ventas * 100.0, 1) if total_ventas else 0.0, "cantidadVentas": int(cnt),
        })
    resto = por_empresa[_MAX_EMPRESAS_PIE:]
    if resto:
        monto_resto = sum(float(r[2]) for r in resto)
        ventas_por_empresa.append({
            "storeId": None, "nombre": f"Otros ({len(resto)})", "monto": round(monto_resto, 2),
            "pct": round(monto_resto / total_ventas * 100.0, 1) if total_ventas else 0.0,
            "cantidadVentas": sum(int(r[3]) for r in resto),
        })

    # -------- Ventas en el tiempo (línea) --------
    puntos = [(o.order_date.date(), float(o.total_amount or 0.0)) for o in db.query(Order).filter(*filtros).all()]
    ventas_en_el_tiempo = serie_temporal(puntos, rango.desde, rango.hasta, rango.granularidad)

    # -------- Margen en el tiempo (línea) --------
    # Mismo cálculo que el KPI margenGenerado (_metricas_ventas): venta -
    # comisión - costo de los ítems con costo conocido, por orden. Si algún
    # ítem vendido no tiene costo, la serie es parcial (igual que el KPI).
    costo_por_orden: dict[int, float] = {}
    for order_id, cantidad, costo in (
        db.query(OrderItem.order_id, OrderItem.quantity, ProductVariant.cost_price)
        .join(Order, OrderItem.order_id == Order.id)
        .outerjoin(ProductVariant, OrderItem.variant_id == ProductVariant.id)
        .filter(*filtros)
        .all()
    ):
        if costo is not None:
            costo_por_orden[order_id] = costo_por_orden.get(order_id, 0.0) + float(costo) * (cantidad or 0)
    puntos_margen = [
        (fecha.date(), float(total or 0.0) - float(comision or 0.0) - costo_por_orden.get(order_id, 0.0))
        for order_id, fecha, total, comision in db.query(Order.id, Order.order_date, Order.total_amount, Order.commission_amount).filter(*filtros).all()
    ]
    margen_en_el_tiempo = serie_temporal(puntos_margen, rango.desde, rango.hasta, rango.granularidad)

    # -------- Top empresas (ranking) --------
    top_empresas = _top_empresas(db, ids_cliente, rango, empresa_id, canal)

    # -------- Analytics Mercado Libre --------
    mercado_libre = _analytics_mercadolibre(db, ids_cliente, rango, empresa_id, empresas_scope)

    # -------- Crecimiento SaaS --------
    crecimiento = _crecimiento_saas(db, ids_cliente, hoy)

    return {
        "periodo": periodo, "canal": canal, "empresa": empresa_id,
        "granularidad": rango.granularidad,
        "generadoEn": datetime.now().isoformat(),
        "hayEmpresas": True,
        "kpis": kpis,
        "ventasPorEmpresa": ventas_por_empresa,
        "ventasEnElTiempo": ventas_en_el_tiempo,
        "margenEnElTiempo": margen_en_el_tiempo,
        "margenEnElTiempoParcial": m["itemsSinCosto"] > 0,
        "topEmpresas": top_empresas,
        "mercadoLibre": mercado_libre,
        "crecimiento": crecimiento,
        "atencion": _clientes_que_necesitan_atencion(db, empresas_scope, hoy),
    }


# Una solicitud de soporte "sin resolver" todavía espera algo del admin.
_ESTADOS_TICKET_SIN_RESOLVER = ("abierto", "en_revision")


def _clientes_que_necesitan_atencion(db: Session, empresas_scope: list[int], hoy: date) -> list[dict]:
    """Empresas cliente con algún motivo real para que el admin las mire
    (ver admin_overview.motivos_de_atencion). Un cliente suspendido queda
    afuera: el admin ya actuó sobre él. Las más urgentes primero."""
    productos = {sid: int(c) for sid, c in
                 db.query(Product.store_id, func.count(Product.id)).filter(Product.store_id.in_(empresas_scope)).group_by(Product.store_id).all()}
    tickets = {sid: int(c) for sid, c in
               db.query(SupportTicket.store_id, func.count(SupportTicket.id))
               .filter(SupportTicket.store_id.in_(empresas_scope), SupportTicket.status.in_(_ESTADOS_TICKET_SIN_RESOLVER))
               .group_by(SupportTicket.store_id).all()}
    tiendas = (
        db.query(Store).join(User, Store.owner_user_id == User.id)
        .filter(Store.id.in_(empresas_scope), User.status != "suspended").all()
    )
    filas = []
    for tienda in tiendas:
        sub = tienda.subscription
        cuenta_ml = _cuenta_ml_de(tienda)
        motivos = motivos_de_atencion(
            sub_status=sub.status if sub else None,
            current_period_end=sub.current_period_end if sub else None,
            ml_status=cuenta_ml.status if cuenta_ml else None,
            cantidad_productos=productos.get(tienda.id, 0),
            tickets_sin_resolver=tickets.get(tienda.id, 0),
            hoy=hoy,
        )
        if motivos:
            severidad = min((m["severidad"] for m in motivos), key=SEVERIDAD_ORDEN.__getitem__)
            filas.append({"storeId": tienda.id, "nombre": tienda.name, "severidad": severidad, "motivos": motivos})
    filas.sort(key=lambda f: (SEVERIDAD_ORDEN[f["severidad"]], -len(f["motivos"]), f["nombre"]))
    return filas


def _top_empresas(db: Session, ids_cliente: list[int], rango, empresa_id: int | None, canal: str) -> list[dict]:
    """Una fila por empresa cliente con sus métricas del período — el frontend
    ordena por la columna que elija el admin. Empresas sin ventas se incluyen
    igual (en 0): "no vendió nada" también es información."""
    scope = [empresa_id] if empresa_id is not None else ids_cliente
    filtros = _filtros_orden(ids_cliente, rango.desde, rango.hasta, empresa_id, canal)
    filtros_prev = (
        _filtros_orden(ids_cliente, rango.desde_prev, rango.hasta_prev, empresa_id, canal) if rango.desde_prev is not None else None
    )

    # Ventas y cantidad por empresa (período actual y previo).
    ventas_act = {sid: (float(g or 0), int(c or 0)) for sid, g, c in
                  db.query(Order.store_id, func.sum(Order.total_amount), func.count(Order.id)).filter(*filtros).group_by(Order.store_id).all()}
    ventas_prev = {}
    if filtros_prev:
        ventas_prev = {sid: float(g or 0) for sid, g in
                       db.query(Order.store_id, func.sum(Order.total_amount)).filter(*filtros_prev).group_by(Order.store_id).all()}

    # Comisiones por empresa (nivel orden) y costos por empresa (nivel ítem,
    # solo los que tienen costo conocido). Margen = venta - comisión - costo.
    comisiones_emp = {sid: float(c or 0) for sid, c in
                      db.query(Order.store_id, func.sum(Order.commission_amount)).filter(*filtros).group_by(Order.store_id).all()}
    costos_emp: dict[int, float] = {}
    for sid, qty, cost in (
        db.query(Order.store_id, OrderItem.quantity, ProductVariant.cost_price)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(ProductVariant, OrderItem.variant_id == ProductVariant.id)  # inner: solo ítems con costo real
        .filter(*filtros)
        .all()
    ):
        if cost is not None:
            costos_emp[sid] = costos_emp.get(sid, 0.0) + float(cost) * (qty or 0)

    # Productos y publicaciones activas por empresa.
    productos = {sid: int(c) for sid, c in db.query(Product.store_id, func.count(Product.id)).filter(Product.store_id.in_(scope)).group_by(Product.store_id).all()}
    pubs = {sid: int(c) for sid, c in
            db.query(MarketplaceAccount.store_id, func.count(MarketplaceListing.id))
            .join(MarketplaceListing, MarketplaceListing.account_id == MarketplaceAccount.id)
            .filter(MarketplaceAccount.store_id.in_(scope), MarketplaceListing.status == "active")
            .group_by(MarketplaceAccount.store_id).all()}

    nombres = {sid: nombre for sid, nombre in db.query(Store.id, Store.name).filter(Store.id.in_(scope)).all()}

    filas = []
    for sid in scope:
        gmv, cnt = ventas_act.get(sid, (0.0, 0))
        prev = ventas_prev.get(sid, 0.0)
        margen = round(gmv - comisiones_emp.get(sid, 0.0) - costos_emp.get(sid, 0.0), 2) if cnt else 0.0
        filas.append({
            "storeId": sid,
            "nombre": nombres.get(sid, f"Empresa {sid}"),
            "ventas": round(gmv, 2),
            "margen": margen,
            "cantidadVentas": cnt,
            "productos": productos.get(sid, 0),
            "publicaciones": pubs.get(sid, 0),
            "crecimientoPct": variacion_pct(gmv, prev),
        })
    filas.sort(key=lambda f: f["ventas"], reverse=True)
    return filas


def _analytics_mercadolibre(db: Session, ids_cliente: list[int], rango, empresa_id: int | None, empresas_scope: list[int]) -> dict:
    """Sección Mercado Libre — siempre sobre el canal ML, sin importar el
    filtro de canal general (esta sección ES Mercado Libre)."""
    filtros_ml = _filtros_orden(ids_cliente, rango.desde, rango.hasta, empresa_id, "mercadolibre")
    m = _metricas_ventas(db, filtros_ml)

    activas = (
        db.query(func.count(MarketplaceListing.id))
        .join(MarketplaceAccount, MarketplaceListing.account_id == MarketplaceAccount.id)
        .filter(MarketplaceAccount.store_id.in_(empresas_scope), MarketplaceListing.status == "active").scalar() or 0
    )
    pausadas = (
        db.query(func.count(MarketplaceListing.id))
        .join(MarketplaceAccount, MarketplaceListing.account_id == MarketplaceAccount.id)
        .filter(MarketplaceAccount.store_id.in_(empresas_scope), MarketplaceListing.status == "paused").scalar() or 0
    )
    cuentas = db.query(MarketplaceAccount).filter(MarketplaceAccount.store_id.in_(empresas_scope), MarketplaceAccount.marketplace == "mercadolibre").all()
    conectadas = sum(1 for c in cuentas if c.status == "connected")
    con_error = sum(1 for c in cuentas if c.status in ("error", "token_expired"))
    ultimas = [c.last_checked_at for c in cuentas if c.last_checked_at is not None]
    ultima_sync = max(ultimas).isoformat() if ultimas else None

    return {
        "gmv": m["gmv"], "ventas": m["ventas"], "unidades": m["unidades"],
        "comisiones": m["comisiones"], "margen": m["margen"], "margenParcial": m["itemsSinCosto"] > 0,
        "publicacionesActivas": int(activas), "publicacionesPausadas": int(pausadas),
        "empresasConectadas": conectadas, "empresasConError": con_error,
        "ultimaSincronizacion": ultima_sync,
    }


def _crecimiento_saas(db: Session, ids_cliente: list[int], hoy: date) -> dict:
    """Cómo crece Nexo como plataforma: altas de empresas por mes (últimos 12)
    y suscripciones por estado. Datos reales de Store/Subscription."""
    desde = (hoy.replace(day=1) - timedelta(days=330)).replace(day=1)
    altas = [(s.created_at.date(), 1.0) for s in db.query(Store).filter(Store.id.in_(ids_cliente), Store.created_at >= datetime.combine(desde, time.min)).all()]
    nuevas_por_mes = serie_temporal(altas, desde, hoy, "mes")

    subs_por_estado: dict[str, int] = {}
    for estado, cnt in db.query(Subscription.status, func.count(Subscription.id)).join(Store, Subscription.store_id == Store.id).filter(Store.id.in_(ids_cliente)).group_by(Subscription.status).all():
        subs_por_estado[estado] = int(cnt)

    return {
        "totalEmpresas": len(ids_cliente),
        "nuevasEmpresasPorMes": nuevas_por_mes,
        "suscripcionesPorEstado": subs_por_estado,
    }


@router.get("/usuarios")
def listar_usuarios(db: Session = Depends(get_db), admin: User = Depends(require_nexo_admin)) -> list[dict]:
    """Vista cruzada de usuarios (segunda pestaña del panel, pedida aparte
    de "Clientes" — hoy son casi la misma información porque cada tienda
    tiene un único dueño, pero se arma como su propia consulta para no
    tener que cambiar de forma el día que exista "varios usuarios por
    tienda"). Nunca incluye password_hash."""
    usuarios = db.query(User).order_by(User.created_at.desc()).all()
    filas = []
    for u in usuarios:
        tienda = u.stores[0] if u.stores else None
        filas.append({
            "id": u.id,
            "email": u.email,
            "nombre": u.full_name,
            "esNexoAdmin": u.is_nexo_admin,
            # Para que el panel no ofrezca quitarse el rol a uno mismo.
            "esVos": u.id == admin.id,
            "estadoCuenta": u.status,
            "creadoEn": u.created_at.isoformat(),
            "empresa": None if tienda is None else {"storeId": tienda.id, "nombre": tienda.name},
        })
    return filas


class RolAdministradorUpdate(BaseModel):
    esAdmin: bool


@router.put("/usuarios/{user_id}/administrador")
def cambiar_rol_administrador(
    user_id: int,
    body: RolAdministradorUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_nexo_admin),
) -> dict:
    """Dar o quitar el rol de administrador de Nexo — 13 de septiembre de 2026.

    Hasta hoy `is_nexo_admin` solo se otorgaba a mano contra la base de
    datos, a proposito: no habia ningun endpoint que pudiera escalar
    privilegios. Se abre ahora porque el dueno necesita sumar a otra persona
    a administrar la plataforma sin tocar SQL. Las barreras que lo hacen
    seguro:

    - solo un administrador existente puede llamarlo (require_nexo_admin);
    - NADIE puede cambiar su propio rol: ni auto-degradarse (y perder el
      panel por accidente) ni tocarse a si mismo;
    - nunca se puede quitar el ultimo administrador que queda, aunque lo
      intente otro admin: Nexo quedaria sin nadie que pueda administrarlo;
    - queda registrado en AdminActionLog, igual que suspender o ver una
      empresa.

    Quitar el rol tiene efecto inmediato: `require_nexo_admin` y
    `store_en_vista_de_admin` (app/api/deps.py) leen el flag en cada
    request, asi que si esa persona estaba viendo la cuenta de un cliente,
    pierde el acceso en la request siguiente sin tener que cerrarle la
    sesion.

    Dar el rol a alguien que tiene empresa propia hace que esa empresa deje
    de aparecer en "Clientes" (ver listar_clientes) — es coherente: pasa a
    ser parte de Nexo, no un cliente."""
    usuario = db.get(User, user_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if usuario.id == admin.id:
        raise HTTPException(status_code=400, detail="No podés cambiar tu propio rol de administrador.")

    if not body.esAdmin and usuario.is_nexo_admin:
        otros_admins = (
            db.query(func.count(User.id))
            .filter(User.is_nexo_admin.is_(True), User.id != usuario.id)
            .scalar()
            or 0
        )
        if otros_admins == 0:
            raise HTTPException(status_code=400, detail="No podés quitar el último administrador de Nexo.")

    usuario.is_nexo_admin = body.esAdmin
    usuario.updated_at = datetime.now()
    _registrar_accion_admin(
        db, admin,
        "dar_rol_administrador" if body.esAdmin else "quitar_rol_administrador",
        detail=f"{'Dio' if body.esAdmin else 'Quitó'} el rol de administrador a {usuario.email}",
    )
    db.commit()
    return {"id": usuario.id, "email": usuario.email, "esNexoAdmin": usuario.is_nexo_admin}


@router.get("/clientes/{store_id}")
def detalle_cliente(store_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)) -> dict:
    tienda = db.get(Store, store_id)
    if tienda is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    cantidad_productos = db.query(func.count(Product.id)).filter(Product.store_id == tienda.id).scalar() or 0
    cuenta_ml = _cuenta_ml_de(tienda)
    ml_conectado = cuenta_ml is not None and cuenta_ml.status == "connected"

    publicaciones = db.query(MarketplaceListing).join(MarketplaceAccount).filter(MarketplaceAccount.store_id == tienda.id).all()
    publicaciones_por_estado: dict[str, int] = {}
    for pub in publicaciones:
        publicaciones_por_estado[pub.status] = publicaciones_por_estado.get(pub.status, 0) + 1

    canales_costos = db.query(ChannelCostSettings).filter_by(store_id=tienda.id).all()

    # 6 de septiembre de 2026 — perfil de empresa completo para el admin
    # (auditoría comercial): antes solo había un conteo de productos y de
    # publicaciones por estado, sin la lista real de ninguno de los dos, y
    # sin ningún dato de soporte acá. Reutiliza build_producto_fila
    # (mismo que ve el propio cliente en /api/productos) y
    # _fila_soporte_admin (mismo que la vista global de Soporte) — nunca
    # se duplica la lógica de armar esas filas.
    pares_producto_variante = (
        db.query(Product, ProductVariant)
        .join(ProductVariant, ProductVariant.product_id == Product.id)
        .filter(Product.store_id == tienda.id)
        .order_by(Product.name)
        .limit(200)
        .all()
    )
    filas_productos = [build_producto_fila(p, v) for p, v in pares_producto_variante]

    filas_publicaciones = [{
        "id": pub.id,
        "producto": pub.product.name if pub.product else None,
        "externalListingId": pub.external_listing_id,
        "status": pub.status,
        "precio": float(pub.price) if pub.price is not None else None,
    } for pub in publicaciones]

    tickets_soporte = db.query(SupportTicket).filter_by(store_id=tienda.id).order_by(SupportTicket.created_at.desc()).all()
    tickets_abiertos = sum(1 for t in tickets_soporte if t.status in ("abierto", "en_revision"))

    ultimas_sesiones = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == tienda.owner_user_id)
        .order_by(AuthSession.created_at.desc())
        .limit(5)
        .all()
    )

    settings_tienda = db.query(StoreSettings).filter_by(store_id=tienda.id).first()

    acciones_admin = (
        db.query(AdminActionLog)
        .filter_by(store_id=tienda.id)
        .order_by(AdminActionLog.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "storeId": tienda.id,
        "nombre": tienda.name,
        "fechaRegistro": tienda.created_at.isoformat(),
        "moneda": tienda.currency,
        "zonaHoraria": tienda.timezone,
        "estado": _estado_cliente(tienda, cantidad_productos, ml_conectado),
        # Hoy siempre es un único dueño (ver docstring de Store) — se
        # devuelve como lista para no tener que cambiar la forma de la
        # respuesta el día que exista "varios usuarios por tienda".
        "usuarios": [{
            "id": tienda.owner.id, "email": tienda.owner.email, "nombre": tienda.owner.full_name,
            "estadoCuenta": tienda.owner.status, "creadoEn": tienda.owner.created_at.isoformat(),
        }],
        "configuracion": {
            "nombreEmpresa": settings_tienda.company_name if settings_tienda else None,
            "nombreTienda": settings_tienda.store_name if settings_tienda else None,
        },
        "productos": {"cantidad": cantidad_productos, "filas": filas_productos},
        "publicaciones": {"total": len(publicaciones), "porEstado": publicaciones_por_estado, "filas": filas_publicaciones},
        "soporte": {
            "ticketsAbiertos": tickets_abiertos,
            "solicitudes": [_fila_soporte_admin(t) for t in tickets_soporte],
        },
        "cantidadUsuarios": 1,  # ver comentario de "usuarios" más arriba
        "mercadoLibre": None if cuenta_ml is None else {
            # Nunca access_token_encrypted/refresh_token_encrypted — ni
            # siquiera el hecho de que existan como campo en la respuesta.
            "estado": cuenta_ml.status,
            "nickname": cuenta_ml.external_account_nickname,
            "siteId": cuenta_ml.external_account_site_id,
            "conectadoEn": cuenta_ml.connected_at.isoformat() if cuenta_ml.connected_at else None,
            "ultimaSincronizacion": cuenta_ml.last_checked_at.isoformat() if cuenta_ml.last_checked_at else None,
        },
        "costosConfigurados": [{
            "canal": c.channel,
            "comisionPct": float(c.commission_pct) if c.commission_pct is not None else None,
            "margenObjetivoPct": float(c.target_margin_pct) if c.target_margin_pct is not None else None,
            "margenMinimoPct": float(c.min_margin_pct) if c.min_margin_pct is not None else None,
        } for c in canales_costos],
        "plan": (
            {"codigo": tienda.subscription.plan.code, "nombre": tienda.subscription.plan.name, "estado": tienda.subscription.status}
            if (tienda.subscription and tienda.subscription.plan) else None
        ),
        "actividadReciente": [{"fecha": s.created_at.isoformat()} for s in ultimas_sesiones],
        "accionesAdministrativas": [{
            "admin": a.admin_user.email, "accion": a.action, "detalle": a.detail, "fecha": a.created_at.isoformat(),
        } for a in acciones_admin],
        # No existe todavía ningún mecanismo de log de errores por tienda
        # (los errores de publicación/ML solo llegan a los logs del
        # servidor) — nunca se inventa un valor acá, se deja explícito.
        "erroresRecientes": None,
    }


class ActualizarEstadoClienteRequest(BaseModel):
    suspendido: bool


@router.put("/clientes/{store_id}/estado")
def actualizar_estado_cliente(
    store_id: int, body: ActualizarEstadoClienteRequest, db: Session = Depends(get_db), admin: User = Depends(require_nexo_admin)
) -> dict:
    """Suspender/reactivar una cuenta — el único cambio que este panel
    puede hacer sobre un cliente (nada de precios/stock/productos/
    publicaciones, que siguen siendo responsabilidad exclusiva del
    dueño de esa empresa)."""
    tienda = db.get(Store, store_id)
    if tienda is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    tienda.owner.status = "suspended" if body.suspendido else "active"
    tienda.owner.updated_at = datetime.now()
    _registrar_accion_admin(db, admin, "suspender" if body.suspendido else "reactivar", store_id=tienda.id)
    db.commit()
    cantidad_productos = db.query(func.count(Product.id)).filter(Product.store_id == tienda.id).scalar() or 0
    cuenta_ml = _cuenta_ml_de(tienda)
    ml_conectado = cuenta_ml is not None and cuenta_ml.status == "connected"
    return {"storeId": tienda.id, "estado": _estado_cliente(tienda, cantidad_productos, ml_conectado)}


@router.post("/clientes/{store_id}/entrar")
def entrar_a_ver_empresa(
    store_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_nexo_admin),
    sesion: AuthSession = Depends(get_current_session),
) -> dict:
    """"Ver como empresa" — para que un administrador de Nexo pueda ver y
    operar la aplicación EXACTAMENTE como la ve ese cliente (necesario para
    dar soporte real, ej. reproducir un error puntual) sin pedirle la
    contraseña ni que el cliente comparta su sesión.

    6 de septiembre de 2026 — esto NO crea una sesión nueva ni toca la
    cookie del navegador. Marca un CONTEXTO en la sesión del propio admin
    (`AuthSession.viewing_store_id`), y la sesión del admin sigue siendo la
    misma de siempre: mismo `user_id`, misma cookie, misma expiración.
    Consecuencias, todas buscadas:

    - el usuario autenticado sigue siendo el admin (nunca se "convierte" en
      el cliente, ni siquiera parcialmente: `get_current_user` no cambia);
    - sobrevive a un refresh y a cerrar/reabrir la pestaña, porque el
      contexto vive en el servidor, no en el navegador;
    - salir (POST /api/admin/ver-como/salir) es volver la columna a NULL:
      el admin queda exactamente donde estaba, autenticado, sin volver a
      pasar por /login;
    - `require_nexo_admin` sigue dando acceso al panel mientras dura, así
      que "salir y volver al panel" nunca depende de un login nuevo.

    Antes esto sí creaba una sesión del usuario cliente y pisaba la cookie
    del admin (impersonación real): eso deslogueaba al admin y era, además,
    un mecanismo de impersonación completo viviendo en el producto. Se
    reemplazó a propósito.

    Nunca es silencioso: queda registrado en AdminActionLog (quién, cuándo,
    a qué empresa — mismo mecanismo que suspender/cambiar plan) y
    GET /api/auth/me lo expone, así el frontend muestra un aviso
    persistente mientras dure."""
    tienda = db.get(Store, store_id)
    if tienda is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    if tienda.owner.is_nexo_admin:
        # Nunca se puede entrar a ver la empresa de OTRO administrador de
        # Nexo — esto es para dar soporte a clientes, no para que un admin
        # mire los datos de otro.
        raise HTTPException(status_code=400, detail="No se puede entrar a la cuenta de un administrador.")

    sesion.viewing_store_id = tienda.id
    _registrar_accion_admin(db, admin, "entrar_como_soporte", store_id=tienda.id, detail=f"Entró a ver la cuenta de {tienda.owner.email}")
    db.commit()

    return {"ok": True, "empresa": {"id": tienda.id, "nombre": tienda.name}}


@router.post("/ver-como/salir")
def salir_de_ver_empresa(
    db: Session = Depends(get_db),
    admin: User = Depends(require_nexo_admin),
    sesion: AuthSession = Depends(get_current_session),
) -> dict:
    """Salir del modo "ver como empresa" — devuelve al admin a su propio
    contexto SIN cerrar su sesión (la cookie no se toca; ver
    entrar_a_ver_empresa). Idempotente: salir cuando no se estaba viendo
    ninguna empresa no es un error."""
    store_id = sesion.viewing_store_id
    if store_id is not None:
        sesion.viewing_store_id = None
        _registrar_accion_admin(db, admin, "salir_de_ver_empresa", store_id=store_id)
    db.commit()
    return {"ok": True}


@router.get("/planes")
def listar_planes(db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)) -> list[dict]:
    """Planes disponibles para asignar manualmente — siembra los 3 planes
    por defecto la primera vez que no existe ninguno (ver app/domain/plans.py)."""
    planes = list(ensure_default_plans(db).values())
    db.commit()
    return [{
        "codigo": p.code, "nombre": p.name, "limiteProductos": p.product_limit,
        "limitePublicaciones": p.publication_limit, "precio": p.price_demo_label, "activo": p.is_active,
    } for p in sorted(planes, key=lambda p: p.id)]


class ActualizarSuscripcionRequest(BaseModel):
    planCode: str | None = None
    estado: str | None = None


@router.put("/clientes/{store_id}/suscripcion")
def actualizar_suscripcion_cliente(
    store_id: int, body: ActualizarSuscripcionRequest, db: Session = Depends(get_db), admin: User = Depends(require_nexo_admin)
) -> dict:
    """Cambio manual de plan/estado — mientras no exista un proveedor de
    pago real conectado, ÚNICO lugar de todo el backend que puede modificar
    una Subscription (nunca el propio cliente, ver app/api/routes/suscripcion.py).

    6 de septiembre de 2026 — hallazgo de la auditoría comercial: una
    empresa creada ANTES de que existiera el sistema de planes (dato viejo,
    ver app/domain/plans.py) no tenía ninguna Subscription, y este endpoint
    devolvía 404 sin dejarle al admin asignarle una — un callejón sin
    salida real para incorporar a Nexo a un cliente ya existente. Ahora, si
    no tiene ninguna, se le CREA una acá mismo (requiere indicar planCode
    la primera vez — nunca se inventa un plan por default en un alta
    manual del admin)."""
    tienda = db.get(Store, store_id)
    if tienda is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    if tienda.subscription is None:
        if body.planCode is None:
            raise HTTPException(
                status_code=400,
                detail="Esta empresa todavía no tiene ninguna suscripción — elegí un plan para crearle la primera.",
            )
        plan_inicial = db.query(Plan).filter_by(code=body.planCode).first()
        if plan_inicial is None:
            raise HTTPException(status_code=404, detail="Ese plan no existe.")
        ahora = datetime.now()
        nueva_suscripcion = Subscription(
            store=tienda, plan=plan_inicial, status=body.estado or "active",
            started_at=ahora, current_period_end=(ahora + timedelta(days=30)).date(),
        )
        db.add(nueva_suscripcion)
        _registrar_accion_admin(db, admin, "asignar_plan_inicial", store_id=tienda.id, detail=f"plan={plan_inicial.code}")
        db.commit()
        # Nunca releer tienda.subscription después del commit acá: el
        # commit expira los atributos del ORM y el reload por relación
        # (Store -> Subscription) puede no resolver a tiempo dentro de la
        # misma respuesta — se devuelve directo desde el objeto recién
        # creado, que sí sigue siendo válido.
        return {"storeId": tienda.id, "plan": plan_inicial.code, "estado": nueva_suscripcion.status}

    if body.estado is not None:
        if body.estado not in ESTADOS_VALIDOS:
            raise HTTPException(status_code=400, detail=f"Estado inválido. Tiene que ser uno de: {', '.join(ESTADOS_VALIDOS)}.")
        tienda.subscription.status = body.estado
        if body.estado == "canceled":
            tienda.subscription.canceled_at = datetime.now()
    if body.planCode is not None:
        plan = db.query(Plan).filter_by(code=body.planCode).first()
        if plan is None:
            raise HTTPException(status_code=404, detail="Ese plan no existe.")
        tienda.subscription.plan = plan
    _registrar_accion_admin(
        db, admin, "cambiar_suscripcion", store_id=tienda.id,
        detail=f"plan={body.planCode or '(sin cambio)'} estado={body.estado or '(sin cambio)'}",
    )
    db.commit()

    return {
        "storeId": tienda.id,
        "plan": tienda.subscription.plan.code if tienda.subscription.plan else None,
        "estado": tienda.subscription.status,
    }


# ------------------------------------------------------------------
# Soporte — vista global de solicitudes de todas las empresas (el cliente
# solo ve las suyas, ver app/api/routes/soporte.py).
# ------------------------------------------------------------------


def _fila_soporte_admin(t: SupportTicket) -> dict:
    return {
        "id": t.id,
        "empresa": {"storeId": t.store_id, "nombre": t.store.name},
        "usuario": {"id": t.user_id, "email": t.user.email, "nombre": t.user.full_name},
        "categoria": t.category,
        "asunto": t.subject,
        "descripcion": t.description,
        "referencia": t.reference,
        "estado": t.status,
        "respuestaAdmin": t.admin_response,
        "respuestaAdminEn": t.admin_response_at.isoformat() if t.admin_response_at else None,
        "creadoEn": t.created_at.isoformat(),
        "actualizadoEn": t.updated_at.isoformat(),
    }


@router.get("/soporte/solicitudes")
def listar_solicitudes_soporte(db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)) -> list[dict]:
    tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).all()
    return [_fila_soporte_admin(t) for t in tickets]


@router.get("/soporte/solicitudes/{ticket_id}")
def detalle_solicitud_soporte(ticket_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)) -> dict:
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    return _fila_soporte_admin(ticket)


class ResponderSolicitudRequest(BaseModel):
    respuesta: str | None = None
    estado: str | None = None


@router.put("/soporte/solicitudes/{ticket_id}")
def responder_solicitud_soporte(
    ticket_id: int, body: ResponderSolicitudRequest, db: Session = Depends(get_db), admin: User = Depends(require_nexo_admin)
) -> dict:
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    if body.estado is not None and body.estado not in ESTADOS_SOPORTE_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Tiene que ser uno de: {', '.join(ESTADOS_SOPORTE_VALIDOS)}.")

    ahora = datetime.now()
    if body.respuesta is not None and body.respuesta.strip():
        ticket.admin_response = body.respuesta.strip()
        ticket.admin_response_at = ahora
        # Responder sin indicar estado explícito mueve la solicitud a "en
        # revisión" si seguía "abierta" — nunca la deja como si nadie la
        # hubiera visto todavía.
        if body.estado is None and ticket.status == "abierto":
            ticket.status = "en_revision"
    if body.estado is not None:
        ticket.status = body.estado
    ticket.updated_at = ahora
    _registrar_accion_admin(db, admin, "responder_ticket", store_id=ticket.store_id, detail=f"ticket_id={ticket.id} estado={ticket.status}")
    db.commit()
    return _fila_soporte_admin(ticket)
