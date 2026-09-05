"""ampliar external_account_site_id para nombres de hoja de Google Sheets

Revision ID: 7f1a9c3e5d02
Revises: d3e5f7a9b1c4
Create Date: 2026-09-05 00:00:00.000000

De String(10) a String(100): Mercado Libre sigue guardando ahí un código
corto ("MLC"), pero la integración de Google Sheets (marketplace=
"google_sheets") reaprovecha el mismo campo para el nombre de la
pestaña/hoja elegida por el dueño — texto libre, puede superar los 10
caracteres.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f1a9c3e5d02'
down_revision: Union[str, None] = 'd3e5f7a9b1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('marketplace_accounts') as batch_op:
        batch_op.alter_column(
            'external_account_site_id',
            existing_type=sa.String(length=10),
            type_=sa.String(length=100),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('marketplace_accounts') as batch_op:
        batch_op.alter_column(
            'external_account_site_id',
            existing_type=sa.String(length=100),
            type_=sa.String(length=10),
            existing_nullable=True,
        )
