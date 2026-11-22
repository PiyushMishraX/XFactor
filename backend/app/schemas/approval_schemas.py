"""Structured records for the human approval loop (Step 6).

These models make the human decision *auditable* and *version-bound*:

* :class:`ProposalSnapshot` is the exact proposal a human reviewed. Its
  ``proposal_version`` is a SHA-256 digest of the proposal's deterministic
  fields, so an approval can be validated against the proposal that is current
  when it arrives. A different proposal means a different version.
* :class:`ApproverIdentity` is the authenticated person and role. It is never
  read from the request body — the API derives it from a bearer credential.
* :class:`ApprovalDecisionRecord` records who decided what, when, on which
  proposal version and with what comment.
* :class:`ApprovalRequestView` is the persisted queue item the approval
  interface reads: the proposal, its status, the full decision history and any
  execution report.

Approval actions are deliberately three-valued: approve, reject, or request
modifications. Only ``approve`` may authorise execution.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.execution_schemas import ExecutionReport


class ApprovalAction(str, Enum):
    """What an authorized reviewer did with a proposal."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_MODIFICATIONS = "request_modifications"


class ApprovalStatus(str, Enum):
    """Lifecycle of one approval queue item."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFICATIONS_REQUESTED = "modifications_requested"


class ApproverRole(str, Enum):
    """Roles that may authenticate against the approval API."""

    MANAGER = "Manager"
    DIRECTOR = "Director"
    ADMIN = "Admin"

    @property
    def rank(self) -> int:
        return {"Manager": 1, "Director": 2, "Admin": 3}[self.value]


#: The minimum role a named approval level requires.
_REQUIRED_RANK = {"Manager": 1, "Director": 2}

#: Fields that identify or timestamp the review, not the proposal itself.
_VERSION_EXCLUDED = frozenset({"thread_id", "proposal_version", "created_at"})


class ApproverIdentity(BaseModel):
    """An authenticated approver, derived from a bearer credential."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    approver_id: str = Field(min_length=1)
    role: ApproverRole

    @property
    def rank(self) -> int:
        return self.role.rank

    def can_approve(self, approval_level: Optional[str]) -> bool:
        """Whether this role may decide at the proposal's approval level.

        An empty level needs a valid credential but no particular rank. An
        unrecognised level is treated as the strictest (Admin only).
        """
        level = (approval_level or "").strip()
        if not level:
            return True
        required = _REQUIRED_RANK.get(level.title(), ApproverRole.ADMIN.rank)
        return self.rank >= required


class ProposalSnapshot(BaseModel):
    """The exact proposal a human reviews, with a deterministic version digest."""

    model_config = ConfigDict(str_strip_whitespace=True)

    thread_id: str = Field(default="", description="Workflow thread; excluded from the version.")
    event_id: str
    proposal_id: str
    proposal_version: str = Field(
        default="", description="SHA-256 prefix over the proposal fields below."
    )
    approval_level: str = ""
    requires_approval: bool = True
    verdict: str = ""
    is_compliant: bool = True
    is_within_budget: bool = True
    reasons: List[str] = Field(default_factory=list)
    violations: List[str] = Field(default_factory=list)
    headline: str = ""
    summary: str = ""
    recommended_scenario_id: Optional[str] = None
    recommended_route_id: Optional[str] = None
    recommended_carrier: Optional[str] = None
    transport_mode: Optional[str] = None
    total_cost_usd: float = 0.0
    total_days: float = 0.0
    shipment_value_usd: float = 0.0
    inventory_transfer_units: float = 0.0
    supplier_id: str = ""
    carrier_change_requested: bool = False
    actions: List[str] = Field(
        default_factory=list, description="Deterministic execution action types."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def version_payload(self) -> Dict[str, Any]:
        """The canonical, review-relevant fields the version is computed from."""
        return self.model_dump(mode="json", exclude=set(_VERSION_EXCLUDED))

    def compute_version(self) -> str:
        """Return a stable short digest of the proposal's deterministic fields.

        ``sort_keys`` and a fixed separator make the digest independent of field
        order, so the workflow and the API always agree on the same version.
        """
        canonical = json.dumps(
            self.version_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def with_version(self) -> "ProposalSnapshot":
        """Return a copy carrying the freshly computed version."""
        return self.model_copy(update={"proposal_version": self.compute_version()})


class ApprovalDecisionRequest(BaseModel):
    """The body of a decision request. The approver identity is *not* part of it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: ApprovalAction
    comment: str = Field(default="", description="Reason or modification instructions.")
    proposal_version: str = Field(
        min_length=1,
        description="The version the reviewer saw; a stale version is rejected.",
    )


class ApprovalDecisionRecord(BaseModel):
    """One authenticated human decision, with identity, time and proposal version."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: ApprovalAction
    approver_id: str
    approver_role: str = ""
    comment: str = ""
    proposal_version: str = ""
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workflow_status: str = ""

    @property
    def approved(self) -> bool:
        return self.action is ApprovalAction.APPROVE

    def status(self) -> ApprovalStatus:
        return {
            ApprovalAction.APPROVE: ApprovalStatus.APPROVED,
            ApprovalAction.REJECT: ApprovalStatus.REJECTED,
            ApprovalAction.REQUEST_MODIFICATIONS: ApprovalStatus.MODIFICATIONS_REQUESTED,
        }[self.action]


class ApprovalRequestView(BaseModel):
    """A persisted approval queue item: the proposal, its state and its history."""

    thread_id: str
    event_id: str
    proposal_id: str
    proposal_version: str
    approval_level: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    proposal: ProposalSnapshot
    decision_history: List[ApprovalDecisionRecord] = Field(default_factory=list)
    execution: Optional[ExecutionReport] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalDecisionOutcome(BaseModel):
    """What happened when a decision was submitted."""

    thread_id: str
    action: ApprovalAction
    approval_status: ApprovalStatus
    workflow_status: str = ""
    proposal_version: str = ""
    awaiting_approval: bool = False
    decision: ApprovalDecisionRecord
    execution: Optional[ExecutionReport] = None
    recommendation: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)
    view: ApprovalRequestView


__all__ = [
    "ApprovalAction",
    "ApprovalDecisionOutcome",
    "ApprovalDecisionRecord",
    "ApprovalDecisionRequest",
    "ApprovalRequestView",
    "ApprovalStatus",
    "ApproverIdentity",
    "ApproverRole",
    "ProposalSnapshot",
]
