"""ver como empresa: contexto en auth_sessions (reemplaza impersonacion)

Revision ID: e2b7d4a09c15
Revises: c4e8b1d63f7a
Create Date: 2026-09-06 00:00:00.000000

Reemplaza `auth_sessions.impersonated_by_admin_id` (impersonación real: se
creaba una sesión del usuario cliente y se pisaba la cookie del admin) por
`auth_sessions.viewing_store_id` — un CONTEXTO sobre la propia sesión del
admin: qué empresa está viendo. La sesión del admin nunca se reemplaza, así
que salir no lo desloguea y el contexto sobrevive a un refresh.

Antes de borrar la columna vieja se REVOCAN las sesiones de impersonación
que hubieran quedado abiertas: eran sesiones que pertenecen al usuario
cliente y que, sin esa columna, quedarían indistinguibles de una sesión
normal del cliente (un admin seguiría con acceso a esa cuenta sin ningún
rastro). Revocarlas es lo único correcto.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7d4a09c15'
down_revision: Union[str, None] = 'c4e8b1d63f7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP "
            "WHERE impersonated_by_admin_id IS NOT NULL AND revoked_at IS NULL"
        )
    )
    with op.batch_alter_table('auth_sessions') as batch_op:
        batch_op.add_column(sa.Column('viewing_store_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_auth_sessions_viewing_store_id_stores',
            'stores', ['viewing_store_id'], ['id'],
        )
        batch_op.drop_constraint('fk_auth_sessions_impersonated_by_admin_id_users', type_='foreignkey')
        batch_op.drop_column('impersonated_by_admin_id')


def downgrade() -> None:
    with op.batch_alter_table('auth_sessions') as batch_op:
        batch_op.add_column(sa.Column('impersonated_by_admin_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_auth_sessions_impersonated_by_admin_id_users',
            'users', ['impersonated_by_admin_id'], ['id'],
        )
        batch_op.drop_constraint('fk_auth_sessions_viewing_store_id_stores', type_='foreignkey')
        batch_op.drop_column('viewing_store_id')
