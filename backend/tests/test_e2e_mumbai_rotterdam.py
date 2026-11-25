"""Step 9 end-to-end validation: Mumbai -> Rotterdam pharmaceutical disruption.

The scenario is the roadmap's primary walkthrough: a maritime security event in
the Bab-el-Mandeb delays shipment ``SH001`` (Pharmaceutical API, Mumbai ->
Rotterdam) and the platform must sense it, delegate all five agents, plan a
reroute plus inventory cover at Rotterdam DC, pass the deterministic audit,
pause for human approval and execute only after that approval.

Unlike the Step 4/6 tests, this module wires the **real** simulated connectors
(``SimulatedSAPConnector``, ``SimulatedMappingConnector``,
``SimulatedCarrierConnector``) to the **seeded demo reference data** (SH001,
SUP001 and the MAT-PHARMA-001 inventory positions), so the numbers asserted here
are the ones the demo dataset actually produces. Gemini is the only double.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.integrations.carriers import SimulatedCarrierConnector
from app.integrations.mapping import SimulatedMappingConnector
from app.integrations.sap import SimulatedSAPConnector
from app.orchestration.checkpointing import in_memory_checkpointer
from app.orchestration.state import (
    AGENT_COMPLIANCE,
    AGENT_SCENARIO,
    AGENT_SENSING,
    DEFAULT_COMPLIANCE_RULES,
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    RecoveryRequest,
)
from app.orchestration.workflow import (
    SupervisorWorkflow,
    build_agents,
    build_graph,
    pending_interrupt,
)
from app.schemas.approval_schemas import ApprovalAction, ApprovalDecisionRequest
from app.schemas.disruption_schemas import DisruptionReport
from app.schemas.scenario_schemas import ScenarioRequest
from app.services.approval_auth import ApprovalAuthorizer
from app.services.approval_repository import InMemoryApprovalRepository
from app.services.approval_service import ApprovalConflictError, ApprovalService
from app.services.execution import ExecutionService, SimulatedExecutionAdapter
from app.schemas.execution_schemas import ExecutionActionType
from tests.fakes import InMemorySupplyChainRepository
from app.schemas.rebalancing_schemas import RebalancingRequest

SENSING_MARKER = "Assess the disruption report below"
REROUTING_MARKER = "Explain the deterministic logistics ranking below"
REBALANCING_MARKER = "Explain the deterministic inventory rebalancing plan below"
SCENARIO_MARKER = "Explain the deterministic recovery scenario ranking below"
AUDIT_MARKER = "Explain the deterministic audit verdict below"

DIRECTOR_TOKEN = "e2e-director-token"

SHIPMENT_VALUE_USD = 1_250_000.0
REPORTED_AT = datetime(2026, 11, 22, 17, 45, tzinfo=timezone.utc)


class ScriptedGemini:
    """The only double in this module: one canned response per agent prompt."""

    def __init__(self) -> None:
        self._payloads: Dict[str, Dict[str, Any]] = {
            SENSING_MARKER: {
                "is_supply_chain_disruption": True,
                "disruption_type": "Maritime Security Threat",
                "description": (
                    "Militant attacks closed the Bab-el-Mandeb strait and Maersk "
                    "suspended Red Sea transits."
                ),
                "affected_locations": ["Bab-el-Mandeb", "Rotterdam"],
                "risk_factors": [
                    "Active physical threat to vessels, cargo or personnel",
                    "Route closure or forced diversion",
                    "Carrier suspended or reduced service",
                    "Reported schedule delay",
                    "Disruption is ongoing or unresolved",
                ],
                "potential_impact": ["Shipment SH001 is delayed or must be rerouted."],
                "mentioned_shipment_ids": ["SH001"],
                "mentioned_supplier_ids": ["SUP001"],
                "recommended_next_action": (
                    "Evaluate reroutes and inventory cover at Rotterdam DC."
                ),
                "confidence": 0.94,
                "evidence": [
                    {
                        "source": "Maritime security alert feed",
                        "description": "Carriers suspended Red Sea transits.",
                    }
                ],
                "missing_information": [],
                "contradictions": [],
            },
            REROUTING_MARKER: {
                "explanation": "The ranking follows the deterministic scorecard.",
                "route_risks": ["Bab-el-Mandeb closure"],
                "confidence": 0.8,
                "missing_information": [],
            },
            REBALANCING_MARKER: {
                "explanation": "Surplus at Mumbai DC covers the Rotterdam shortage.",
                "confidence": 0.8,
                "missing_information": [],
            },
            SCENARIO_MARKER: {
                "recommendation_rationale": "The top-ranked scenario wins the scorecard.",
                "scenario_assessments": [
                    {"scenario_id": "SC1", "assessment": "Best weighted score."}
                ],
                "confidence": 0.8,
                "missing_information": [],
            },
            AUDIT_MARKER: {
                "explanation": "The verdict follows the deterministic rule findings.",
                "regulatory_notes": ["No restricted country on the route."],
                "operational_policy_notes": ["High-impact reroute requires review."],
                "confidence": 0.9,
                "missing_information": [],
            },
        }
        self.calls: List[str] = []

    def generate_structured_json(
        self,
        *,
        prompt: str,
        response_schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        **_: Any,
    ) -> Any:
        for marker, payload in self._payloads.items():
            if marker in prompt:
                self.calls.append(marker)
                return payload
        raise AssertionError(f"No scripted response for prompt: {prompt[:80]!r}")


def mumbai_request() -> RecoveryRequest:
    """The roadmap walkthrough as a supervisor request against the demo data."""
    return RecoveryRequest(
        disruption_report=DisruptionReport(
            event_id="EV-STEP9-MUMBAI-E2E",
            headline="Militant attack closes the Bab-el-Mandeb route",
            description=(
                "Maersk suspended Red Sea transits after attacks on merchant "
                "vessels. Shipment SH001 is delayed and needs a reroute or "
                "inventory cover at Rotterdam."
            ),
            source="Maritime security alert feed",
            reported_at=REPORTED_AT,
            location_hint="Bab-el-Mandeb, Red Sea",
        ),
        scenario_request=ScenarioRequest(
            event_id="EV-STEP9-MUMBAI-E2E",
            disruption_type="Maritime Security Threat",
            location="Bab-el-Mandeb, Red Sea",
            severity="High",
            origin="Mumbai",
            destination="Rotterdam",
            cargo_value_usd=SHIPMENT_VALUE_USD,
            container_count=4,
            transport_mode="Sea",
            current_carrier="Maersk",
            available_budget_usd=500_000.0,
            congestion_days=4,
            risk_factors=[
                "Active physical threat to vessels, cargo or personnel",
                "Route closure or forced diversion",
                "Carrier suspended or reduced service",
                "Reported schedule delay",
                "Disruption is ongoing or unresolved",
            ],
            inventory=RebalancingRequest(
                material_id="MAT-PHARMA-001",
                target_plant="Rotterdam DC",
                demand_forecast=20_000.0,
                committed=2_000.0,
                average_daily_demand=400.0,
                lead_time_days=7.0,
                demand_std_dev=100.0,
                lead_time_std_dev=2.0,
                service_level_percent=95.0,
            ),
        ),
        applicable_rules=list(DEFAULT_COMPLIANCE_RULES),
        supplier_id="SUP001",
        supplier_risk_tier="Medium",
        origin_country="India",
        destination_country="Netherlands",
        transit_countries=["Egypt", "Saudi Arabia"],
        certifications=["GDP", "WHO-GMP"],
        is_high_impact_reroute=True,
    )


def build_mumbai_workflow(gemini: ScriptedGemini) -> SupervisorWorkflow:
    """The supervisor wired to the real simulated connectors and demo seed data."""
    agents = build_agents(
        gemini=gemini,  # type: ignore[arg-type]
        repository=InMemorySupplyChainRepository(),
        sap=SimulatedSAPConnector(),
        mapping=SimulatedMappingConnector(),
        carriers=SimulatedCarrierConnector(),
    )
    graph = build_graph(agents=agents, checkpointer=in_memory_checkpointer())
    return SupervisorWorkflow(graph)


def test_mumbai_rotterdam_run_uses_the_seeded_lane_and_inventory() -> None:
    gemini = ScriptedGemini()
    workflow = build_mumbai_workflow(gemini)

    state = workflow.invoke(mumbai_request(), thread_id="EV-STEP9-MUMBAI-E2E")

    # All five agents really ran: sensing, scenario (which composes rerouting
    # and inventory), and the compliance audit.
    assert gemini.calls.count(SENSING_MARKER) == 1
    assert gemini.calls.count(SCENARIO_MARKER) == 1
    assert gemini.calls.count(REROUTING_MARKER) == 1
    assert gemini.calls.count(REBALANCING_MARKER) == 1
    assert gemini.calls.count(AUDIT_MARKER) == 1

    # The maritime report is linked to the real SH001/SUP001 master records.
    assessment = state["assessment"]
    assert assessment["disruption_type"] == "Maritime Security Threat"
    assert assessment["severity"] in {"High", "Critical"}
    assert assessment["risk_score"] >= 60
    assert "SH001" in assessment["affected_shipments"]
    assert "SUP001" in assessment["affected_suppliers"]

    # Scenario comparison produced ranked alternatives and a recommendation.
    plan = state["scenario_plan"]
    assert plan is not None
    assert len(plan["scenarios"]) >= 3
    assert plan["recommended_scenario_id"] is not None
    assert state["scenario_screening"] is not None

    # Inventory cover was computed from the real SAP sample rows: Rotterdam DC
    # is short, and the plan closes (or reduces) that shortage with transfers.
    assert plan["inventory_shortage_after"] is not None
    assert plan["inventory_impact"]
    assert plan["inventory_can_cover_disruption"] is True
    assert plan["inventory_shortage_after"] <= 0

    # The high-value reroute is compliant but needs a human decision.
    assert state["status"] == STATUS_AWAITING_APPROVAL
    payload = pending_interrupt(state)
    assert payload is not None
    assert payload["approval_level"] == "Director"
    assert payload["is_compliant"] is True
    assert payload["proposal_version"]

    resumed = workflow.resume(
        {"approved": True, "comment": "Approved for the Step 9 walkthrough"},
        thread_id="EV-STEP9-MUMBAI-E2E",
    )
    assert resumed["status"] == STATUS_COMPLETED
    recommendation = resumed["recommendation"]
    assert recommendation["status"] == STATUS_COMPLETED
    assert recommendation["delegated_agents"] == [
        AGENT_SENSING,
        AGENT_SCENARIO,
        AGENT_COMPLIANCE,
    ]


def test_mumbai_rotterdam_approval_executes_the_planned_transfer_only_once() -> None:
    gemini = ScriptedGemini()
    workflow = build_mumbai_workflow(gemini)
    thread_id = "EV-STEP9-MUMBAI-E2E-EXEC"

    paused = workflow.invoke(mumbai_request(), thread_id=thread_id)
    payload = pending_interrupt(paused)
    assert payload is not None

    repository = InMemoryApprovalRepository()
    service = ApprovalService(
        repository=repository,
        authorizer=ApprovalAuthorizer(f"{DIRECTOR_TOKEN}:step9-director:Director"),
        execution=ExecutionService(
            adapter=SimulatedExecutionAdapter(), store=repository
        ),
    )

    outcome = service.decide(
        thread_id=thread_id,
        authorization=f"Bearer {DIRECTOR_TOKEN}",
        request=ApprovalDecisionRequest(
            action=ApprovalAction.APPROVE,
            comment="Step 9 E2E approval",
            proposal_version=payload["proposal_version"],
        ),
        workflow=workflow,
    )

    assert outcome.workflow_status == STATUS_COMPLETED
    assert outcome.approval_status.value == "approved"
    assert outcome.decision.approver_id == "step9-director"

    execution = outcome.execution
    assert execution is not None
    assert execution.status.value == "completed"
    action_types = [action.action_type for action in execution.actions]
    # The approved inventory transfer is part of the executed plan.
    assert ExecutionActionType.SHIPMENT_PLAN_UPDATE in action_types
    assert ExecutionActionType.INVENTORY_TRANSFER in action_types
    assert ExecutionActionType.SAP_EXECUTION in action_types
    for action in execution.actions:
        assert action.is_mock is True
        assert action.message.startswith("[SIMULATED]")

    # A replay cannot execute the approved proposal again.
    with pytest.raises(ApprovalConflictError):
        service.decide(
            thread_id=thread_id,
            authorization=f"Bearer {DIRECTOR_TOKEN}",
            request=ApprovalDecisionRequest(
                action=ApprovalAction.APPROVE,
                comment="Duplicated approval",
                proposal_version=payload["proposal_version"],
            ),
            workflow=workflow,
        )
    assert len(repository.get(thread_id).execution.actions) == len(action_types)


DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"


def _load_demo_request(name: str) -> RecoveryRequest:
    payload = json.loads((DEMO_DIR / name).read_text(encoding="utf-8"))
    return RecoveryRequest.model_validate(payload["request"])


def test_demo_payloads_are_valid_and_the_replan_variant_replans() -> None:
    """The shipped demo JSON must drive the documented flows unchanged."""
    base = _load_demo_request("mumbai_rotterdam_scenario.json")
    assert base.scenario_request.origin == "Mumbai"
    assert base.scenario_request.destination == "Rotterdam"
    assert base.scenario_request.inventory is not None
    assert base.scenario_request.inventory.target_plant == "Rotterdam DC"
    assert base.supplier_id == "SUP001"

    replan = _load_demo_request("mumbai_rotterdam_replan_scenario.json")
    workflow = build_mumbai_workflow(ScriptedGemini())
    state = workflow.invoke(replan, thread_id="EV-DEMO-RED-SEA-REPLAN")

    # The three-day ceiling rejects the Sea alternatives and the supervisor
    # records exactly one revision, preserving the rejected plan.
    assert state["replan_rounds"] == 1
    assert len(state["scenario_history"]) == 1
    assert state["scenario_history"][0]["rejected_scenario_ids"]
    assert state["scenario_plan"]["revision_round"] == 1
    assert state["scenario_plan"]["scenarios"]
