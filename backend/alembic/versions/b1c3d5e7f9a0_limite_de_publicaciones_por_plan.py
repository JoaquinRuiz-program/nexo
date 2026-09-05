"""limite de publicaciones por plan

Revision ID: b1c3d5e7f9a0
Revises: ac76a1d7d3ff
Create Date: 2026-09-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c3d5e7f9a0'
down_revision: Union[str, None] = 'ac76a1d7d3ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # None = sin límite (igual criterio que product_limit ya existente) —
    # necesario para el sistema de suscripciones/planes: hasta ahora solo
    # se limitaba cantidad de productos, nunca publicaciones activas.
    op.add_column("plans", sa.Column("publication_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.drop_column("publication_limit")
