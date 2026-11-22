"""Health-check endpoints used by the frontend, Docker and monitoring."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.config.settings import get_settings
from app.database.session import check_database_connection

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health", summary="Service and dependency health")
def health() -> dict:
    """Report application metadata and PostgreSQL connectivity."""
    database_connected = check_database_connection()
    return {
        "status": "ok" if database_connected else "degraded",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "database": "connected" if database_connected else "unavailable",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/live", summary="Liveness probe")
def liveness() -> dict:
    """Cheap liveness probe that does not touch any dependency."""
    return {"status": "ok"}
