"""
Configuración de costos por canal de venta (comisión, envío, otros costos
fijos) — lo que domain/profitability.py necesita para calcular margen neto.

29 de agosto de 2026 — la tienda se resuelve desde la sesión autenticada
(Depends(get_current_store), ver app/api/deps.py), nunca "la única tienda
que existe". Nada acá asume un valor por defecto para ningún costo — un
canal sin configurar simplemente no aparece, o aparece con sus campos en null.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_store
from app.db.models import ChannelCostSettings, Store
from app.db.session import get_db

router = APIRouter(prefix="/api/configuracion", tags=["configuracion"])


class ChannelCostsUpdate(BaseModel):
    commission_pct: float | None = None
    shipping_cost: float | None = None
    other_fixed_cost: float | None = None
    # classic | premium | None ("comparar ambas", ver domain/ml_fees.py) —
    # solo tiene sentido para channel="mercadolibre".
    listing_type_pref: str | None = None
    # 30 de agosto de 2026 — FASE 5 (precio recomendado): margen objetivo y
    # mínimo aceptable, POR CANAL. NULL = "no configurado" (ver
    # domain/pricing.py: sin esto, la recomendación de precio devuelve
    # DATOS_INSUFICIENTES en vez de asumir un % inventado).
    target_margin_pct: float | None = None
    min_margin_pct: float | None = None


def _fila(costos: ChannelCostSettings) -> dict:
    return {
        "channel": costos.channel,
        "commissionPct": float(costos.commission_pct) if costos.commission_pct is not None else None,
        "shippingCost": float(costos.shipping_cost) if costos.shipping_cost is not None else None,
        "otherFixedCost": float(costos.other_fixed_cost) if costos.other_fixed_cost is not None else None,
        "listingTypePref": costos.listing_type_pref,
        "targetMarginPct": float(costos.target_margin_pct) if costos.target_margin_pct is not None else None,
        "minMarginPct": float(costos.min_margin_pct) if costos.min_margin_pct is not None else None,
        # Ningún campo configurado todavía = el canal existe pero no se usa
        # para calcular margen neto (ver domain/profitability.py.is_configured).
        "configurado": costos.commission_pct is not None or costos.shipping_cost is not None or costos.other_fixed_cost is not None,
        "actualizadoEn": costos.updated_at.isoformat(),
    }


@router.get("/canales")
def listar_canales(db: Session = Depends(get_db), store: Store = Depends(get_current_store)) -> list[dict]:
    canales = db.query(ChannelCostSettings).filter_by(store_id=store.id).order_by(ChannelCostSettings.channel).all()
    return [_fila(c) for c in canales]


@router.put("/canales/{channel}")
def configurar_canal(
    channel: str, body: ChannelCostsUpdate, db: Session = Depends(get_db), store: Store = Depends(get_current_store)
) -> dict:
    costos = db.query(ChannelCostSettings).filter_by(store_id=store.id, channel=channel).first()
    if costos is None:
        costos = ChannelCostSettings(store=store, channel=channel, updated_at=datetime.now())
        db.add(costos)

    costos.commission_pct = body.commission_pct
    costos.shipping_cost = body.shipping_cost
    costos.other_fixed_cost = body.other_fixed_cost
    costos.listing_type_pref = body.listing_type_pref
    costos.target_margin_pct = body.target_margin_pct
    costos.min_margin_pct = body.min_margin_pct
    costos.updated_at = datetime.now()
    db.commit()
    db.refresh(costos)
    return _fila(costos)
