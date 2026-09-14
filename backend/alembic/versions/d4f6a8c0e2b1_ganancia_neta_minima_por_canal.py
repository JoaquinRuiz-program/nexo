"""ganancia neta minima por canal

Revision ID: d4f6a8c0e2b1
Revises: c9e1a3b5d7f2
Create Date: 2026-09-14 00:00:00.000000

Pedido del dueno (14 de septiembre de 2026): un producto caro puede dejar buena
ganancia en pesos con poco margen en %. channel_cost_settings.min_profit_clp es
la ganancia neta minima por unidad: un producto conviene si alcanza el margen
minimo (%) O esta ganancia. NULL = no configurada (nada cambia).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6a8c0e2b1'
down_revision: Union[str, None] = 'c9e1a3b5d7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channel_cost_settings') as batch_op:
        batch_op.add_column(sa.Column('min_profit_clp', sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('channel_cost_settings') as batch_op:
        batch_op.drop_column('min_profit_clp')
