"""Checkpoint persistence for the supervisor workflow (Step 4).

Two checkpointers are offered:

* :func:`in_memory_checkpointer` — an :class:`~langgraph.checkpoint.memory.InMemorySaver`
  for tests and single-process runs.
* :func:`postgres_checkpointer` — a
  :class:`~langgraph.checkpoint.postgres.PostgresSaver` that persists every
  checkpoint to the application's PostgreSQL database, so a workflow can be
  resumed from a saved checkpoint in a different process.

:func:`open_checkpointer` picks one from ``LANGGRAPH_CHECKPOINT_BACKEND``.

Assumption
----------
The LangGraph checkpoint adapter speaks **psycopg 3 / libpq**, while the
application's SQLAlchemy engine speaks psycopg2. :func:`checkpointer_dsn`
therefore strips the ``+psycopg2`` driver suffix from
:attr:`~app.config.settings.Settings.database_url` before handing the URL over.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Iterator, Optional

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: Driver suffixes SQLAlchemy may have added to the URL that libpq does not accept.
_SQLALCHEMY_DRIVER_SUFFIXES = (
    "postgresql+psycopg2://",
    "postgresql+psycopg://",
    "postgres://",
    "postgresql://",
)


def checkpointer_dsn(settings: Optional[Settings] = None) -> str:
    """Return the libpq connection string the checkpoint backend expects.

    Args:
        settings: Settings to read the database URL from; defaults to the
            process settings.
    """
    settings = settings or get_settings()
    url = settings.database_url
    for prefix in _SQLALCHEMY_DRIVER_SUFFIXES:
        if url.startswith(prefix):
            return f"postgresql://{url[len(prefix):]}"
    return url


def in_memory_checkpointer() -> Any:
    """Return a checkpointer that keeps checkpoints in process memory."""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@contextlib.contextmanager
def postgres_checkpointer(
    settings: Optional[Settings] = None,
    *,
    setup: bool = True,
) -> Iterator[Any]:
    """Yield a PostgreSQL-backed checkpointer, closing its connection on exit.

    Args:
        settings: Settings to read the database URL from.
        setup: Create the checkpoint tables when they are missing. Safe to leave
            on: the adapter's migrations are idempotent.
    """
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = checkpointer_dsn(settings)
    logger.info("Opening PostgreSQL checkpointer for the LangGraph supervisor.")
    with PostgresSaver.from_conn_string(dsn) as saver:
        if setup:
            saver.setup()
        yield saver


@contextlib.contextmanager
def open_checkpointer(
    settings: Optional[Settings] = None,
    *,
    backend: Optional[str] = None,
) -> Iterator[Any]:
    """Yield the checkpointer selected by ``LANGGRAPH_CHECKPOINT_BACKEND``.

    ``"postgres"`` uses :func:`postgres_checkpointer`; anything else (including
    ``"memory"``) yields an in-memory checkpointer.
    """
    settings = settings or get_settings()
    chosen = (backend or settings.LANGGRAPH_CHECKPOINT_BACKEND or "memory").strip().lower()
    if chosen == "postgres":
        with postgres_checkpointer(settings) as saver:
            yield saver
    else:
        yield in_memory_checkpointer()
