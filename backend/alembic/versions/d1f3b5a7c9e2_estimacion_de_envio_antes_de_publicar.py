"""estimacion del costo de envio antes de publicar

Revision ID: d1f3b5a7c9e2
Revises: c3e5a7b9d1f2
Create Date: 2026-09-16 00:00:00.000000

Cache del costo de envio que Mercado Libre le cobraria al vendedor por
categoria + precio, consultado con las medidas por defecto de la categoria
(ver app/domain/ml_shipping.py). Es una estimacion: el costo REAL de una
publicacion existente sigue viviendo en marketplace_listings y tiene
prioridad. shipping_cost NULL = "no disponible" con su motivo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f3b5a7c9e2'
down_revision: Union[str, None] = 'c3e5a7b9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mercadolibre_shipping_estimates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.String(50), nullable=False),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.Column('shipping_cost', sa.Numeric(12, 2), nullable=True),
        sa.Column('mandatory', sa.Boolean(), nullable=True),
        sa.Column('dimensions', sa.String(50), nullable=True),
        sa.Column('unavailable_reason', sa.String(255), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'category_id', 'price', name='uq_ml_shipping_estimate_store_category_price'),
    )


def downgrade() -> None:
    op.drop_table('mercadolibre_shipping_estimates')
