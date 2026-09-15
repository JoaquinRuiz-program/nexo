"""envio desde precio de venta

Revision ID: c3e5a7b9d1f2
Revises: b9d1f3a5c7e9
Create Date: 2026-09-15 00:00:00.000000

channel_cost_settings.shipping_min_price_clp: precio de venta desde el cual el
vendedor paga el envio manual. NULL = se descuenta en todos los productos.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e5a7b9d1f2'
down_revision: Union[str, None] = 'b9d1f3a5c7e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('channel_cost_settings') as batch_op:
        batch_op.add_column(sa.Column('shipping_min_price_clp', sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('channel_cost_settings') as batch_op:
        batch_op.drop_column('shipping_min_price_clp')
