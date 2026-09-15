"""devoluciones de mercado libre

Revision ID: e5a7c9b1d3f4
Revises: d4f6a8c0e2b1
Create Date: 2026-09-14 00:00:00.000000

Devoluciones reales de Mercado Libre por empresa (order_returns), sin datos
del comprador. Ver app/db/models/returns.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9b1d3f4'
down_revision: Union[str, None] = 'd4f6a8c0e2b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'order_returns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('external_claim_id', sa.String(length=50), nullable=False),
        sa.Column('external_order_id', sa.String(length=100), nullable=True),
        sa.Column('claim_type', sa.String(length=30), nullable=False),
        sa.Column('claim_status', sa.String(length=30), nullable=True),
        sa.Column('return_status', sa.String(length=30), nullable=True),
        sa.Column('money_status', sa.String(length=30), nullable=True),
        sa.Column('claim_created_at', sa.DateTime(), nullable=True),
        sa.Column('return_closed_at', sa.DateTime(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'external_claim_id', name='uq_order_return_store_claim'),
    )


def downgrade() -> None:
    op.drop_table('order_returns')
