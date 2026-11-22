"""Authenticated human-approval API (Step 6).

Every endpoint requires ``Authorization: Bearer <token>`` where the token is one
of the ``APPROVER_CREDENTIALS`` entries. An unauthenticated request can read
nothing and decide nothing; there is deliberately no anonymous queue.

* ``GET  /approvals/pending`` — the proposals waiting for a decision.
* ``GET  /approvals/{thread_id}`` — one proposal with its full decision history.
* ``POST /approvals/{thread_id}/decision`` — approve, reject or request changes.
  The body carries an action, a comment and the proposal version the reviewer
  saw; it never carries an approver identity or an approval status.
* ``GET  /approvals/{thread_id}/execution`` — the execution report produced after
  an approval.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.session import get_db
from app.integrations.base import IntegrationNotConfiguredError
from app.orchestration.state import NODE_APPROVAL_GATE
from app.orchestration.workflow import supervisor_runtime
from app.schemas.approval_schemas import (
    ApprovalDecisionOutcome,
    ApprovalDecisionRequest,
    ApprovalRequestView,
    ApproverIdentity,
)
from app.services.approval_auth import (
    ApprovalAuthorizer,
    ApprovalConfigurationError,
    ApproverAuthenticationError,
    ApproverAuthorizationError,
    extract_bearer_token,
)
from app.services.approval_repository import (
    ApprovalRepository,
    PostgresApprovalRepository,
)
from app.services.approval_service import (
    ApprovalConflictError,
    ApprovalNotFoundError,
    ApprovalService,
)
from app.services.execution import ExecutionAdapter, ExecutionService, get_execution_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["Approvals"])


# ---------------------------------------------------------------------------
# Dependencies (overridable in tests)
# ---------------------------------------------------------------------------


def approval_repository(session: Session = Depends(get_db)) -> ApprovalRepository:
    return PostgresApprovalRepository(session)


def approval_authorizer() -> ApprovalAuthorizer:
    return ApprovalAuthorizer(settings=get_settings())


def execution_adapter() -> ExecutionAdapter:
    try:
        return get_execution_adapter(get_settings())
    except IntegrationNotConfiguredError as exc:
        # Dependencies resolve before the endpoint's own try/except, so the
        # configuration failure is mapped here to keep the 503 contract.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _http_error(exc: Exception) -> HTTPException:
    """Translate a domain error into an HTTP response without leaking detail."""
    if isinstance(exc, ApprovalConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ApproverAuthenticationError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(exc, ApproverAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ApprovalNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ApprovalConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, IntegrationNotConfiguredError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _authenticate(
    authorizer: ApprovalAuthorizer, authorization: Optional[str]
) -> ApproverIdentity:
    return authorizer.authenticate(extract_bearer_token(authorization))


def _view_payload(view: ApprovalRequestView) -> Dict[str, Any]:
    return view.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/pending", summary="List proposals awaiting a decision")
def list_pending(
    authorization: Optional[str] = Header(default=None),
    repository: ApprovalRepository = Depends(approval_repository),
    authorizer: ApprovalAuthorizer = Depends(approval_authorizer),
) -> Dict[str, Any]:
    """Return every pending approval item. Requires an authenticated approver."""
    try:
        _authenticate(authorizer, authorization)
        views: List[ApprovalRequestView] = repository.list_pending()
    except Exception as exc:  # noqa: BLE001 - mapped to an HTTP status
        raise _http_error(exc) from exc
    return {"count": len(views), "pending": [_view_payload(view) for view in views]}


@router.get("/{thread_id}", summary="Read one approval proposal and its history")
def get_approval(
    thread_id: str,
    authorization: Optional[str] = Header(default=None),
    repository: ApprovalRepository = Depends(approval_repository),
    authorizer: ApprovalAuthorizer = Depends(approval_authorizer),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return the queue item, rebuilding it from the checkpoint when necessary."""
    try:
        _authenticate(authorizer, authorization)
        view = repository.get(thread_id)
        if view is None:
            view = _rebuild_from_checkpoint(thread_id, repository, authorizer, session)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return _view_payload(view)


@router.post("/{thread_id}/decision", summary="Approve, reject or request modifications")
def decide(
    thread_id: str,
    body: ApprovalDecisionRequest,
    authorization: Optional[str] = Header(default=None),
    repository: ApprovalRepository = Depends(approval_repository),
    authorizer: ApprovalAuthorizer = Depends(approval_authorizer),
    adapter: ExecutionAdapter = Depends(execution_adapter),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Apply an authenticated decision and, on approval, execute the proposal."""
    try:
        _authenticate(authorizer, authorization)
        with supervisor_runtime(session=session) as workflow:
            service = ApprovalService(
                repository=repository,
                authorizer=authorizer,
                execution=ExecutionService(adapter=adapter, store=repository),
            )
            outcome: ApprovalDecisionOutcome = service.decide(
                thread_id=thread_id,
                authorization=authorization,
                request=body,
                workflow=workflow,
            )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return outcome.model_dump(mode="json")


@router.get("/{thread_id}/execution", summary="Read the execution report")
def get_execution(
    thread_id: str,
    authorization: Optional[str] = Header(default=None),
    repository: ApprovalRepository = Depends(approval_repository),
    authorizer: ApprovalAuthorizer = Depends(approval_authorizer),
) -> Dict[str, Any]:
    """Return the execution report for the thread, when one exists."""
    try:
        _authenticate(authorizer, authorization)
        view = repository.get(thread_id)
        if view is None:
            raise ApprovalNotFoundError(
                f"No approval request exists for thread {thread_id!r}."
            )
        if view.execution is None:
            raise ApprovalNotFoundError(
                f"No execution report exists for thread {thread_id!r}."
            )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return view.execution.model_dump(mode="json")


def _rebuild_from_checkpoint(
    thread_id: str,
    repository: ApprovalRepository,
    authorizer: ApprovalAuthorizer,
    session: Session,
) -> ApprovalRequestView:
    with supervisor_runtime(session=session) as workflow:
        snapshot = workflow.snapshot(thread_id=thread_id)
    values = dict(getattr(snapshot, "values", None) or {})
    next_nodes = list(getattr(snapshot, "next", None) or [])
    if not values or NODE_APPROVAL_GATE not in next_nodes:
        raise ApprovalNotFoundError(
            f"No approval request exists for thread {thread_id!r}."
        )
    service = ApprovalService(repository=repository, authorizer=authorizer)
    return service.record_pending(thread_id, values)


__all__ = [
    "approval_authorizer",
    "approval_repository",
    "execution_adapter",
    "router",
]
