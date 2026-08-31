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

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_nexo_admin
from app.db.models import (
    AuthSession,
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    Product,
    Store,
    StoreSettings,
    User,
)
from app.db.session import get_db

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


@router.get("/clientes")
def listar_clientes(db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)) -> list[dict]:
    tiendas = db.query(Store).order_by(Store.created_at.desc()).all()
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

    ultimas_sesiones = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == tienda.owner_user_id)
        .order_by(AuthSession.created_at.desc())
        .limit(5)
        .all()
    )

    settings_tienda = db.query(StoreSettings).filter_by(store_id=tienda.id).first()

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
        "productos": {"cantidad": cantidad_productos},
        "publicaciones": {"total": len(publicaciones), "porEstado": publicaciones_por_estado},
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
            {"nombre": tienda.subscription.plan.name, "estado": tienda.subscription.status}
            if (tienda.subscription and tienda.subscription.plan) else None
        ),
        "actividadReciente": [{"fecha": s.created_at.isoformat()} for s in ultimas_sesiones],
        # No existe todavía ningún mecanismo de log de errores por tienda
        # (los errores de publicación/ML solo llegan a los logs del
        # servidor) — nunca se inventa un valor acá, se deja explícito.
        "erroresRecientes": None,
    }


class ActualizarEstadoClienteRequest(BaseModel):
    suspendido: bool


@router.put("/clientes/{store_id}/estado")
def actualizar_estado_cliente(
    store_id: int, body: ActualizarEstadoClienteRequest, db: Session = Depends(get_db), _admin: User = Depends(require_nexo_admin)
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
    db.commit()
    cantidad_productos = db.query(func.count(Product.id)).filter(Product.store_id == tienda.id).scalar() or 0
    cuenta_ml = _cuenta_ml_de(tienda)
    ml_conectado = cuenta_ml is not None and cuenta_ml.status == "connected"
    return {"storeId": tienda.id, "estado": _estado_cliente(tienda, cantidad_productos, ml_conectado)}
