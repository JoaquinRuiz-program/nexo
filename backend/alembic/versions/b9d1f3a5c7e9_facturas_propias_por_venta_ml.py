"""facturas propias por venta ml

Revision ID: b9d1f3a5c7e9
Revises: a7c9e1b3d5f6
Create Date: 2026-09-15 00:00:00.000000

Registro de la factura propia del vendedor adjunta a cada venta de Mercado
Libre (order_invoices). Ver app/db/models/order_invoice.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9d1f3a5c7e9'
down_revision: Union[str, None] = 'a7c9e1b3d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'order_invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('pack_id', sa.String(length=50), nullable=False),
        sa.Column('document_ids', sa.String(length=500), nullable=False),
        sa.Column('file_names', sa.String(length=500), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'order_id', name='uq_order_invoice_store_order'),
    )


def downgrade() -> None:
    op.drop_table('order_invoices')
