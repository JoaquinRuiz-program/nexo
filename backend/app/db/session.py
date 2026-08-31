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
    # pool_pre_ping: 30 de agosto de 2026, hallazgo de backend-architect
    # para producción — un Postgres gestionado (RDS, Supabase, Neon, etc.)
    # corta conexiones idle; sin esto, el primer request después de un
    # rato inactivo puede fallar con "server closed the connection"
    # (SQLAlchemy hace un SELECT 1 barato antes de reusar la conexión del
    # pool). Sin efecto práctico en SQLite.
    return create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)


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
