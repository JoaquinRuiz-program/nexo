"""
Base declarativa de SQLAlchemy — un solo lugar del que cuelgan todos los
modelos (app/db/models/*.py), para que Alembic (y `Base.metadata.create_all`
en los tests) vean siempre el conjunto completo de tablas sin importar en
qué orden se hayan importado los módulos de modelos.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
