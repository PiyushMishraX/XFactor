"""Persistence for the human approval queue (Step 6).

The approval coordinator depends on the :class:`ApprovalRepository` protocol, so
the API can use PostgreSQL while tests use the in-memory implementation. Both
implement the same semantics:

* a thread has one *current* proposal; recording a new proposal version keeps
  the existing decision history and clears the previous execution report;
* a decision appends one immutable :class:`ApprovalDecisionRecord` to the
  history and moves the status;
* an execution report is stored only for the proposal version that was executed,
  which is what makes duplicate execution detectable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.approvals import ApprovalRequestRow
from app.schemas.approval_schemas import (
    ApprovalDecisionRecord,
    ApprovalRequestView,
    ApprovalStatus,
    ProposalSnapshot,
)
from app.schemas.execution_schemas import ExecutionReport

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _copy(view: ApprovalRequestView) -> ApprovalRequestView:
    """A deep, detached copy so callers cannot mutate the stored queue item."""
    return ApprovalRequestView.model_validate(view.model_dump(mode="json"))


class ApprovalRepository(Protocol):
    """The approval queue operations the coordinator needs."""

    def upsert_pending(self, view: ApprovalRequestView) -> ApprovalRequestView:
        """Insert or refresh the thread's current proposal, preserving history."""
        ...

    def get(self, thread_id: str) -> Optional[ApprovalRequestView]:
        """Return the thread's queue item, or ``None``."""
        ...

    def list_pending(self) -> List[ApprovalRequestView]:
        """Return every item still waiting for a decision."""
        ...

    def add_decision(
        self,
        thread_id: str,
        decision: ApprovalDecisionRecord,
        status: ApprovalStatus,
        workflow_status: str = "",
    ) -> ApprovalRequestView:
        """Append one decision record and move the item's status."""
        ...

    def save_execution(self, thread_id: str, report: ExecutionReport) -> ApprovalRequestView:
        """Store the execution report for the thread's current proposal version."""
        ...

    def get_execution(self, thread_id: str, proposal_version: str) -> Optional[ExecutionReport]:
        """Return the stored report only when it belongs to ``proposal_version``."""
        ...


class PostgresApprovalRepository:
    """Approval queue persisted in the ``approval_requests`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_pending(self, view: ApprovalRequestView) -> ApprovalRequestView:
        row = self._session.get(ApprovalRequestRow, view.thread_id)
        now = _utc_now()
        if row is None:
            row = ApprovalRequestRow(
                thread_id=view.thread_id,
                event_id=view.event_id,
                proposal_id=view.proposal_id,
                proposal_version=view.proposal_version,
                approval_level=view.approval_level,
                status=ApprovalStatus.PENDING.value,
                proposal_json=view.proposal.model_dump_json(),
                decision_history_json=json.dumps(
                    [record.model_dump(mode="json") for record in view.decision_history]
                ),
                execution_json=(
                    view.execution.model_dump_json() if view.execution is not None else None
                ),
                created_at=view.created_at,
                updated_at=now,
            )
            self._session.add(row)
            self._session.commit()
            return _to_view(row)

        if row.proposal_version == view.proposal_version and row.status != ApprovalStatus.PENDING.value:
            # The proposal is already decided. Refresh the displayed snapshot but
            # never reopen a decided item by re-recording it.
            row.proposal_json = view.proposal.model_dump_json()
            row.updated_at = now
            self._session.commit()
            return _to_view(row)

        if row.proposal_version != view.proposal_version:
            # A new proposal version (after requested modifications) starts a new
            # review; the previous execution report no longer applies.
            row.execution_json = None
        row.event_id = view.event_id
        row.proposal_id = view.proposal_id
        row.proposal_version = view.proposal_version
        row.approval_level = view.approval_level
        row.status = ApprovalStatus.PENDING.value
        row.proposal_json = view.proposal.model_dump_json()
        row.updated_at = now
        self._session.commit()
        return _to_view(row)

    def get(self, thread_id: str) -> Optional[ApprovalRequestView]:
        row = self._session.get(ApprovalRequestRow, thread_id)
        return _to_view(row) if row is not None else None

    def list_pending(self) -> List[ApprovalRequestView]:
        statement = (
            select(ApprovalRequestRow)
            .where(ApprovalRequestRow.status == ApprovalStatus.PENDING.value)
            .order_by(ApprovalRequestRow.created_at)
        )
        return [_to_view(row) for row in self._session.execute(statement).scalars()]

    def add_decision(
        self,
        thread_id: str,
        decision: ApprovalDecisionRecord,
        status: ApprovalStatus,
        workflow_status: str = "",
    ) -> ApprovalRequestView:
        row = self._require(thread_id)
        record = decision.model_copy(update={"workflow_status": workflow_status})
        history = _decode_history(row.decision_history_json)
        history.append(record)
        row.decision_history_json = json.dumps(
            [item.model_dump(mode="json") for item in history]
        )
        row.status = status.value
        row.updated_at = _utc_now()
        self._session.commit()
        return _to_view(row)

    def save_execution(self, thread_id: str, report: ExecutionReport) -> ApprovalRequestView:
        row = self._require(thread_id)
        row.execution_json = report.model_dump_json()
        row.updated_at = _utc_now()
        self._session.commit()
        return _to_view(row)

    def get_execution(self, thread_id: str, proposal_version: str) -> Optional[ExecutionReport]:
        row = self._session.get(ApprovalRequestRow, thread_id)
        if row is None or not row.execution_json:
            return None
        report = ExecutionReport.model_validate_json(row.execution_json)
        return report if report.proposal_version == proposal_version else None

    def _require(self, thread_id: str) -> ApprovalRequestRow:
        row = self._session.get(ApprovalRequestRow, thread_id)
        if row is None:
            raise KeyError(f"No approval request exists for thread {thread_id!r}.")
        return row


class InMemoryApprovalRepository:
    """The same approval queue semantics without a database."""

    def __init__(self) -> None:
        self._items: Dict[str, ApprovalRequestView] = {}

    def upsert_pending(self, view: ApprovalRequestView) -> ApprovalRequestView:
        current = self._items.get(view.thread_id)
        if (
            current is not None
            and current.proposal_version == view.proposal_version
            and current.status is not ApprovalStatus.PENDING
        ):
            updated = _copy(current)
            updated.proposal = view.proposal
            updated.updated_at = _utc_now()
            self._items[view.thread_id] = updated
            return _copy(updated)

        updated = _copy(view)
        if current is not None:
            updated.decision_history = list(current.decision_history)
            updated.created_at = current.created_at
            if current.proposal_version != view.proposal_version:
                updated.execution = None
        updated.status = ApprovalStatus.PENDING
        updated.updated_at = _utc_now()
        self._items[view.thread_id] = updated
        return _copy(updated)

    def get(self, thread_id: str) -> Optional[ApprovalRequestView]:
        item = self._items.get(thread_id)
        return _copy(item) if item is not None else None

    def list_pending(self) -> List[ApprovalRequestView]:
        return [
            _copy(item)
            for item in sorted(self._items.values(), key=lambda entry: entry.created_at)
            if item.status is ApprovalStatus.PENDING
        ]

    def add_decision(
        self,
        thread_id: str,
        decision: ApprovalDecisionRecord,
        status: ApprovalStatus,
        workflow_status: str = "",
    ) -> ApprovalRequestView:
        current = self._items.get(thread_id)
        if current is None:
            raise KeyError(f"No approval request exists for thread {thread_id!r}.")
        updated = _copy(current)
        updated.decision_history.append(
            decision.model_copy(update={"workflow_status": workflow_status})
        )
        updated.status = status
        updated.updated_at = _utc_now()
        self._items[thread_id] = updated
        return _copy(updated)

    def save_execution(self, thread_id: str, report: ExecutionReport) -> ApprovalRequestView:
        current = self._items.get(thread_id)
        if current is None:
            raise KeyError(f"No approval request exists for thread {thread_id!r}.")
        updated = _copy(current)
        updated.execution = report
        updated.updated_at = _utc_now()
        self._items[thread_id] = updated
        return _copy(updated)

    def get_execution(self, thread_id: str, proposal_version: str) -> Optional[ExecutionReport]:
        item = self._items.get(thread_id)
        if item is None or item.execution is None:
            return None
        if item.execution.proposal_version != proposal_version:
            return None
        return ExecutionReport.model_validate(item.execution.model_dump(mode="json"))


def _decode_history(payload: str) -> List[ApprovalDecisionRecord]:
    return [
        ApprovalDecisionRecord.model_validate(item) for item in json.loads(payload or "[]")
    ]


def _to_view(row: ApprovalRequestRow) -> ApprovalRequestView:
    return ApprovalRequestView(
        thread_id=row.thread_id,
        event_id=row.event_id,
        proposal_id=row.proposal_id,
        proposal_version=row.proposal_version,
        approval_level=row.approval_level,
        status=ApprovalStatus(row.status),
        proposal=ProposalSnapshot.model_validate_json(row.proposal_json),
        decision_history=_decode_history(row.decision_history_json),
        execution=(
            ExecutionReport.model_validate_json(row.execution_json)
            if row.execution_json
            else None
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def ensure_approval_schema(engine: Engine) -> None:
    """Create the approval table when it is missing. Safe to call at startup."""
    ApprovalRequestRow.__table__.create(bind=engine, checkfirst=True)


__all__ = [
    "ApprovalRepository",
    "InMemoryApprovalRepository",
    "PostgresApprovalRepository",
    "ensure_approval_schema",
]
