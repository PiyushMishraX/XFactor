"""Deterministic collaboration mechanics for the LangGraph supervisor (Step 5).

This module contains the *decisions* behind multi-agent collaboration. It is
deliberately free of LangGraph and of any LLM call:

* :func:`build_agent_task` turns a real supervisor decision into the structured
  :class:`~app.schemas.collaboration_schemas.AgentTask` handed to an agent.
* :func:`evaluate_scenario_plan` scores every recovery alternative with the same
  compliance, budget and approval engines Agent 5 uses, so the supervisor can
  evaluate an agent's result before auditing it.
* :func:`build_scenario_revision` and :func:`build_history_entry` translate a
  rejection into concrete revision instructions, and preserve the plan that was
  replaced.
* :func:`screening_requires_replan` is the single condition that opens the
  feedback loop.

Bounded autonomy: :data:`MAX_REPLAN_ROUNDS` caps how many revisions the
supervisor may request, so a plan that keeps failing validation stops at
``STATUS_NO_COMPLIANT_RECOVERY`` instead of looping.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.orchestration.state import (
    AGENT_COMPLIANCE,
    AGENT_REBALANCING,
    AGENT_REROUTING,
    AGENT_SCENARIO,
    AGENT_SENSING,
    RecoveryRequest,
)
from app.schemas.audit_schemas import AuditVerdict
from app.schemas.collaboration_schemas import (
    AgentTask,
    ReplanningRecord,
    ScenarioEvaluation,
    ScenarioHistoryEntry,
    ScenarioScreening,
)
from app.schemas.scenario_schemas import ScenarioPlan, ScenarioRevision
from app.tools.approval import ApprovalRequest, evaluate_approval
from app.tools.budget import validate_budget
from app.tools.compliance import RecoveryProposal, validate_compliance

#: How many times the supervisor may ask the Scenario agent to revise a plan.
MAX_REPLAN_ROUNDS = 2

#: The tools each agent is expected to use, as recorded in its task.
AGENT_TOOLS: Dict[str, Tuple[str, ...]] = {
    AGENT_SENSING: (
        "gemini.generate_structured_json",
        "supply_chain_repository.snapshot",
        "risk_scoring.compute_risk_score",
    ),
    AGENT_REROUTING: (
        "gemini.generate_structured_json",
        "mapping.get_route",
        "carriers.list_services",
        "route_optimization.rank_routes",
    ),
    AGENT_REBALANCING: (
        "gemini.generate_structured_json",
        "sap.list_inventory",
        "safety_stock.calculate_safety_stock",
        "inventory.calculate_inventory_shortage",
    ),
    AGENT_SCENARIO: (
        "gemini.generate_structured_json",
        "rerouting_logistics.analyse",
        "inventory_rebalancing.plan",
        "route_optimization.rank_routes",
    ),
    AGENT_COMPLIANCE: (
        "gemini.generate_structured_json",
        "compliance.validate_compliance",
        "budget.validate_budget",
        "approval.evaluate_approval",
    ),
}

#: What each agent is asked to produce, stated in its task.
AGENT_OBJECTIVES: Dict[str, str] = {
    AGENT_SENSING: "Interpret the disruption report and validate the affected shipment and supplier ids.",
    AGENT_REROUTING: "Score and rank the logistics alternatives for the affected lane.",
    AGENT_REBALANCING: "Establish the inventory shortage and the safe transfer allocation.",
    AGENT_SCENARIO: "Build, score and rank at least three recovery alternatives.",
    AGENT_COMPLIANCE: "Validate the proposed recovery against the compliance, budget and approval engines.",
}

_MAX_TEXT = 160


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def build_agent_task(
    *,
    agent: str,
    request: RecoveryRequest,
    reason: str,
    step: int,
    attempt: int,
    revision: Optional[ScenarioRevision] = None,
) -> AgentTask:
    """Build the task object for one real delegation."""
    return AgentTask(
        task_id=f"{step:02d}-{agent}-{attempt}",
        agent=agent,
        objective=AGENT_OBJECTIVES.get(agent, f"Execute the {agent} agent."),
        reason=reason,
        step=step,
        attempt=attempt,
        tools=list(AGENT_TOOLS.get(agent, ())),
        inputs=task_inputs(agent, request, revision),
        revision=revision,
    )


def task_inputs(
    agent: str,
    request: RecoveryRequest,
    revision: Optional[ScenarioRevision] = None,
) -> Dict[str, Any]:
    """A small, JSON-safe summary of what the agent is being handed."""
    scenario = request.scenario_request
    if agent == AGENT_SENSING:
        report = request.disruption_report
        return {
            "source": report.source,
            "headline": _truncate(report.headline),
            "location_hint": report.location_hint,
        }
    if agent == AGENT_REROUTING:
        return {
            "event_id": scenario.event_id,
            "origin": scenario.origin,
            "destination": scenario.destination,
            "cargo_value_usd": scenario.cargo_value_usd,
        }
    if agent == AGENT_REBALANCING:
        inventory = scenario.inventory
        if inventory is None:
            return {"event_id": scenario.event_id}
        return {
            "material_id": inventory.material_id,
            "target_plant": inventory.target_plant or "auto",
            "demand_forecast": inventory.demand_forecast,
        }
    if agent == AGENT_SCENARIO:
        return {
            "event_id": scenario.event_id,
            "severity": scenario.severity,
            "available_budget_usd": scenario.available_budget_usd,
            "revision_round": revision.round if revision else 0,
            "excluded_scenarios": list(revision.rejected_scenario_ids) if revision else [],
        }
    if agent == AGENT_COMPLIANCE:
        return {
            "event_id": scenario.event_id,
            "available_budget_usd": scenario.available_budget_usd,
            "rule_count": len(request.applicable_rules),
        }
    return {"event_id": scenario.event_id}


# ---------------------------------------------------------------------------
# Deterministic evaluation of a scenario plan
# ---------------------------------------------------------------------------


def evaluate_scenario_plan(
    *,
    request: RecoveryRequest,
    plan: ScenarioPlan,
    inventory_transfer_units: float = 0.0,
) -> ScenarioScreening:
    """Validate every alternative with the same engines Agent 5 audits with.

    The result is the supervisor's own assessment of the agent's output. It
    fabricates nothing: each row comes from deterministic validation of numbers
    the scenario agent already produced.
    """
    scenario = request.scenario_request
    transfer_units = float(request.inventory_transfer_units or inventory_transfer_units or 0.0)
    evaluations: List[ScenarioEvaluation] = []

    for item in plan.scenarios:
        proposal = RecoveryProposal(
            proposal_id=f"{scenario.event_id}:{item.scenario_id}",
            total_cost_usd=item.total_cost_usd,
            origin_country=request.origin_country,
            destination_country=request.destination_country,
            transit_countries=tuple(request.transit_countries),
            supplier_id=request.supplier_id,
            carrier=item.carrier,
            carrier_reliability=item.carrier_reliability,
            estimated_lead_time_days=item.total_days,
            certifications=tuple(request.certifications),
        )
        compliance = validate_compliance(
            proposal=proposal, applicable_rules=request.applicable_rules
        )
        budget = validate_budget(
            proposed_cost_usd=item.total_cost_usd,
            available_budget_usd=scenario.available_budget_usd,
        )
        approval = evaluate_approval(
            request=ApprovalRequest(
                proposal_id=proposal.proposal_id,
                action_type="Recovery execution",
                total_cost_usd=item.total_cost_usd,
                shipment_value_usd=scenario.cargo_value_usd,
                inventory_transfer_units=transfer_units,
                supplier_risk_tier=request.supplier_risk_tier,
                is_high_impact_reroute=request.is_high_impact_reroute,
                compliance_requires_approval=compliance.requires_approval,
            ),
            policy=request.approval_policy,
        )

        is_approved = compliance.is_compliant and budget.is_within_budget
        if not is_approved:
            verdict = AuditVerdict.REJECTED
        elif approval.requires_approval:
            verdict = AuditVerdict.APPROVED_WITH_APPROVAL
        else:
            verdict = AuditVerdict.APPROVED

        violations = [finding.detail for finding in compliance.violations]
        if not budget.is_within_budget:
            violations.append(
                f"Cost {budget.proposed_cost_usd} USD exceeds the available budget of "
                f"{budget.available_budget_usd} USD by {budget.overage_usd} USD."
            )
        warnings = [finding.detail for finding in compliance.warnings]
        reason = (
            violations[0]
            if verdict is AuditVerdict.REJECTED and violations
            else (
                "Passed deterministic compliance and budget validation and needs no human approval."
                if verdict is AuditVerdict.APPROVED
                else "Passed deterministic validation but requires human approval."
            )
        )

        evaluations.append(
            ScenarioEvaluation(
                scenario_id=item.scenario_id,
                rank=item.rank,
                carrier=item.carrier,
                transport_mode=item.transport_mode,
                total_cost_usd=item.total_cost_usd,
                total_days=item.total_days,
                risk_score=item.risk_score,
                verdict=verdict,
                is_compliant=compliance.is_compliant,
                is_within_budget=budget.is_within_budget,
                requires_approval=approval.requires_approval,
                approval_level=approval.approval_level,
                violations=violations,
                warnings=warnings,
                recommended=item.scenario_id == plan.recommended_scenario_id,
                reason=reason,
            )
        )

    recommended = next((item for item in evaluations if item.recommended), None)
    all_rejected = bool(evaluations) and all(
        item.verdict is AuditVerdict.REJECTED for item in evaluations
    )
    return ScenarioScreening(
        recommended_scenario_id=plan.recommended_scenario_id,
        recommended_verdict=recommended.verdict if recommended else None,
        scenario_count=len(evaluations),
        evaluations=evaluations,
        all_rejected=all_rejected,
        inventory_impact=plan.inventory_impact,
        inventory_can_cover_disruption=(
            plan.inventory_can_cover_disruption if plan.inventory_shortage_after is not None else None
        ),
        inventory_shortage_after=plan.inventory_shortage_after,
    )


def screening_requires_replan(screening: ScenarioScreening) -> bool:
    """Whether the plan on the table has no compliant recommendation."""
    if not screening.evaluations:
        return False
    recommended = next((item for item in screening.evaluations if item.recommended), None)
    if recommended is None:
        return True
    return recommended.verdict is AuditVerdict.REJECTED


# ---------------------------------------------------------------------------
# Feedback loop
# ---------------------------------------------------------------------------


def build_scenario_revision(
    *,
    round_number: int,
    evaluations: Sequence[ScenarioEvaluation],
    previous_rejected: Iterable[str] = (),
) -> ScenarioRevision:
    """Translate a failed screening into concrete revision instructions."""
    rejected = [item for item in evaluations if item.verdict is AuditVerdict.REJECTED]
    rejected_ids = _deduplicate(
        [*previous_rejected, *(item.scenario_id for item in rejected)]
    )
    carriers = sorted({item.carrier for item in rejected if item.carrier})
    reasons = _deduplicate(
        [
            f"{item.scenario_id}: {detail}"
            for item in rejected
            for detail in item.violations
        ]
    )
    if not reasons:
        reasons = [
            f"{item.scenario_id} was rejected by deterministic validation."
            for item in rejected
        ]
    reason_text = "; ".join(reasons)
    return ScenarioRevision(
        round=round_number,
        rejected_scenario_ids=rejected_ids,
        rejection_reasons=reasons,
        excluded_carriers=carriers,
        feedback=(
            f"Round {round_number}: deterministic screening rejected "
            f"{', '.join(item.scenario_id for item in rejected) or 'the recommendation'}. "
            f"{reason_text}"
        ),
    )


def build_history_entry(
    *,
    round_number: int,
    plan: ScenarioPlan,
    evaluations: Sequence[ScenarioEvaluation],
    rejected_scenario_ids: Sequence[str],
) -> ScenarioHistoryEntry:
    """Preserve a plan and its evaluation before the supervisor replaces it."""
    return ScenarioHistoryEntry(
        round=round_number,
        scenario_ids=[item.scenario_id for item in plan.scenarios],
        recommended_scenario_id=plan.recommended_scenario_id,
        rejected_scenario_ids=list(rejected_scenario_ids),
        plan=plan,
        evaluations=list(evaluations),
    )


def build_replanning_record(
    *,
    round_number: int,
    revision: ScenarioRevision,
    previous_scenario_ids: Sequence[str],
    trigger: str = "deterministic screening",
) -> ReplanningRecord:
    """Record why the supervisor sent the plan back for revision."""
    return ReplanningRecord(
        round=round_number,
        trigger=trigger,
        rejected_scenario_ids=list(revision.rejected_scenario_ids),
        reasons=list(revision.rejection_reasons),
        revision=revision,
        previous_scenario_ids=list(previous_scenario_ids),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deduplicate(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _truncate(text: str, limit: int = _MAX_TEXT) -> str:
    cleaned = " ".join(str(text).split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[:limit]}..."


__all__ = [
    "AGENT_OBJECTIVES",
    "AGENT_TOOLS",
    "MAX_REPLAN_ROUNDS",
    "build_agent_task",
    "build_history_entry",
    "build_replanning_record",
    "build_scenario_revision",
    "evaluate_scenario_plan",
    "screening_requires_replan",
    "task_inputs",
]
