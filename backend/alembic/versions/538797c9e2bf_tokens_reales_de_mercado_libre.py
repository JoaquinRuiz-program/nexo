"""tokens reales de mercado libre

Revision ID: 538797c9e2bf
Revises: d22fcefcb976
Create Date: 2026-08-24 16:59:34.320387

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '538797c9e2bf'
down_revision: Union[str, None] = 'd22fcefcb976'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite no soporta ALTER TABLE para agregar/quitar constraints — hace
    # falta "batch mode" (recrea la tabla), a diferencia de las migraciones
    # anteriores que solo agregaban columnas sueltas.
    with op.batch_alter_table("marketplace_accounts") as batch_op:
        batch_op.add_column(sa.Column("access_token_encrypted", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("refresh_token_encrypted", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("token_expires_at", sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_marketplace_account_store_marketplace", ["store_id", "marketplace"]
        )
        batch_op.drop_column("access_token_ref")


def downgrade() -> None:
    with op.batch_alter_table("marketplace_accounts") as batch_op:
        batch_op.add_column(sa.Column("access_token_ref", sa.VARCHAR(length=255), nullable=True))
        batch_op.drop_constraint("uq_marketplace_account_store_marketplace", type_="unique")
        batch_op.drop_column("token_expires_at")
        batch_op.drop_column("refresh_token_encrypted")
        batch_op.drop_column("access_token_encrypted")
