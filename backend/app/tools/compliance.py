"""Compliance Rules Engine (Step 2).

Evaluates a recovery proposal against an explicit rule set and returns the
*specific* rules that fail. Nothing here is decided by an LLM: a proposal is
compliant only when deterministic validation says so.

Assumptions
-----------
* Rules are supplied by the caller (typically loaded from configuration or the
  database), so the engine has no hidden policy of its own. Calling it with an
  empty rule set is rejected rather than treated as "compliant".
* Country and identifier comparisons are case-insensitive.
* ``mandatory`` rules produce violations; non-mandatory rules produce warnings.
* ``BUDGET_APPROVAL_REQUIRED`` is not a violation — it records that a human
  approval is needed before the proposal may be executed.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.tools.base import (
    EngineResult,
    ToolInputError,
    require_non_empty,
    require_number,
    require_positive,
    round_money,
)


class RuleType(str, Enum):
    """The kinds of deterministic check the engine understands."""

    MAX_SPEND = "Max spend"
    RESTRICTED_COUNTRY = "Restricted country"
    SANCTIONED_SUPPLIER = "Sanctioned supplier"
    REQUIRED_CERTIFICATION = "Required certification"
    MAX_LEAD_TIME = "Max lead time"
    MIN_CARRIER_RELIABILITY = "Minimum carrier reliability"
    BUDGET_APPROVAL_REQUIRED = "Budget approval required"


class ComplianceRule(BaseModel):
    """One deterministic policy rule."""

    rule_id: str
    description: str
    rule_type: RuleType
    mandatory: bool = True
    max_value: Optional[float] = Field(
        default=None, description="Threshold for MAX_SPEND / MAX_LEAD_TIME / MIN_CARRIER_RELIABILITY."
    )
    blocked_values: tuple[str, ...] = Field(
        default=(), description="Countries or supplier ids the rule forbids."
    )
    required_certifications: tuple[str, ...] = ()


class RecoveryProposal(BaseModel):
    """The deterministic facts of a proposal that rules are checked against."""

    proposal_id: str
    total_cost_usd: float = 0.0
    origin_country: str = ""
    destination_country: str = ""
    transit_countries: tuple[str, ...] = ()
    supplier_id: str = ""
    carrier: str = ""
    carrier_reliability: float = 1.0
    estimated_lead_time_days: float = 0.0
    certifications: tuple[str, ...] = ()


class RuleFinding(BaseModel):
    """A single rule outcome."""

    rule_id: str
    rule_type: RuleType
    description: str
    detail: str
    mandatory: bool


class ComplianceResult(EngineResult):
    """Outcome of deterministic compliance validation."""

    proposal_id: str
    is_compliant: bool = Field(description="True only when no mandatory rule failed.")
    checked_rule_count: int
    violations: list[RuleFinding] = Field(default=(), description="Mandatory rule failures.")
    warnings: list[RuleFinding] = Field(default=(), description="Non-mandatory rule failures.")
    approval_requirements: list[RuleFinding] = Field(
        default=(), description="Human approvals triggered by the proposal."
    )

    @property
    def requires_approval(self) -> bool:
        return bool(self.approval_requirements)


def validate_compliance(
    *,
    proposal: RecoveryProposal,
    applicable_rules: Sequence[ComplianceRule],
) -> ComplianceResult:
    """Validate ``proposal`` against ``applicable_rules``.

    Raises:
        ToolInputError: No rules were supplied, or the proposal is malformed.
    """
    if not applicable_rules:
        raise ToolInputError(
            "validate_compliance requires at least one applicable rule; refusing to "
            "declare a proposal compliant without deterministic validation."
        )
    require_non_empty(proposal.proposal_id, "proposal.proposal_id")
    require_positive(proposal.total_cost_usd, "proposal.total_cost_usd", allow_zero=True)
    require_positive(proposal.estimated_lead_time_days, "proposal.estimated_lead_time_days", allow_zero=True)

    violations: list[RuleFinding] = []
    warnings: list[RuleFinding] = []
    approvals: list[RuleFinding] = []

    for rule in applicable_rules:
        finding = _check_rule(rule, proposal)
        if finding is None:
            continue
        if rule.rule_type is RuleType.BUDGET_APPROVAL_REQUIRED:
            approvals.append(finding)
        elif rule.mandatory:
            violations.append(finding)
        else:
            warnings.append(finding)

    return ComplianceResult(
        proposal_id=proposal.proposal_id,
        is_compliant=not violations,
        checked_rule_count=len(applicable_rules),
        violations=violations,
        warnings=warnings,
        approval_requirements=approvals,
        assumptions=(
            f"{len(applicable_rules)} rule(s) evaluated deterministically.",
            "Country and identifier comparisons are case-insensitive.",
            "A proposal is compliant only when no mandatory rule failed.",
        ),
    )


def _check_rule(rule: ComplianceRule, proposal: RecoveryProposal) -> Optional[RuleFinding]:
    """Return a finding when ``rule`` fails for ``proposal``, else ``None``."""
    blocked = {value.strip().lower() for value in rule.blocked_values}
    required_certs = {value.strip().lower() for value in rule.required_certifications}
    held_certs = {value.strip().lower() for value in proposal.certifications}

    if rule.rule_type is RuleType.MAX_SPEND:
        threshold = _required_threshold(rule)
        if proposal.total_cost_usd > threshold:
            return _finding(
                rule,
                f"Proposed cost {round_money(proposal.total_cost_usd)} USD exceeds the "
                f"limit of {round_money(threshold)} USD.",
            )

    elif rule.rule_type is RuleType.BUDGET_APPROVAL_REQUIRED:
        threshold = _required_threshold(rule)
        if proposal.total_cost_usd > threshold:
            return _finding(
                rule,
                f"Proposed cost {round_money(proposal.total_cost_usd)} USD exceeds the "
                f"approval threshold of {round_money(threshold)} USD.",
            )

    elif rule.rule_type is RuleType.MAX_LEAD_TIME:
        threshold = _required_threshold(rule)
        if proposal.estimated_lead_time_days > threshold:
            return _finding(
                rule,
                f"Estimated lead time {proposal.estimated_lead_time_days} days exceeds the "
                f"limit of {threshold} days.",
            )

    elif rule.rule_type is RuleType.MIN_CARRIER_RELIABILITY:
        threshold = _required_threshold(rule)
        if proposal.carrier_reliability < threshold:
            return _finding(
                rule,
                f"Carrier '{proposal.carrier or 'unknown'}' reliability "
                f"{proposal.carrier_reliability} is below the required {threshold}.",
            )

    elif rule.rule_type is RuleType.RESTRICTED_COUNTRY:
        touched = {proposal.origin_country, proposal.destination_country, *proposal.transit_countries}
        hits = sorted(
            country for country in touched if country and country.strip().lower() in blocked
        )
        if hits:
            return _finding(rule, f"Route touches restricted country/countries: {', '.join(hits)}.")

    elif rule.rule_type is RuleType.SANCTIONED_SUPPLIER:
        if proposal.supplier_id and proposal.supplier_id.strip().lower() in blocked:
            return _finding(rule, f"Supplier '{proposal.supplier_id}' is on the blocked list.")

    elif rule.rule_type is RuleType.REQUIRED_CERTIFICATION:
        missing = sorted(required_certs - held_certs)
        if missing:
            return _finding(
                rule,
                f"Missing required certification(s): {', '.join(sorted(missing))}.",
            )

    return None


def _required_threshold(rule: ComplianceRule) -> float:
    if rule.max_value is None:
        raise ToolInputError(
            f"Rule '{rule.rule_id}' of type '{rule.rule_type.value}' needs a max_value threshold."
        )
    return require_number(rule.max_value, f"rule[{rule.rule_id}].max_value")


def _finding(rule: ComplianceRule, detail: str) -> RuleFinding:
    return RuleFinding(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        description=rule.description,
        detail=detail,
        mandatory=rule.mandatory,
    )
