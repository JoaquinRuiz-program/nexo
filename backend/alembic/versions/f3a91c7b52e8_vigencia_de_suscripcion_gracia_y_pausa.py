"""vigencia de suscripcion: gracia, recordatorios y pausa por vencimiento

Revision ID: f3a91c7b52e8
Revises: e2b7d4a09c15
Create Date: 2026-09-13 00:00:00.000000

Tres columnas para el ciclo de vida de la suscripcion (ver
app/domain/subscription_lifecycle.py):

- subscriptions.ultimo_hito_recordatorio: el ultimo recordatorio (5/3/1)
  que ya se avisó, para no repetir el mismo mail si el proceso diario corre
  mas de una vez. NULL = ninguno enviado.
- subscriptions.publicaciones_pausadas_por_vencimiento: marca idempotente de
  que ya se corrio la pausa real en Mercado Libre para esta empresa, para no
  volver a llamar a la API en cada corrida.
- marketplace_listings.paused_by_expiry: esta publicacion fue pausada por el
  vencimiento (no por el cliente a mano). Al pagar, solo se reactivan estas,
  nunca las que el cliente habia pausado por su cuenta.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a91c7b52e8'
down_revision: Union[str, None] = 'e2b7d4a09c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.add_column(sa.Column('ultimo_hito_recordatorio', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('publicaciones_pausadas_por_vencimiento', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('marketplace_listings') as batch_op:
        batch_op.add_column(sa.Column('paused_by_expiry', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('marketplace_listings') as batch_op:
        batch_op.drop_column('paused_by_expiry')
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.drop_column('publicaciones_pausadas_por_vencimiento')
        batch_op.drop_column('ultimo_hito_recordatorio')
