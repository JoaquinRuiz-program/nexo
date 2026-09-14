"""costo de envio real de mercado libre por publicacion

Revision ID: b8d2f4a6c1e3
Revises: f3a91c7b52e8
Create Date: 2026-09-14 00:00:00.000000

Datos de envio que Mercado Libre informa para cada publicacion (ver
app/domain/ml_shipping.py y app/services/ml_shipping_sync.py). Todas
nullable: NULL en shipping_cost = "No disponible" (el motivo queda en
shipping_cost_unavailable_reason), nunca un valor estimado.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d2f4a6c1e3'
down_revision: Union[str, None] = 'f3a91c7b52e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('marketplace_listings') as batch_op:
        batch_op.add_column(sa.Column('shipping_cost', sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column('shipping_currency_id', sa.String(10), nullable=True))
        batch_op.add_column(sa.Column('shipping_mode', sa.String(30), nullable=True))
        batch_op.add_column(sa.Column('shipping_logistic_type', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('shipping_free_shipping', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('shipping_cost_unavailable_reason', sa.String(255), nullable=True))
        batch_op.add_column(sa.Column('shipping_synced_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('marketplace_listings') as batch_op:
        batch_op.drop_column('shipping_synced_at')
        batch_op.drop_column('shipping_cost_unavailable_reason')
        batch_op.drop_column('shipping_free_shipping')
        batch_op.drop_column('shipping_logistic_type')
        batch_op.drop_column('shipping_mode')
        batch_op.drop_column('shipping_currency_id')
        batch_op.drop_column('shipping_cost')
