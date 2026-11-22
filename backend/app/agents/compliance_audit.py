"""Compliance & Audit Agent — AGENT 5 (Step 3).

Design rule enforced here, identical to Step 1: **the LLM explains, deterministic
code decides — and it cannot override a failed validation.**

* :func:`app.tools.compliance.validate_compliance` evaluates the proposal against an
  explicit rule set and returns the *specific* rules that failed;
* :func:`app.tools.budget.validate_budget` checks affordability;
* :func:`app.tools.approval.evaluate_approval` decides whether a human must sign off,
  and at what level.

``AuditReport.verdict`` is derived from those three results. Gemini's response schema
contains no verdict field at all, so a proposal that fails a mandatory rule is
rejected no matter what the model writes.

The agent audits only. It never approves, executes or releases anything.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.audit_schemas import (
    AuditEvidence,
    AuditReport,
    AuditRequest,
    AuditVerdict,
)
from app.services.gemini_service import GeminiService
from app.tools.approval import ApprovalRequest, evaluate_approval
from app.tools.budget import BudgetValidation, validate_budget
from app.tools.compliance import (
    ComplianceResult,
    RuleFinding,
    validate_compliance,
)

logger = logging.getLogger(__name__)


class ComplianceAuditError(RuntimeError):
    """Raised when the agent cannot produce a usable audit report."""


SYSTEM_INSTRUCTION = """You are the Compliance & Audit Agent inside X FACTOR, an
enterprise supply-chain resilience platform used by a logistics control tower.

You are given the result of deterministic compliance, budget and approval validation
for ONE recovery proposal.

RULES
1. Explain the verdict you are given. The verdict is decided by deterministic
   validation and you cannot change it.
2. Never state that a proposal is compliant, affordable or approved when the supplied
   validation says otherwise. Quote the failed rules exactly.
3. regulatory_notes must describe the regulatory restrictions that were actually
   checked or actually failed. operational_policy_notes must describe the operational
   policies that were actually checked or actually failed. Do not invent a rule.
4. List everything you could not establish in missing_information. Use an empty list
   when nothing is missing.
5. confidence is your own certainty in this explanation, between 0 and 1.
6. You audit only. Never state or imply that a proposal has been approved, released or
   executed.
"""


#: OpenAPI-subset schema handed to Gemini. Deliberately has NO verdict field, so the
#: model cannot override deterministic validation.
LLM_AUDIT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "Why the deterministic verdict came out this way.",
        },
        "regulatory_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Regulatory restrictions actually checked or actually failed.",
        },
        "operational_policy_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Operational policies actually checked or actually failed.",
        },
        "confidence": {"type": "number", "description": "Certainty between 0 and 1."},
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Facts required for a firmer audit that were not supplied.",
        },
    },
    "required": [
        "explanation",
        "regulatory_notes",
        "operational_policy_notes",
        "confidence",
        "missing_information",
    ],
}


class LLMAuditNarrative(BaseModel):
    """The only fields the model decides for Agent 5."""

    model_config = ConfigDict(str_strip_whitespace=True)

    explanation: str = Field(min_length=1)
    regulatory_notes: List[str] = Field(default_factory=list)
    operational_policy_notes: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_information: List[str] = Field(default_factory=list)


class ComplianceAuditAgent:
    """Validates one recovery proposal and produces structured audit evidence."""

    def __init__(self, *, gemini: Optional[GeminiService] = None) -> None:
        self._gemini = gemini or GeminiService()

    def audit(self, request: AuditRequest) -> AuditReport:
        """Validate ``request`` and return a deterministic :class:`AuditReport`.

        Raises:
            ToolInputError: The rule set is empty or the proposal is malformed — the
                agent refuses to declare a proposal compliant without validation.
            GeminiNotConfiguredError: No Gemini API key is configured.
            GeminiRequestError: Gemini was unreachable or returned unusable output.
            ComplianceAuditError: Gemini's output did not satisfy the schema.
        """
        proposal = request.proposal
        logger.info("Auditing proposal %s against %s rule(s)", proposal.proposal_id, len(request.applicable_rules))

        compliance = validate_compliance(
            proposal=proposal,
            applicable_rules=request.applicable_rules,
        )
        budget = validate_budget(
            proposed_cost_usd=proposal.total_cost_usd,
            available_budget_usd=request.available_budget_usd,
        )
        approval = evaluate_approval(
            request=ApprovalRequest(
                proposal_id=proposal.proposal_id,
                action_type=request.action_type,
                total_cost_usd=proposal.total_cost_usd,
                shipment_value_usd=request.shipment_value_usd,
                inventory_transfer_units=request.inventory_transfer_units,
                supplier_risk_tier=request.supplier_risk_tier,
                is_high_impact_reroute=request.is_high_impact_reroute,
                compliance_requires_approval=compliance.requires_approval,
            ),
            policy=request.approval_policy,
        )

        is_approved = compliance.is_compliant and budget.is_within_budget
        verdict = self._verdict(is_approved, approval.requires_approval)

        narrative = self._narrate(request, compliance, budget, verdict)

        report = AuditReport(
            proposal_id=proposal.proposal_id,
            verdict=verdict,
            is_approved=is_approved,
            is_compliant=compliance.is_compliant,
            is_within_budget=budget.is_within_budget,
            checked_rule_count=compliance.checked_rule_count,
            violations=compliance.violations,
            warnings=compliance.warnings,
            budget=budget,
            approval=approval,
            audit_evidence=self._build_evidence(compliance, budget, verdict),
            explanation=narrative.explanation,
            regulatory_notes=narrative.regulatory_notes,
            operational_policy_notes=narrative.operational_policy_notes,
            confidence=round(narrative.confidence, 3),
            missing_information=[
                *narrative.missing_information,
                *self._detected_gaps(request),
            ],
        )

        logger.info(
            "Audit of %s: verdict=%s compliant=%s within_budget=%s approval=%s",
            proposal.proposal_id,
            report.verdict.value,
            report.is_compliant,
            report.is_within_budget,
            report.approval.approval_level,
        )
        return report

    # -- deterministic decision -------------------------------------------

    @staticmethod
    def _verdict(is_approved: bool, requires_approval: bool) -> AuditVerdict:
        """Derive the verdict from deterministic validation only."""
        if not is_approved:
            return AuditVerdict.REJECTED
        if requires_approval:
            return AuditVerdict.APPROVED_WITH_APPROVAL
        return AuditVerdict.APPROVED

    @staticmethod
    def _build_evidence(
        compliance: ComplianceResult,
        budget: BudgetValidation,
        verdict: AuditVerdict,
    ) -> List[AuditEvidence]:
        """Assemble the structured audit trail, one row per deterministic finding."""
        evidence: List[AuditEvidence] = [
            AuditEvidence(
                check="Compliance rules",
                outcome="Passed" if compliance.is_compliant else "Violation",
                detail=(
                    f"{compliance.checked_rule_count} rule(s) evaluated; "
                    f"{len(compliance.violations)} mandatory failure(s), "
                    f"{len(compliance.warnings)} warning(s)."
                ),
                source="app.tools.compliance.validate_compliance",
            ),
            AuditEvidence(
                check="Budget fit",
                outcome="Passed" if budget.is_within_budget else "Violation",
                detail=(
                    f"Proposed {budget.proposed_cost_usd} USD against an available budget of "
                    f"{budget.available_budget_usd} USD; overage {budget.overage_usd} USD."
                ),
                source="app.tools.budget.validate_budget",
            ),
        ]
        for finding in compliance.violations:
            evidence.append(_rule_evidence(finding, "Violation"))
        for finding in compliance.warnings:
            evidence.append(_rule_evidence(finding, "Warning"))
        for finding in compliance.approval_requirements:
            evidence.append(_rule_evidence(finding, "Approval required"))
        evidence.append(
            AuditEvidence(
                check="Audit verdict",
                outcome=verdict.value,
                detail=(
                    "Derived deterministically from compliance and budget validation; the "
                    "LLM cannot override it."
                ),
                source="app.agents.compliance_audit.ComplianceAuditAgent",
            )
        )
        return evidence

    # -- LLM call ---------------------------------------------------------

    def _narrate(
        self,
        request: AuditRequest,
        compliance: ComplianceResult,
        budget: BudgetValidation,
        verdict: AuditVerdict,
    ) -> LLMAuditNarrative:
        """Ask Gemini to explain the deterministic verdict."""
        raw = self._gemini.generate_structured_json(
            prompt=build_prompt(request, compliance, budget, verdict),
            response_schema=LLM_AUDIT_SCHEMA,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        try:
            return LLMAuditNarrative.model_validate(raw)
        except ValidationError as exc:
            raise ComplianceAuditError(
                f"Gemini returned an audit narrative for {request.proposal.proposal_id} that "
                f"does not match the expected schema: {exc.error_count()} validation "
                f"error(s). First error: {exc.errors()[0]['msg']} at "
                f"{'.'.join(str(part) for part in exc.errors()[0]['loc'])}"
            ) from exc

    # -- deterministic post-processing ------------------------------------

    @staticmethod
    def _detected_gaps(request: AuditRequest) -> List[str]:
        """Gaps the deterministic layer can see, independent of the model."""
        proposal = request.proposal
        gaps: List[str] = []
        if proposal.estimated_lead_time_days <= 0:
            gaps.append(
                "The proposal carries no estimated lead time, so lead-time rules could "
                "only be evaluated trivially."
            )
        if request.available_budget_usd <= 0:
            gaps.append(
                "No available budget was supplied, so affordability rests on the raw cost "
                "comparison alone."
            )
        if not proposal.certifications:
            gaps.append(
                "The proposal lists no certifications, so certification requirements could "
                "only fail, never be confirmed as held."
            )
        if not proposal.origin_country or not proposal.destination_country:
            gaps.append(
                "The proposal omits an origin or destination country, so country "
                "restrictions could not be fully checked."
            )
        return gaps


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    request: AuditRequest,
    compliance: ComplianceResult,
    budget: BudgetValidation,
    verdict: AuditVerdict,
) -> str:
    """Render the deterministic validation result into the user-turn prompt."""
    proposal = request.proposal
    lines = [
        "Explain the deterministic audit verdict below. Do not change it.",
        "",
        f"PROPOSAL ID: {proposal.proposal_id}",
        f"ACTION: {request.action_type}",
        f"TOTAL COST: {proposal.total_cost_usd} USD",
        f"AVAILABLE BUDGET: {request.available_budget_usd} USD",
        f"ROUTE: {proposal.origin_country or 'unknown'} -> "
        f"{proposal.destination_country or 'unknown'}"
        + (f" via {', '.join(proposal.transit_countries)}" if proposal.transit_countries else ""),
        f"SUPPLIER: {proposal.supplier_id or 'not specified'}",
        f"CARRIER: {proposal.carrier or 'not specified'} "
        f"(reliability {proposal.carrier_reliability})",
        f"ESTIMATED LEAD TIME: {proposal.estimated_lead_time_days} days",
        f"CERTIFICATIONS: {', '.join(proposal.certifications) or 'none listed'}",
        "",
        "DETERMINISTIC VALIDATION RESULT",
        "------------------------------",
        f"COMPLIANT: {compliance.is_compliant} "
        f"({compliance.checked_rule_count} rule(s) evaluated)",
        f"WITHIN BUDGET: {budget.is_within_budget} "
        f"(overage {budget.overage_usd} USD, utilisation {budget.utilisation_percent}%)",
        f"APPROVAL REQUIRED: {compliance.requires_approval}",
        f"VERDICT: {verdict.value}",
        "",
        "MANDATORY RULE FAILURES",
    ]
    lines.extend(
        [f"- [{finding.rule_id}] {finding.detail}" for finding in compliance.violations]
        or ["- none"]
    )
    lines.append("")
    lines.append("NON-MANDATORY RULE FAILURES")
    lines.extend(
        [f"- [{finding.rule_id}] {finding.detail}" for finding in compliance.warnings]
        or ["- none"]
    )
    lines.append("")
    lines.append("APPROVAL REQUIREMENTS")
    lines.extend(
        [f"- [{finding.rule_id}] {finding.detail}" for finding in compliance.approval_requirements]
        or ["- none"]
    )
    return "\n".join(lines)


def _rule_evidence(finding: RuleFinding, outcome: str) -> AuditEvidence:
    """Turn one rule finding into an audit-trail row."""
    return AuditEvidence(
        check=finding.rule_type.value,
        outcome=outcome,
        detail=f"[{finding.rule_id}] {finding.detail}",
        source="app.tools.compliance.validate_compliance",
    )
