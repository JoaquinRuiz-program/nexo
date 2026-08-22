"""
Motor y sesiones de la base de datos propia del sistema.

Deliberadamente síncrono por ahora (SQLAlchemy en modo clásico, no
`asyncio`): esta fase es solo diseño + modelos + migraciones + pruebas, sin
un motor de sincronización real corriendo todavía. Cuando construyamos ese
motor (Fase 4, el que sí habla con WooCommerce y Mercado Libre al mismo
tiempo que escribe en la base), conviene revisar si pasar a sesiones
asíncronas — por ahora agregar esa complejidad no tiene beneficio real.

SQLite en desarrollo/pruebas (cero instalación), PostgreSQL en producción —
ambos casos son la misma URL configurable, sin cambiar una línea de código
de los modelos.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


# Engine "de proceso" — se usa cuando corre la app real (no en los tests,
# que crean su propio engine aislado por prueba; ver tests/db/conftest.py).
engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: una sesión por request, siempre cerrada al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
