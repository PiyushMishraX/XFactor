"""Workflow run history for the control-tower dashboard (Step 8).

A row is recorded after every supervisor invocation and refreshed after every
authenticated approval decision. The summary columns answer "what happened" for
lists and KPIs; ``state_json`` carries the JSON-safe workflow state the Agent
Activity, Scenario Comparison and Audit pages render.

The recording function accepts a raw graph result (including LangGraph's
``__interrupt__`` key) and strips it, so callers never have to pre-process the
state. Writing a run is best-effort: a history failure is logged and must never
lose a completed workflow.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.workflow_runs import WorkflowRunRow
from app.orchestration.state import (
    STATUS_APPROVAL_REJECTED,
    STATUS_AWAITING_APPROVAL,
    STATUS_FAILED,
    STATUS_ITERATION_LIMIT,
    STATUS_NO_COMPLIANT_RECOVERY,
    STATUS_NO_FEASIBLE_RECOVERY,
)

logger = logging.getLogger(__name__)

#: Statuses that mean the run did not deliver a usable recovery.
FAILED_STATUSES = frozenset(
    {
        STATUS_FAILED,
        STATUS_ITERATION_LIMIT,
        STATUS_NO_COMPLIANT_RECOVERY,
        STATUS_NO_FEASIBLE_RECOVERY,
    }
)

#: Status of a run in which a human rejected the proposal.
REJECTED_STATUSES = frozenset({STATUS_APPROVAL_REJECTED})


def _utc_now() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


def json_safe(value: Any) -> Any:
    """Recursively reduce a workflow value to JSON-native data.

    LangGraph adds a live ``__interrupt__`` object that cannot serialise, and
    tuples/decimals can appear in nested payloads. Private keys are dropped and
    unknown objects fall back to their string form, never to a fabricated value.
    """
    if isinstance(value, Mapping):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
            if not str(key).startswith("__")
        }
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarise_state(thread_id: str, values: Mapping[str, Any]) -> Dict[str, Any]:
    """Derive the queryable summary fields from a recorded workflow state."""
    request = values.get("request") or {}
    scenario = request.get("scenario_request") or {}
    report = request.get("disruption_report") or {}
    assessment = values.get("assessment") or {}
    recommendation = values.get("recommendation") or {}
    plan = values.get("scenario_plan") or {}

    status = str(values.get("status") or recommendation.get("status") or "")
    executions = values.get("agent_executions") or []
    errors = values.get("errors") or []
    decision_count = _as_int(recommendation.get("iterations")) or 0

    return {
        "thread_id": thread_id,
        "event_id": str(
            assessment.get("event_id")
            or scenario.get("event_id")
            or report.get("event_id")
            or ""
        ),
        "disruption_type": str(
            assessment.get("disruption_type") or scenario.get("disruption_type") or ""
        ),
        "severity": str(assessment.get("severity") or scenario.get("severity") or ""),
        "location": str(assessment.get("location") or scenario.get("location") or ""),
        "origin": str(scenario.get("origin") or ""),
        "destination": str(scenario.get("destination") or ""),
        "status": status,
        "awaiting_approval": status == STATUS_AWAITING_APPROVAL,
        "risk_score": _as_int(assessment.get("risk_score")),
        "recommended_scenario_id": (
            recommendation.get("recommended_scenario_id")
            or plan.get("recommended_scenario_id")
        ),
        "headline": str(
            recommendation.get("headline")
            or report.get("headline")
            or assessment.get("description")
            or ""
        ),
        "summary": str(recommendation.get("summary") or assessment.get("description") or ""),
        "execution_count": len(executions) or decision_count,
        "error_count": len(errors),
    }


def _summary(row: WorkflowRunRow) -> Dict[str, Any]:
    return {
        "thread_id": row.thread_id,
        "event_id": row.event_id,
        "disruption_type": row.disruption_type,
        "severity": row.severity,
        "location": row.location,
        "origin": row.origin,
        "destination": row.destination,
        "status": row.status,
        "awaiting_approval": row.awaiting_approval,
        "risk_score": row.risk_score,
        "recommended_scenario_id": row.recommended_scenario_id,
        "headline": row.headline,
        "summary": row.summary,
        "execution_count": row.execution_count,
        "error_count": row.error_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def record_workflow_run(
    session: Optional[Session], thread_id: str, state: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """Insert or refresh the history row for one workflow thread.

    ``session=None`` is a deliberate no-op used by API tests that inject no
    database; it keeps the approval endpoints independent of history storage.
    """
    if session is None or not thread_id:
        return None
    values = json_safe(state or {})
    if not values:
        return None
    summary = summarise_state(thread_id, values)
    now = _utc_now()

    row = session.get(WorkflowRunRow, thread_id)
    if row is None:
        row = WorkflowRunRow(thread_id=thread_id, created_at=now)
        session.add(row)

    row.event_id = summary["event_id"]
    row.disruption_type = summary["disruption_type"]
    row.severity = summary["severity"]
    row.location = summary["location"]
    row.origin = summary["origin"]
    row.destination = summary["destination"]
    row.status = summary["status"]
    row.awaiting_approval = summary["awaiting_approval"]
    row.risk_score = summary["risk_score"]
    row.recommended_scenario_id = summary["recommended_scenario_id"]
    row.headline = summary["headline"][:240]
    row.summary = summary["summary"]
    row.execution_count = summary["execution_count"]
    row.error_count = summary["error_count"]
    row.state_json = json.dumps(values, ensure_ascii=True, default=str)
    row.updated_at = now
    session.commit()
    return summary


def list_workflow_runs(
    session: Session, *, limit: int = 25, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return recent run summaries, newest update first."""
    statement = select(WorkflowRunRow)
    if status:
        statement = statement.where(WorkflowRunRow.status == status)
    statement = statement.order_by(WorkflowRunRow.updated_at.desc()).limit(limit)
    rows = session.execute(statement).scalars().all()
    return [_summary(row) for row in rows]


def get_workflow_run(session: Session, thread_id: str) -> Optional[Dict[str, Any]]:
    """Return one run with its recorded workflow state, or ``None``."""
    row = session.get(WorkflowRunRow, thread_id)
    if row is None:
        return None
    payload = _summary(row)
    try:
        state = json.loads(row.state_json or "{}")
    except json.JSONDecodeError:
        logger.warning("Workflow run %s has unreadable state_json.", thread_id)
        state = {}
    payload["state"] = state
    return payload


def run_status_counts(session: Session) -> Dict[str, Any]:
    """Aggregate run counts for the overview page."""
    rows = session.execute(select(WorkflowRunRow)).scalars().all()
    awaiting = sum(1 for row in rows if row.awaiting_approval)
    failed = sum(1 for row in rows if row.status in FAILED_STATUSES)
    rejected = sum(1 for row in rows if row.status in REJECTED_STATUSES)
    by_status: Dict[str, int] = {}
    for row in rows:
        key = row.status or "unknown"
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "runs": len(rows),
        "awaiting_approval": awaiting,
        "failed": failed,
        "rejected": rejected,
        "agent_executions": sum(row.execution_count for row in rows),
        "errors": sum(row.error_count for row in rows),
        "by_status": by_status,
    }


def list_disruptions(session: Session, *, limit: int = 25) -> List[Dict[str, Any]]:
    """Recent disruptions with the assessment and supervisor decision attached."""
    rows = (
        session.execute(
            select(WorkflowRunRow)
            .order_by(WorkflowRunRow.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    disruptions: List[Dict[str, Any]] = []
    for row in rows:
        try:
            state = json.loads(row.state_json or "{}")
        except json.JSONDecodeError:
            state = {}
        request = state.get("request") or {}
        report = request.get("disruption_report") or {}
        assessment = state.get("assessment") or {}
        recommendation = state.get("recommendation") or {}
        decisions = state.get("decisions") or []
        latest = decisions[-1] if decisions else {}
        disruptions.append(
            {
                **_summary(row),
                "reported_headline": str(report.get("headline") or ""),
                "source": str(report.get("source") or ""),
                "affected_shipments": list(assessment.get("affected_shipments") or []),
                "affected_suppliers": list(assessment.get("affected_suppliers") or []),
                "risk_breakdown": assessment.get("risk_breakdown") or {},
                "potential_impact": list(assessment.get("potential_impact") or []),
                "supervisor_decision": {
                    "step": latest.get("step"),
                    "action": latest.get("action"),
                    "reason": latest.get("reason"),
                }
                if latest
                else None,
                "recommendation": {
                    "headline": recommendation.get("headline"),
                    "status": recommendation.get("status"),
                    "requires_approval": recommendation.get("requires_approval"),
                }
                if recommendation
                else None,
            }
        )
    return disruptions


def ensure_workflow_run_schema(engine: Engine) -> None:
    """Create the workflow history table when it is missing. Idempotent."""
    WorkflowRunRow.__table__.create(bind=engine, checkfirst=True)


__all__ = [
    "FAILED_STATUSES",
    "REJECTED_STATUSES",
    "ensure_workflow_run_schema",
    "get_workflow_run",
    "json_safe",
    "list_disruptions",
    "list_workflow_runs",
    "record_workflow_run",
    "run_status_counts",
    "summarise_state",
]
