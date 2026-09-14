"""limites de productos por plan: basico 1000, pro 5000

Revision ID: c9e1a3b5d7f2
Revises: b8d2f4a6c1e3
Create Date: 2026-09-14 00:00:00.000000

Decision del dueno (14 de septiembre de 2026): cualquier tienda real (ej. una
libreria) supera facilmente los 1.000 items. Nexo Basico pasa de 200 a 1.000
productos y Nexo Pro de 1.000 a 5.000. ensure_default_plans solo CREA planes
que faltan (nunca actualiza), por eso los planes ya guardados se actualizan
aca. Solo se toca un plan que sigue con el limite por defecto anterior: un
limite editado a mano desde el panel de admin no se pisa. Los limites de
publicaciones (150 / 800) no cambian.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e1a3b5d7f2'
down_revision: Union[str, None] = 'b8d2f4a6c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, limite anterior, limite nuevo, texto anterior, texto nuevo)
_CAMBIOS = [
    ("basico", 200, 1000, "Hasta 200 productos", "Hasta 1.000 productos"),
    ("pro", 1000, 5000, "Hasta 1.000 productos", "Hasta 5.000 productos"),
]

_plans = sa.table(
    "plans",
    sa.column("id", sa.Integer),
    sa.column("code", sa.String),
    sa.column("product_limit", sa.Integer),
    sa.column("features", sa.JSON),
)


def _aplicar(cambios) -> None:
    bind = op.get_bind()
    for code, antes, despues, texto_antes, texto_despues in cambios:
        filas = bind.execute(
            sa.select(_plans.c.id, _plans.c.features).where(_plans.c.code == code, _plans.c.product_limit == antes)
        ).fetchall()
        for plan_id, features in filas:
            if isinstance(features, str):
                features = json.loads(features)
            nuevas = [texto_despues if f == texto_antes else f for f in (features or [])]
            bind.execute(_plans.update().where(_plans.c.id == plan_id).values(product_limit=despues, features=nuevas))


def upgrade() -> None:
    _aplicar(_CAMBIOS)


def downgrade() -> None:
    # Orden inverso: primero Pro (5000 -> 1000), después Básico (1000 -> 200).
    _aplicar([(code, despues, antes, texto_despues, texto_antes) for code, antes, despues, texto_antes, texto_despues in reversed(_CAMBIOS)])
