"""HTTP surface for the LangGraph supervisor (Step 4).

Three endpoints expose the workflow:

* ``POST /orchestration/workflows`` — start a recovery run for one disruption.
* ``POST /orchestration/workflows/{thread_id}/resume`` — answer the approval gate
  of a paused run and let it continue from its saved checkpoint.
* ``GET  /orchestration/workflows/{thread_id}/state`` — read the last saved state.

The endpoints stay deliberately thin: they translate HTTP into
:class:`~app.orchestration.workflow.SupervisorWorkflow` calls and back. All
orchestration — delegation, retries, routing, the approval gate — lives in the
graph. The workflow is built with the configured checkpointer, so a run paused at
the approval gate can be resumed by a later request.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.orchestration.state import RecoveryRequest
from app.orchestration.workflow import pending_interrupt, supervisor_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestration", tags=["Orchestration"])


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


class ApprovalDecision(BaseModel):
    """Body for resuming an interrupted workflow."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approved: bool = Field(description="Whether the human approves the proposal.")
    comment: str = Field(default="", description="Reason or note attached to the decision.")


def _serialise(thread_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a raw graph result into a JSON-safe response.

    The raw result carries an ``__interrupt__`` key holding live LangGraph objects
    that do not serialise; the approval request is extracted into its own field
    and the raw key is dropped.
    """
    approval_request = pending_interrupt(state)
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
    }
    if approval_request is not None:
        body["approval_request"] = approval_request
    return body


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
    when it pauses at the human gate.
    """
    thread_id = body.thread_id or body.request.scenario_request.event_id
    if not thread_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A thread_id is required when the disruption has no event id.",
        )
    with supervisor_runtime(session=session) as workflow:
        result = workflow.invoke(body.request, thread_id=thread_id)
    return _serialise(thread_id, result)


@router.post(
    "/workflows/{thread_id}/resume",
    summary="Resume an interrupted workflow",
    status_code=status.HTTP_200_OK,
)
def resume_workflow(
    thread_id: str, body: ApprovalDecision, session: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Answer the approval gate and continue the run from its checkpoint."""
    with supervisor_runtime(session=session) as workflow:
        snapshot = workflow.snapshot(thread_id=thread_id)
        if not getattr(snapshot, "next", None):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Thread {thread_id!r} is not paused at an approval gate.",
            )
        result = workflow.resume(
            {"approved": body.approved, "comment": body.comment}, thread_id=thread_id
        )
    return _serialise(thread_id, result)


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
