"""X FACTOR FastAPI application entry point.

Run locally with::

    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config.logging_config import configure_logging
from app.config.settings import get_settings
from app.database.session import check_database_connection, get_engine
from app.services.approval_repository import ensure_approval_schema

settings = get_settings()
configure_logging(settings.LOG_LEVEL, settings.LOG_JSON)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown hooks."""
    logger.info(
        "Starting %s v%s (%s)", settings.APP_NAME, settings.APP_VERSION, settings.APP_ENV
    )
    if check_database_connection():
        logger.info("PostgreSQL connection verified.")
        try:
            ensure_approval_schema(get_engine())
        except Exception:  # noqa: BLE001 - startup must not fail on schema setup
            logger.exception("Could not ensure the approval schema exists.")
    else:
        logger.warning(
            "PostgreSQL is not reachable — database-backed features are unavailable."
        )
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description="Agentic AI-powered Supply Chain Resilience Platform",
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/", tags=["Root"], summary="Service index")
def root() -> dict:
    """Small discovery payload for humans and the frontend."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": f"{settings.API_PREFIX}/health",
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected errors and return a generic 500 payload."""
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
