"""PostgreSQL connection management.

The SQLAlchemy engine is created lazily so that importing the application never
requires a reachable database. Connection problems are handled gracefully and
are surfaced through the health-check endpoint instead of crashing the process.
"""

import logging
from collections.abc import Generator
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Return (and lazily create) the process-wide SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
        )
        logger.info(
            "PostgreSQL engine created for %s:%s/%s",
            settings.POSTGRES_HOST,
            settings.POSTGRES_PORT,
            settings.POSTGRES_DB,
        )
    return _engine


def get_session_factory() -> sessionmaker:
    """Return (and lazily create) the session factory bound to the engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> bool:
    """Return ``True`` when a trivial query against PostgreSQL succeeds."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - a health check must never raise
        logger.warning("Database connectivity check failed: %s", exc)
        return False
