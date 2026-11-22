"""Logging configuration for X FACTOR.

A single entry point (:func:`configure_logging`) is used by the FastAPI
application and the test-suite so that every process logs consistently.
Human readable output is used in development; structured JSON is available
for production / container deployments.
"""

import logging
import sys

from pythonjsonlogger import json as json_logger


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure the root logger.

    Args:
        level: Log level name (e.g. ``"INFO"``, ``"DEBUG"``).
        json_logs: When ``True`` emit structured JSON log lines.
    """
    handler = logging.StreamHandler(sys.stdout)

    if json_logs:
        handler.setFormatter(
            json_logger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level"},
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn keeps its own handlers by default — align them with ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
