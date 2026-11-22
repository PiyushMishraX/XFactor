"""Aggregated API router.

Every feature router is registered here and mounted under the configured API
prefix by :mod:`app.main`.
"""

from fastapi import APIRouter

from app.api import approvals, dashboard, health, orchestration

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(orchestration.router)
api_router.include_router(approvals.router)
api_router.include_router(dashboard.router)
