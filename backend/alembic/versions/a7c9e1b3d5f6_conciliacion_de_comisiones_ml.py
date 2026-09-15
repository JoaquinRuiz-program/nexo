"""conciliacion de comisiones ml

Revision ID: a7c9e1b3d5f6
Revises: f6b8d0a2c4e5
Create Date: 2026-09-14 00:00:00.000000

Cargos facturados por Mercado Libre por venta (order_billing) para conciliar
la comision real cobrada con la que calcula Nexo. Ver app/db/models/order_billing.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c9e1b3d5f6'
down_revision: Union[str, None] = 'f6b8d0a2c4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'order_billing',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('has_charges', sa.Boolean(), nullable=False),
        sa.Column('billed_sale_fee', sa.Numeric(12, 2), nullable=False),
        sa.Column('billed_shipping', sa.Numeric(12, 2), nullable=False),
        sa.Column('billed_other', sa.Numeric(12, 2), nullable=False),
        sa.Column('listing_type_id', sa.String(length=30), nullable=True),
        sa.Column('estimated_sale_fee', sa.Numeric(12, 2), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'order_id', name='uq_order_billing_store_order'),
    )


def downgrade() -> None:
    op.drop_table('order_billing')
