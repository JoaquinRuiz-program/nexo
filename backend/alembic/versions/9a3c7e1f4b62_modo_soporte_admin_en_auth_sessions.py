"""modo soporte (admin) en auth_sessions

Revision ID: 9a3c7e1f4b62
Revises: 7f1a9c3e5d02
Create Date: 2026-09-06 00:00:00.000000

Agrega `impersonated_by_admin_id` a `auth_sessions` — NULL en cualquier
sesión normal; si un administrador de Nexo "entró como soporte" a una
empresa (ver app/api/routes/admin.py::entrar_como_soporte), acá queda
registrado qué admin fue.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a3c7e1f4b62'
down_revision: Union[str, None] = '7f1a9c3e5d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('auth_sessions') as batch_op:
        batch_op.add_column(sa.Column('impersonated_by_admin_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_auth_sessions_impersonated_by_admin_id_users',
            'users', ['impersonated_by_admin_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('auth_sessions') as batch_op:
        batch_op.drop_constraint('fk_auth_sessions_impersonated_by_admin_id_users', type_='foreignkey')
        batch_op.drop_column('impersonated_by_admin_id')
