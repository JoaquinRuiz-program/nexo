"""minimos por defecto mercadolibre

Revision ID: f6b8d0a2c4e5
Revises: e5a7c9b1d3f4
Create Date: 2026-09-14 00:00:00.000000

Decision del dueno (14 de septiembre de 2026): margen minimo 15 % y ganancia
neta minima $3.000 por defecto para Mercado Libre, modificables. Completa las
filas existentes que no tenian ese valor; desde aca un NULL es un minimo que
el usuario decidio no exigir (ver umbrales_minimos en channel_costs.py).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f6b8d0a2c4e5'
down_revision: Union[str, None] = 'e5a7c9b1d3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE channel_cost_settings SET min_margin_pct = 15 WHERE channel = 'mercadolibre' AND min_margin_pct IS NULL")
    op.execute("UPDATE channel_cost_settings SET min_profit_clp = 3000 WHERE channel = 'mercadolibre' AND min_profit_clp IS NULL")


def downgrade() -> None:
    # No se puede distinguir un default completado de un valor elegido: no se revierte.
    pass
