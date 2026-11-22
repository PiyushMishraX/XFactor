"""Read-only control-tower API for the Step 8 dashboard.

Every payload is derived from real persisted state:

* ``/dashboard/overview`` — KPI counts and the latest workflow runs;
* ``/dashboard/runs`` — recorded workflow history (newest first);
* ``/dashboard/runs/{thread_id}`` — one run with the full recorded state the
  Agent Activity, Scenario Comparison and Audit pages render;
* ``/dashboard/disruptions`` — assessed disruptions and the supervisor's latest
  decision;
* ``/dashboard/shipments`` — seeded shipment master data with suppliers;
* ``/dashboard/inventory`` — the SAP connector's inventory positions and
  materials, labelled simulated or live through their provenance.

There are no write endpoints here and no payload is invented: an empty history
returns an empty list so the frontend can show a real empty state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.integrations.base import IntegrationNotConfiguredError
from app.integrations.sap import SAPConnector, get_sap_connector
from app.services.dashboard_service import list_shipments, platform_overview
from app.services.workflow_history import (
    get_workflow_run,
    list_disruptions,
    list_workflow_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def sap_connector() -> SAPConnector:
    """The SAP read connector; overridden in tests."""
    return get_sap_connector()


def _database_error(exc: Exception) -> HTTPException:
    logger.warning("Dashboard database read failed: %s", exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The workflow database is unavailable.",
    )


@router.get("/overview", summary="Control-tower KPI counts and latest runs")
def overview(session: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return platform_overview(session)
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc


@router.get("/runs", summary="List recorded workflow runs")
def runs(
    limit: int = Query(default=25, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        items = list_workflow_runs(session, limit=limit, status=status_filter)
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    return {"count": len(items), "runs": items}


@router.get("/runs/{thread_id}", summary="Read one workflow run and its state")
def run_detail(thread_id: str, session: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        payload = get_workflow_run(session, thread_id)
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No recorded workflow run exists for thread {thread_id!r}.",
        )
    return payload


@router.get("/disruptions", summary="Recent assessed disruptions")
def disruptions(
    limit: int = Query(default=25, ge=1, le=100),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        items = list_disruptions(session, limit=limit)
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    return {"count": len(items), "disruptions": items}


@router.get("/shipments", summary="Shipment master data with suppliers")
def shipments(session: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        items = list_shipments(session)
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    return {
        "count": len(items),
        "source": "PostgreSQL demo reference data",
        "shipments": items,
    }


@router.get("/inventory", summary="SAP inventory positions and material master")
def inventory(connector: SAPConnector = Depends(sap_connector)) -> Dict[str, Any]:
    try:
        items = connector.list_inventory()
        materials = connector.list_materials()
    except IntegrationNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    provenance = None
    if items:
        provenance = items[0].provenance
    elif materials:
        provenance = materials[0].provenance
    is_mock = bool(provenance.is_mock) if provenance is not None else True
    return {
        "count": len(items),
        "material_count": len(materials),
        "is_mock": is_mock,
        "source": provenance.label if provenance is not None else "SAP connector",
        "endpoint": provenance.endpoint if provenance is not None else None,
        "items": [item.model_dump(mode="json") for item in items],
        "materials": [material.model_dump(mode="json") for material in materials],
    }


__all__ = ["router", "sap_connector"]
