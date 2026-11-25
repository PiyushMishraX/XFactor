"""HTTP surface for the LangGraph supervisor (Step 4).

The endpoints expose the workflow:

* ``POST /orchestration/workflows`` — start a recovery run for one disruption.
* ``POST /orchestration/workflows/start`` — the dashboard's one-click Start: the
  bundled demo scenario under a fresh event id.
* ``GET  /orchestration/workflows/active`` — whether a run is in flight.
* ``GET  /orchestration/workflows/{thread_id}/state`` — read the last saved state.

Every start path is admitted through one process-wide single-flight guard, so
repeated clicks, extra tabs or the shipment form cannot run two workflows at
once and overload the five agents or the Gemini quota. A second start while a
run is in flight is refused with ``409``.

When a run pauses at the human gate, the pending approval is persisted so it
appears in ``GET /approvals/pending``. Approval decisions are **not** accepted
here: they live behind the authenticated ``/approvals`` API (Step 6), so an
unauthenticated request can never resume a paused workflow. All orchestration —
delegation, retries, routing, the approval gate — lives in the graph.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.orchestration.approvals import build_proposal_snapshot
from app.orchestration.state import RecoveryRequest
from app.orchestration.workflow import pending_interrupt, supervisor_runtime
from app.services.approval_repository import PostgresApprovalRepository
from app.services.approval_service import record_pending_approval
from app.services.workflow_guard import WorkflowBusyError, WorkflowGuard
from app.services.workflow_history import record_workflow_run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestration", tags=["Orchestration"])

#: The validated demo scenario used by the one-click Start button.
DEMO_SCENARIO_PATH = (
    Path(__file__).resolve().parents[2] / "demo" / "mumbai_rotterdam_scenario.json"
)

#: Process-wide admission control: one supervisor run at a time.
WORKFLOW_GUARD = WorkflowGuard()


class WorkflowInvocation(BaseModel):
    """Body for starting a workflow."""

    model_config = ConfigDict(str_strip_whitespace=True)

    request: RecoveryRequest = Field(description="The disruption and lane to recover.")
    thread_id: Optional[str] = Field(
        default=None,
        description=(
            "Checkpoint thread to run under. Defaults to the disruption event id, so "
            "re-submitting the same event continues the same thread."
        ),
    )


def _serialise(thread_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a raw graph result into a JSON-safe response.

    The raw result carries an ``__interrupt__`` key holding live LangGraph objects
    that do not serialise; the approval request is extracted into its own field
    and the raw key is dropped.
    """
    approval_request = pending_interrupt(state)
    snapshot = build_proposal_snapshot(thread_id, state)
    body: Dict[str, Any] = {
        "thread_id": thread_id,
        "status": state.get("status"),
        "awaiting_approval": approval_request is not None,
        "recommendation": state.get("recommendation"),
        "decision_log": state.get("decisions") or [],
        "errors": state.get("errors") or [],
        "missing_information": state.get("missing_information") or [],
        # Step 5 collaboration record
        "agent_executions": state.get("agent_executions") or [],
        "scenario_screening": state.get("scenario_screening"),
        "replanning": state.get("replanning") or [],
        "replanning_rounds": state.get("replan_rounds") or 0,
        "skipped_agents": state.get("skipped_agents") or [],
        # Step 6 human approval record
        "proposal_version": snapshot.proposal_version if snapshot is not None else None,
        "approval": state.get("approval"),
        "approval_history": state.get("approval_history") or [],
        "modification_rounds": state.get("modification_rounds") or 0,
    }
    if approval_request is not None:
        body["approval_request"] = approval_request
    return body


def _run_guarded(
    thread_id: str, request: RecoveryRequest, session: Session
) -> Dict[str, Any]:
    """Run one supervisor workflow while holding the single-flight slot."""
    try:
        WORKFLOW_GUARD.try_begin(thread_id)
    except WorkflowBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A supervisor workflow is already running for thread "
                f"{exc.active_thread_id!r}. Only one run is allowed at a time so the "
                "five agents cannot overload the Gemini quota; wait for it to finish "
                "and start again."
            ),
        ) from exc

    try:
        with supervisor_runtime(session=session) as workflow:
            result = workflow.invoke(request, thread_id=thread_id)

        if pending_interrupt(result) is not None:
            # Persist the queue item so an approver can find it. The checkpointed
            # graph remains the source of truth; recording failure is logged, not
            # hidden, and the approval API can rebuild the item from the checkpoint.
            try:
                record_pending_approval(
                    PostgresApprovalRepository(session), thread_id, result
                )
            except Exception:  # noqa: BLE001 - never lose a completed workflow result
                session.rollback()
                logger.exception(
                    "Could not persist the pending approval for thread %s", thread_id
                )

        try:
            record_workflow_run(session, thread_id, result)
        except Exception:  # noqa: BLE001 - history must not lose a workflow result
            session.rollback()
            logger.exception("Could not record the workflow run for thread %s", thread_id)

        return _serialise(thread_id, result)
    finally:
        WORKFLOW_GUARD.end()


def _one_shot_invocation() -> tuple[str, RecoveryRequest]:
    """Load the bundled demo scenario under a fresh event id for one UI run."""
    event_id = (
        f"EV-UI-START-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-"
        f"{uuid.uuid4().hex[:6]}"
    )
    try:
        payload = json.loads(DEMO_SCENARIO_PATH.read_text(encoding="utf-8"))
        request_payload = payload["request"]
        request_payload["disruption_report"]["event_id"] = event_id
        request_payload["scenario_request"]["event_id"] = event_id
        request = RecoveryRequest.model_validate(request_payload)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.exception("Could not load the bundled demo scenario for a one-shot run.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The bundled demo scenario is unavailable, so no run was started.",
        ) from exc
    return event_id, request


@router.get(
    "/workflows/active",
    summary="Whether a supervisor run is currently in flight",
)
def active_workflow() -> Dict[str, Any]:
    """Report the single-flight slot so the UI can disable its Start button."""
    thread_id = WORKFLOW_GUARD.active_thread_id
    return {"running": thread_id is not None, "thread_id": thread_id}


@router.post(
    "/workflows",
    summary="Start a supervisor workflow",
    status_code=status.HTTP_200_OK,
)
def start_workflow(
    body: WorkflowInvocation, session: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Run one disruption through the supervisor.

    Returns the recommendation when the run completes, or the approval request
    when it pauses at the human gate. A second concurrent run is refused with
    ``409`` so overlapping starts cannot overload the agent/Gemini capacity.
    """
    thread_id = body.thread_id or body.request.scenario_request.event_id
    if not thread_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A thread_id is required when the disruption has no event id.",
        )
    return _run_guarded(thread_id, body.request, session)


@router.post(
    "/workflows/start",
    summary="Start one five-agent run from the bundled scenario",
    status_code=status.HTTP_200_OK,
)
def start_one_shot(session: Session = Depends(get_db)) -> Dict[str, Any]:
    """One-click start used by the dashboard's Start button.

    It runs the validated Red Sea scenario exactly once under a fresh event id.
    The single-flight guard refuses a second start while this run is in flight.
    """
    thread_id, request = _one_shot_invocation()
    return _run_guarded(thread_id, request, session)


@router.get(
    "/workflows/{thread_id}/state",
    summary="Read the saved workflow state",
)
def read_workflow_state(
    thread_id: str, session: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Return the last checkpointed state for a thread."""
    with supervisor_runtime(session=session) as workflow:
        snapshot = workflow.snapshot(thread_id=thread_id)
    values = dict(getattr(snapshot, "values", None) or {})
    if not values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No saved state for thread {thread_id!r}.",
        )
    return {
        "thread_id": thread_id,
        "next": list(getattr(snapshot, "next", None) or []),
        "values": values,
    }
