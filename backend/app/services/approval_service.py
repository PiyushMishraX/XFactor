"""Coordination of the human approval loop (Step 6).

:class:`ApprovalService` is the only place where a decision, the workflow resume
and execution meet. Its order of operations is the security model:

1. authenticate the bearer token and bind the decision to the authenticated
   approver;
2. load the queue item and confirm the workflow is actually paused at the
   approval gate;
3. compare the submitted proposal version with both the stored proposal and the
   workflow's *current* proposal — a stale approval never resumes a newer plan;
4. enforce the role hierarchy for the proposal's approval level;
5. resume the graph, record the decision with identity and timestamp;
6. execute only after an ``approve`` decision produced a completed workflow, and
   only through the idempotent :class:`~app.services.execution.ExecutionService`;
7. if the graph is paused again on a modified proposal, record the new version as
   a fresh pending item while preserving the decision history.

Nothing here trusts a status supplied by the caller: the caller supplies an
action and a version, and the service derives everything else.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.orchestration.approvals import (
    build_proposal_snapshot,
    build_resume_payload,
    parse_approval_decision,
)
from app.orchestration.state import NODE_APPROVAL_GATE, STATUS_APPROVAL_REJECTED, STATUS_COMPLETED
from app.schemas.approval_schemas import (
    ApprovalAction,
    ApprovalDecisionOutcome,
    ApprovalDecisionRequest,
    ApprovalRequestView,
    ApprovalStatus,
)
from app.services.approval_auth import (
    ApprovalAuthorizer,
    extract_bearer_token,
)
from app.services.approval_repository import ApprovalRepository
from app.services.execution import ExecutionNotAuthorizedError, ExecutionService

logger = logging.getLogger(__name__)


class ApprovalNotFoundError(RuntimeError):
    """No approval item or paused workflow exists for the thread."""


class ApprovalConflictError(RuntimeError):
    """The thread is not in a state where this decision can be applied."""


class ProposalVersionMismatchError(ApprovalConflictError):
    """The decision targets a proposal version that is no longer current."""


class ApprovalService:
    """Record pending proposals and apply authenticated decisions."""

    def __init__(
        self,
        *,
        repository: ApprovalRepository,
        authorizer: ApprovalAuthorizer,
        execution: Optional[ExecutionService] = None,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer
        self._execution = execution

    # -- queue -----------------------------------------------------------

    def record_pending(self, thread_id: str, state: Dict[str, Any]) -> ApprovalRequestView:
        """Persist the proposal in ``state`` as the thread's pending item."""
        snapshot = build_proposal_snapshot(thread_id, state)
        if snapshot is None:
            raise ApprovalNotFoundError(
                f"The workflow for thread {thread_id!r} has no audited proposal to approve."
            )
        view = ApprovalRequestView(
            thread_id=thread_id,
            event_id=snapshot.event_id,
            proposal_id=snapshot.proposal_id,
            proposal_version=snapshot.proposal_version,
            approval_level=snapshot.approval_level,
            status=ApprovalStatus.PENDING,
            proposal=snapshot,
        )
        return self._repository.upsert_pending(view)

    def pending(self) -> List[ApprovalRequestView]:
        return self._repository.list_pending()

    def get(self, thread_id: str) -> ApprovalRequestView:
        view = self._repository.get(thread_id)
        if view is None:
            raise ApprovalNotFoundError(
                f"No approval request exists for thread {thread_id!r}."
            )
        return view

    def ensure_recorded(self, thread_id: str, state: Dict[str, Any]) -> ApprovalRequestView:
        """Return the stored item, recording ``state`` when it is missing."""
        existing = self._repository.get(thread_id)
        if existing is not None:
            return existing
        return self.record_pending(thread_id, state)

    # -- decisions -------------------------------------------------------

    def decide(
        self,
        *,
        thread_id: str,
        authorization: Optional[str],
        request: ApprovalDecisionRequest,
        workflow: Any,
    ) -> ApprovalDecisionOutcome:
        """Authenticate, validate, resume, record and (on approval) execute."""
        identity = self._authorizer.authenticate(extract_bearer_token(authorization))

        state, next_nodes = _paused_state(workflow, thread_id)
        if NODE_APPROVAL_GATE not in next_nodes:
            raise ApprovalConflictError(
                f"Thread {thread_id!r} is not paused at an approval gate."
            )
        current = build_proposal_snapshot(thread_id, state)
        if current is None:
            raise ApprovalNotFoundError(
                f"The paused workflow for thread {thread_id!r} has no audited proposal."
            )

        view = self.ensure_recorded(thread_id, state)
        if view.status is not ApprovalStatus.PENDING:
            raise ApprovalConflictError(
                f"Thread {thread_id!r} already has a '{view.status.value}' decision for "
                f"proposal version {view.proposal_version}."
            )
        if request.proposal_version != view.proposal_version:
            raise ProposalVersionMismatchError(
                f"The decision targets proposal version {request.proposal_version!r}, but "
                f"the stored proposal is {view.proposal_version!r}. Reload the proposal "
                f"before deciding."
            )
        if current.proposal_version != view.proposal_version:
            raise ProposalVersionMismatchError(
                f"The workflow's current proposal ({current.proposal_version!r}) differs "
                f"from the stored proposal ({view.proposal_version!r}). Reload before "
                f"deciding."
            )

        self._authorizer.authorize(identity, view.approval_level)

        payload = build_resume_payload(
            action=request.action,
            comment=request.comment,
            proposal_version=view.proposal_version,
            identity=identity,
        )
        logger.info(
            "Approver %s (%s) submitted '%s' for thread %s, proposal %s",
            identity.approver_id,
            identity.role.value,
            request.action.value,
            thread_id,
            view.proposal_version,
        )
        result = workflow.resume(payload, thread_id=thread_id)
        workflow_status = str(result.get("status") or "")
        decision = parse_approval_decision(payload)

        status = decision.status()
        if (
            request.action is ApprovalAction.REQUEST_MODIFICATIONS
            and workflow_status == STATUS_APPROVAL_REJECTED
        ):
            # The bounded reconsideration loop is exhausted; the workflow closed.
            status = ApprovalStatus.REJECTED

        view = self._repository.add_decision(
            thread_id, decision, status, workflow_status=workflow_status
        )

        execution = None
        errors: List[str] = list(result.get("errors") or [])
        if request.action is ApprovalAction.APPROVE and workflow_status == STATUS_COMPLETED:
            execution = self._execute(thread_id, view, errors)
            view = self._repository.save_execution(thread_id, execution)

        awaiting_approval = bool(_pending_interrupt(result))
        if awaiting_approval:
            # The reviewer asked for modifications and the revised proposal now
            # needs a fresh decision. The decision history is preserved.
            view = self.record_pending(thread_id, result)
            status = view.status

        return ApprovalDecisionOutcome(
            thread_id=thread_id,
            action=request.action,
            approval_status=status,
            workflow_status=workflow_status,
            proposal_version=view.proposal_version,
            awaiting_approval=awaiting_approval,
            decision=view.decision_history[-1],
            execution=view.execution,
            recommendation=result.get("recommendation"),
            errors=errors,
            view=view,
        )

    def _execute(
        self, thread_id: str, view: ApprovalRequestView, errors: List[str]
    ):
        if self._execution is None:
            errors.append(
                "The proposal was approved but no execution service is configured in this "
                "process, so no operational action was performed."
            )
            return None
        try:
            return self._execution.execute(view.proposal)
        except ExecutionNotAuthorizedError as exc:
            logger.error("Execution refused for thread %s: %s", thread_id, exc)
            errors.append(f"Execution refused: {exc}")
            return None


def _paused_state(workflow: Any, thread_id: str) -> Any:
    snapshot = workflow.snapshot(thread_id=thread_id)
    values = dict(getattr(snapshot, "values", None) or {})
    next_nodes = list(getattr(snapshot, "next", None) or [])
    return values, next_nodes


def _pending_interrupt(result: Dict[str, Any]) -> Any:
    interrupts = (result or {}).get("__interrupt__") or ()
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", None) or first


def record_pending_approval(
    repository: ApprovalRepository, thread_id: str, state: Dict[str, Any]
) -> Optional[ApprovalRequestView]:
    """Best-effort helper used when a workflow pauses; never fabricates a proposal."""
    snapshot = build_proposal_snapshot(thread_id, state)
    if snapshot is None:
        return None
    return repository.upsert_pending(
        ApprovalRequestView(
            thread_id=thread_id,
            event_id=snapshot.event_id,
            proposal_id=snapshot.proposal_id,
            proposal_version=snapshot.proposal_version,
            approval_level=snapshot.approval_level,
            status=ApprovalStatus.PENDING,
            proposal=snapshot,
        )
    )


__all__ = [
    "ApprovalConflictError",
    "ApprovalNotFoundError",
    "ApprovalService",
    "ProposalVersionMismatchError",
    "record_pending_approval",
]
