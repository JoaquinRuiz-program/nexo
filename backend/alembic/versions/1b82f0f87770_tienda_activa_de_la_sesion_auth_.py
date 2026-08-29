"""tienda activa de la sesion (auth_sessions.active_store_id)

Revision ID: 1b82f0f87770
Revises: 3780b4217d64
Create Date: 2026-08-29 19:29:26.583546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b82f0f87770'
down_revision: Union[str, None] = '3780b4217d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite no soporta ALTER TABLE ADD CONSTRAINT (ver
    # NotImplementedError de alembic/ddl/sqlite.py) — batch mode hace el
    # truco de copiar-y-mover la tabla, necesario acá porque se agrega una
    # foreign key, no solo una columna simple.
    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("active_store_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_auth_sessions_active_store_id_stores", "stores", ["active_store_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_auth_sessions_active_store_id_stores", type_="foreignkey")
        batch_op.drop_column("active_store_id")
