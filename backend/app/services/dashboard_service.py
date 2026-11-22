"""Read-only aggregation for the Step 8 control-tower dashboard.

Nothing here decides anything: it reads the persisted workflow history, the
seeded shipment master data, and the SAP connector's inventory view, and returns
them as JSON-safe dictionaries. The dashboard never recomputes an agent result.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.supply_chain import Shipment, Supplier
from app.services.workflow_history import list_workflow_runs, run_status_counts


def _shipment(row: Shipment) -> Dict[str, Any]:
    supplier = row.supplier
    return {
        "id": row.id,
        "origin": row.origin,
        "destination": row.destination,
        "route": row.route,
        "transport_mode": row.transport_mode,
        "carrier": row.carrier,
        "status": row.status,
        "cargo": row.cargo,
        "value_usd": float(row.value_usd),
        "supplier_id": row.supplier_id,
        "supplier": (
            {
                "id": supplier.id,
                "name": supplier.name,
                "country": supplier.country,
                "category": supplier.category,
                "risk_tier": supplier.risk_tier,
            }
            if supplier is not None
            else None
        ),
    }


def list_shipments(session: Session) -> List[Dict[str, Any]]:
    """Every seeded shipment, with its supplier, ordered by shipment id."""
    statement = (
        select(Shipment)
        .options(joinedload(Shipment.supplier))
        .order_by(Shipment.id)
    )
    rows = session.execute(statement).scalars().unique().all()
    return [_shipment(row) for row in rows]


def platform_overview(session: Session) -> Dict[str, Any]:
    """KPI counts and the latest runs for the overview page."""
    counts = run_status_counts(session)
    shipment_count = session.execute(
        select(func.count()).select_from(Shipment)
    ).scalar_one()
    supplier_count = session.execute(
        select(func.count()).select_from(Supplier)
    ).scalar_one()
    return {
        "counts": {
            **counts,
            "shipments": int(shipment_count),
            "suppliers": int(supplier_count),
        },
        "latest_runs": list_workflow_runs(session, limit=5),
        "data_sources": {
            "shipments": "PostgreSQL demo reference data",
            "workflow_history": "PostgreSQL workflow_runs",
            "inventory": "SAP connector (simulated unless live credentials are configured)",
        },
    }


__all__ = ["list_shipments", "platform_overview"]
