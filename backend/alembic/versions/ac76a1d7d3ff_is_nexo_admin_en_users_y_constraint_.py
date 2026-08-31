"""is_nexo_admin en users y constraint anti-duplicado en marketplace_listings

Revision ID: ac76a1d7d3ff
Revises: cb9872ee2357
Create Date: 2026-08-30 22:25:26.893854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac76a1d7d3ff'
down_revision: Union[str, None] = 'cb9872ee2357'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite no soporta ALTER TABLE ADD CONSTRAINT (ver
    # alembic/ddl/sqlite.py) — batch mode copia-y-mueve la tabla, igual
    # criterio que 1b82f0f87770.
    with op.batch_alter_table("marketplace_listings", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_listing_account_product", ["account_id", "product_id"])
    op.add_column("users", sa.Column("is_nexo_admin", sa.Boolean(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "is_nexo_admin")
    with op.batch_alter_table("marketplace_listings", schema=None) as batch_op:
        batch_op.drop_constraint("uq_listing_account_product", type_="unique")
