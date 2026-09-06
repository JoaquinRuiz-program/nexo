"""cobro real con Mercado Pago

Revision ID: c4e8b1d63f7a
Revises: 9a3c7e1f4b62
Create Date: 2026-09-06 00:00:00.000000

Agrega `monthly_price_clp` a `plans` (precio real para calcular cobros,
nunca se parsea `price_demo_label`) y a `subscriptions`: `billing_cycle`,
`mercadopago_preapproval_id`, `mercadopago_last_payment_id`,
`last_payment_at`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8b1d63f7a'
down_revision: Union[str, None] = '9a3c7e1f4b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('plans', sa.Column('monthly_price_clp', sa.Integer(), nullable=True))
    op.add_column('subscriptions', sa.Column('billing_cycle', sa.String(length=10), nullable=True))
    op.add_column('subscriptions', sa.Column('mercadopago_preapproval_id', sa.String(length=100), nullable=True))
    op.add_column('subscriptions', sa.Column('mercadopago_last_payment_id', sa.String(length=100), nullable=True))
    op.add_column('subscriptions', sa.Column('last_payment_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'last_payment_at')
    op.drop_column('subscriptions', 'mercadopago_last_payment_id')
    op.drop_column('subscriptions', 'mercadopago_preapproval_id')
    op.drop_column('subscriptions', 'billing_cycle')
    op.drop_column('plans', 'monthly_price_clp')
