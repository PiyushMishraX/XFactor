"""Step 3 tests for the Compliance & Audit Agent (Agent 5).

Gemini is replaced with a deterministic stub, while compliance, budget and approval
validation run for real. The point of these tests is the architectural contract:
**the verdict is decided by deterministic code, and the LLM structurally cannot
change it** — its response schema has no verdict field at all.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Sequence

import pytest
from pydantic import ValidationError

from app.agents.compliance_audit import (
    LLM_AUDIT_SCHEMA,
    SYSTEM_INSTRUCTION,
    ComplianceAuditAgent,
    ComplianceAuditError,
)
from app.schemas.audit_schemas import AuditRequest, AuditVerdict
from app.services.gemini_service import GeminiNotConfiguredError
from app.tools.base import ToolInputError
from app.tools.compliance import (
    ComplianceRule,
    RecoveryProposal,
    RuleType,
    validate_compliance,
)
from tests.fakes import StubGeminiService

# ---------------------------------------------------------------------------
# Fixtures: hand-built rules and proposals with hand-checkable outcomes
# ---------------------------------------------------------------------------

MAX_SPEND_RULE = ComplianceRule(
    rule_id="R-MAX-SPEND",
    description="Spend must not exceed 200,000 USD.",
    rule_type=RuleType.MAX_SPEND,
    max_value=200_000.0,
)
LENIENT_MAX_SPEND_RULE = ComplianceRule(
    rule_id="R-MAX-SPEND-LENIENT",
    description="Spend must not exceed 500,000 USD.",
    rule_type=RuleType.MAX_SPEND,
    max_value=500_000.0,
)
RESTRICTED_COUNTRY_RULE = ComplianceRule(
    rule_id="R-RESTRICTED",
    description="Routes must not touch restricted countries.",
    rule_type=RuleType.RESTRICTED_COUNTRY,
    blocked_values=("Russia",),
)
CERTIFICATION_RULE = ComplianceRule(
    rule_id="R-CERT",
    description="ISO9001 must be held.",
    rule_type=RuleType.REQUIRED_CERTIFICATION,
    required_certifications=("ISO9001",),
)
BUDGET_APPROVAL_RULE = ComplianceRule(
    rule_id="R-APPROVAL",
    description="Spend above 100,000 USD needs human approval.",
    rule_type=RuleType.BUDGET_APPROVAL_REQUIRED,
    max_value=100_000.0,
)

DEFAULT_RULES: tuple[ComplianceRule, ...] = (
    MAX_SPEND_RULE,
    RESTRICTED_COUNTRY_RULE,
    CERTIFICATION_RULE,
)


def llm_response(**overrides: Any) -> Dict[str, Any]:
    """A schema-shaped LLM response with sensible defaults."""
    response: Dict[str, Any] = {
        "explanation": "The proposal passed every mandatory rule and fits the budget.",
        "regulatory_notes": [],
        "operational_policy_notes": [],
        "confidence": 0.9,
        "missing_information": [],
    }
    response.update(overrides)
    return response


def make_proposal(**overrides: Any) -> RecoveryProposal:
    payload: Dict[str, Any] = {
        "proposal_id": "PROP-1",
        "total_cost_usd": 150_000.0,
        "origin_country": "India",
        "destination_country": "Netherlands",
        "supplier_id": "SUP-1",
        "carrier": "CarrierA",
        "carrier_reliability": 0.95,
        "estimated_lead_time_days": 10.0,
        "certifications": ("ISO9001",),
    }
    payload.update(overrides)
    return RecoveryProposal(**payload)


def build_agent(response: Any) -> ComplianceAuditAgent:
    stub = StubGeminiService(response)
    return ComplianceAuditAgent(gemini=stub)  # type: ignore[arg-type]


def build_agent_with_stub(response: Any) -> tuple[ComplianceAuditAgent, StubGeminiService]:
    stub = StubGeminiService(response)
    return ComplianceAuditAgent(gemini=stub), stub  # type: ignore[arg-type]


def audit(
    agent: ComplianceAuditAgent,
    *,
    proposal: RecoveryProposal | None = None,
    rules: Sequence[ComplianceRule] = DEFAULT_RULES,
    available_budget_usd: float = 1_000_000.0,
    **overrides: Any,
):
    request = AuditRequest(
        proposal=proposal or make_proposal(),
        applicable_rules=list(rules),
        available_budget_usd=available_budget_usd,
        **overrides,
    )
    return agent.audit(request)


# ---------------------------------------------------------------------------
# The deterministic verdict
# ---------------------------------------------------------------------------


def test_audit_approves_a_compliant_in_budget_proposal() -> None:
    agent = build_agent(llm_response())
    report = audit(agent)

    assert report.verdict is AuditVerdict.APPROVED
    assert report.is_approved is True
    assert report.is_compliant is True
    assert report.is_within_budget is True
    assert report.checked_rule_count == 3
    assert report.violations == []
    assert report.warnings == []
    assert report.approval.requires_approval is False
    assert report.approval.approval_level is None
    assert report.budget.remaining_budget_usd == 850_000.0
    assert report.budget.utilisation_percent == 15.0
    assert report.explanation == llm_response()["explanation"]
    assert report.confidence == 0.9


def test_audit_rejects_a_mandatory_rule_failure_even_when_within_budget() -> None:
    agent = build_agent(llm_response(explanation="All good."))
    report = audit(agent, proposal=make_proposal(total_cost_usd=300_000.0))

    assert report.verdict is AuditVerdict.REJECTED
    assert report.is_approved is False
    assert report.is_compliant is False
    assert report.is_within_budget is True
    assert [finding.rule_id for finding in report.violations] == ["R-MAX-SPEND"]
    # The cost is above the approval threshold, so approval is also required —
    # but a failed mandatory rule still yields Rejected, never "subject to approval".
    assert report.approval.requires_approval is True
    assert report.approval.approval_level == "Manager"


def test_audit_approves_subject_to_approval_when_a_human_must_sign_off() -> None:
    agent = build_agent(llm_response())
    report = audit(
        agent,
        proposal=make_proposal(total_cost_usd=300_000.0),
        rules=(LENIENT_MAX_SPEND_RULE, RESTRICTED_COUNTRY_RULE, CERTIFICATION_RULE),
    )

    assert report.is_compliant is True
    assert report.is_within_budget is True
    assert report.is_approved is True
    assert report.verdict is AuditVerdict.APPROVED_WITH_APPROVAL
    assert report.approval.approval_level == "Manager"


def test_audit_reflects_a_compliance_mandated_approval() -> None:
    agent = build_agent(llm_response())
    report = audit(agent, rules=(*DEFAULT_RULES, BUDGET_APPROVAL_RULE))

    assert report.is_compliant is True
    assert report.verdict is AuditVerdict.APPROVED_WITH_APPROVAL
    assert report.approval.requires_approval is True
    assert any(
        "compliance rules mandate human approval" in reason.lower()
        for reason in report.approval.reasons
    )


def test_audit_uses_director_level_for_a_high_impact_proposal() -> None:
    agent = build_agent(llm_response())
    report = audit(
        agent,
        proposal=make_proposal(total_cost_usd=300_000.0),
        rules=(LENIENT_MAX_SPEND_RULE, RESTRICTED_COUNTRY_RULE, CERTIFICATION_RULE),
        is_high_impact_reroute=True,
    )

    assert report.verdict is AuditVerdict.APPROVED_WITH_APPROVAL
    assert report.approval.approval_level == "Director"


# ---------------------------------------------------------------------------
# The model cannot be the source of the verdict
# ---------------------------------------------------------------------------


def test_model_cannot_override_a_rejection() -> None:
    response = llm_response(
        explanation="The proposal is fully compliant and approved. Ship it."
    )
    agent, stub = build_agent_with_stub(response)
    report = audit(agent, proposal=make_proposal(total_cost_usd=300_000.0))

    # The model claims approval; the verdict remains the deterministic one.
    assert report.verdict is AuditVerdict.REJECTED
    assert report.is_approved is False
    assert report.explanation == response["explanation"]
    prompt = stub.calls[0]["prompt"]
    assert "VERDICT: Rejected" in prompt
    assert "Do not change it" in prompt


def test_verdict_fields_are_not_offered_to_the_model() -> None:
    properties = LLM_AUDIT_SCHEMA["properties"]
    for forbidden in (
        "verdict",
        "is_approved",
        "is_compliant",
        "is_within_budget",
        "requires_approval",
        "approval_level",
    ):
        assert forbidden not in properties


def test_system_instruction_forbids_declaring_approval() -> None:
    assert "cannot change it" in SYSTEM_INSTRUCTION
    assert "Never state or imply that a proposal has been approved" in SYSTEM_INSTRUCTION


# ---------------------------------------------------------------------------
# Audit evidence trail
# ---------------------------------------------------------------------------


def test_audit_evidence_records_every_deterministic_finding() -> None:
    agent = build_agent(llm_response())
    report = audit(agent, proposal=make_proposal(total_cost_usd=300_000.0))

    checks = {row.check for row in report.audit_evidence}
    assert "Compliance rules" in checks
    assert "Budget fit" in checks
    assert "Audit verdict" in checks
    assert any(row.check == RuleType.MAX_SPEND.value for row in report.audit_evidence)

    verdict_row = next(row for row in report.audit_evidence if row.check == "Audit verdict")
    assert verdict_row.outcome == AuditVerdict.REJECTED.value
    assert "cannot override it" in verdict_row.detail

    violation_row = next(
        row for row in report.audit_evidence if row.check == RuleType.MAX_SPEND.value
    )
    assert violation_row.outcome == "Violation"
    assert violation_row.source == "app.tools.compliance.validate_compliance"


def test_audit_evidence_marks_compliance_mandated_approvals() -> None:
    agent = build_agent(llm_response())
    report = audit(agent, rules=(*DEFAULT_RULES, BUDGET_APPROVAL_RULE))

    approval_rows = [
        row for row in report.audit_evidence if row.outcome == "Approval required"
    ]
    assert len(approval_rows) == 1
    assert approval_rows[0].check == RuleType.BUDGET_APPROVAL_REQUIRED.value


# ---------------------------------------------------------------------------
# Deterministic gap detection and note hygiene
# ---------------------------------------------------------------------------


def test_audit_reports_gaps_the_deterministic_layer_can_see() -> None:
    agent = build_agent(llm_response())
    report = audit(
        agent,
        proposal=make_proposal(
            total_cost_usd=0.0,
            estimated_lead_time_days=0.0,
            certifications=(),
            origin_country="",
            destination_country="",
        ),
        available_budget_usd=0.0,
    )

    gaps = " ".join(report.missing_information).lower()
    assert "no estimated lead time" in gaps
    assert "no available budget" in gaps
    assert "lists no certifications" in gaps
    assert "omits an origin or destination" in gaps


def test_audit_drops_blank_and_duplicate_model_notes() -> None:
    agent = build_agent(
        llm_response(
            regulatory_notes=["Export licence required", "Export licence required", "   "],
            operational_policy_notes=["", "Dual-sourcing mandate"],
        )
    )
    report = audit(agent)

    assert report.regulatory_notes == ["Export licence required"]
    assert report.operational_policy_notes == ["Dual-sourcing mandate"]


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_audit_request_rejects_an_empty_rule_set() -> None:
    with pytest.raises(ValidationError):
        AuditRequest(
            proposal=make_proposal(),
            applicable_rules=[],
            available_budget_usd=1_000_000.0,
        )


def test_engine_refuses_to_declare_compliance_without_rules() -> None:
    with pytest.raises(ToolInputError):
        validate_compliance(proposal=make_proposal(), applicable_rules=[])


def test_malformed_model_output_raises_a_clear_error() -> None:
    agent = build_agent({"confidence": 2.0})
    with pytest.raises(ComplianceAuditError) as excinfo:
        audit(agent)
    assert "does not match the expected schema" in str(excinfo.value)


def test_missing_api_key_surfaces_as_a_configuration_error() -> None:
    agent = build_agent(GeminiNotConfiguredError("GEMINI_API_KEY is not configured"))
    with pytest.raises(GeminiNotConfiguredError):
        audit(agent)


# ---------------------------------------------------------------------------
# Opt-in live check against the real Gemini API
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1",
    reason="Set RUN_LIVE_GEMINI=1 to call the live Gemini API.",
)
def test_live_gemini_audit_explains_the_verdict() -> None:
    """Real Gemini call. Costs one API request."""
    agent = ComplianceAuditAgent()
    report = audit(agent)

    assert report.verdict in (
        AuditVerdict.APPROVED,
        AuditVerdict.APPROVED_WITH_APPROVAL,
        AuditVerdict.REJECTED,
    )
    assert report.explanation
