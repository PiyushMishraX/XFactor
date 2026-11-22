"""Structured input/output models for the Compliance & Audit Agent (Step 3).

The verdict is **never** decided by the LLM. ``AuditReport.verdict``,
``is_compliant``, ``is_within_budget`` and ``is_approved`` are all derived from the
deterministic engines in :mod:`app.tools.compliance`, :mod:`app.tools.budget` and
:mod:`app.tools.approval`. The LLM may only explain them — its response schema does
not even contain a verdict field, so it structurally cannot override a failure.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.tools.approval import ApprovalDecision, ApprovalPolicy
from app.tools.budget import BudgetValidation
from app.tools.compliance import ComplianceRule, RecoveryProposal, RuleFinding


class AuditVerdict(str, Enum):
    """The deterministic outcome of the audit."""

    APPROVED = "Approved"
    APPROVED_WITH_APPROVAL = "Approved subject to human approval"
    REJECTED = "Rejected"


class AuditRequest(BaseModel):
    """A recovery proposal submitted for compliance, budget and approval review."""

    model_config = ConfigDict(str_strip_whitespace=True)

    proposal: RecoveryProposal
    applicable_rules: List[ComplianceRule] = Field(
        min_length=1,
        description="The rules to validate against. An empty set is rejected upstream.",
    )
    available_budget_usd: float = Field(ge=0)
    action_type: str = Field(default="Recovery execution")
    shipment_value_usd: float = Field(default=0.0, ge=0)
    inventory_transfer_units: float = Field(default=0.0, ge=0)
    supplier_risk_tier: str = ""
    is_high_impact_reroute: bool = False
    approval_policy: Optional[ApprovalPolicy] = None


class AuditEvidence(BaseModel):
    """One structured, auditable finding in the trail."""

    check: str = Field(description="What was checked, e.g. 'Max spend' or 'Budget fit'.")
    outcome: str = Field(description="'Passed', 'Violation', 'Warning' or 'Approval required'.")
    detail: str
    source: str = Field(description="The deterministic engine or rule that produced the finding.")


class AuditReport(BaseModel):
    """Validated audit report — the Step 3 deliverable for Agent 5."""

    proposal_id: str
    verdict: AuditVerdict = Field(description="Set by deterministic validation, never by the LLM.")
    is_approved: bool = Field(
        description="True only when the proposal is compliant AND within budget."
    )
    is_compliant: bool
    is_within_budget: bool
    checked_rule_count: int
    violations: List[RuleFinding] = Field(default_factory=list)
    warnings: List[RuleFinding] = Field(default_factory=list)
    budget: BudgetValidation
    approval: ApprovalDecision
    audit_evidence: List[AuditEvidence] = Field(default_factory=list)

    # --- LLM-contributed narrative (cannot change the verdict) -----------
    explanation: str = Field(description="Why the deterministic verdict came out this way.")
    regulatory_notes: List[str] = Field(default_factory=list)
    operational_policy_notes: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    # --- Data quality ----------------------------------------------------
    missing_information: List[str] = Field(default_factory=list)

    @field_validator("regulatory_notes", "operational_policy_notes", "missing_information")
    @classmethod
    def _drop_blank_entries(cls, values: List[str]) -> List[str]:
        """Drop empty strings while preserving order and removing duplicates."""
        seen: set[str] = set()
        cleaned: List[str] = []
        for value in values:
            item = value.strip()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item)
        return cleaned
