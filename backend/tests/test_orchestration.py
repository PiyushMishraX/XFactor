"""Step 4 tests for the LangGraph supervisor and orchestration layer.

The supervisor is exercised through the same dependency-injection seams the agent
tests use: one Gemini double answers every agent from its own canned payload, and
the external connectors are the Step 3 fakes. That makes the six roadmap scenarios
deterministic without a provider or a database.

Covered here:

1. a normal disruption, end to end;
2. a disruption affecting more than one shipment (the scenario path);
3. missing route information;
4. no feasible recovery;
5. an agent failure;
6. invalid agent output.

Plus the approval interrupt/resume path, the architectural contract that the state
stores JSON rather than live Pydantic objects, and an opt-in live check.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest

from app.orchestration.checkpointing import in_memory_checkpointer
from app.orchestration.state import (
    AGENT_COMPLIANCE,
    AGENT_NODES,
    AGENT_REBALANCING,
    AGENT_REROUTING,
    AGENT_SCENARIO,
    AGENT_SENSING,
    DEFAULT_COMPLIANCE_RULES,
    NODE_APPROVAL_GATE,
    NODE_ERROR,
    NODE_FINALIZE,
    NODE_SUPERVISOR,
    STATUS_APPROVAL_REJECTED,
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_ITERATION_LIMIT,
    STATUS_NO_ACTION,
    STATUS_NO_FEASIBLE_RECOVERY,
    RecoveryRequest,
)
from app.orchestration.workflow import (
    SupervisorWorkflow,
    build_agents,
    build_graph,
    mermaid_diagram,
    pending_interrupt,
)
from app.schemas.disruption_schemas import DisruptionReport
from app.schemas.scenario_schemas import ScenarioRequest
from app.services.gemini_service import GeminiNotConfiguredError
from tests.fakes import (
    FakeCarrierConnector,
    FakeMappingConnector,
    FakeSAPConnector,
    InMemorySupplyChainRepository,
    make_carrier_service,
    make_inventory_item,
)

# ---------------------------------------------------------------------------
# Scripted model output
# ---------------------------------------------------------------------------

SENSING_MARKER = "Assess the disruption report below"
REROUTING_MARKER = "Explain the deterministic logistics ranking below"
REBALANCING_MARKER = "Explain the deterministic inventory rebalancing plan below"
SCENARIO_MARKER = "Explain the deterministic recovery scenario ranking below"
AUDIT_MARKER = "Explain the deterministic audit verdict below"


#: A supply-chain disruption at a location that matches three demo shipments.
SENSING_PAYLOAD: Dict[str, Any] = {
    "is_supply_chain_disruption": True,
    "disruption_type": "Port Congestion",
    "description": "Severe congestion at the port delays outbound shipments.",
    "affected_locations": ["Mumbai"],
    "risk_factors": ["Port closure or severe congestion", "Reported schedule delay"],
    "potential_impact": ["Delayed departures"],
    "mentioned_shipment_ids": [],
    "mentioned_supplier_ids": [],
    "recommended_next_action": "Investigate berth availability.",
    "confidence": 0.8,
    "evidence": [{"source": "Reuters", "description": "Port congestion reported."}],
    "missing_information": [],
    "contradictions": [],
}

#: The same report at a location that matches no master-data row.
SENSING_SINGLE_SHIPMENT_PAYLOAD: Dict[str, Any] = {
    **SENSING_PAYLOAD,
    "affected_locations": ["Reykjavik"],
}

#: News that is not a supply-chain disruption at all.
SENSING_UNRELATED_PAYLOAD: Dict[str, Any] = {
    **SENSING_PAYLOAD,
    "is_supply_chain_disruption": False,
    "disruption_type": "Unrelated",
    "description": "A regional sporting event.",
    "affected_locations": [],
    "risk_factors": [],
    "potential_impact": [],
    "recommended_next_action": "No supply-chain action required.",
}

REROUTING_PAYLOAD: Dict[str, Any] = {
    "explanation": "The ranking follows the deterministic scorecard.",
    "route_risks": ["Congestion on the incumbent lane."],
    "confidence": 0.7,
    "missing_information": [],
}

REBALANCING_PAYLOAD: Dict[str, Any] = {
    "explanation": "Balance is restored by moving surplus stock from PlantA.",
    "confidence": 0.7,
    "missing_information": [],
}

SCENARIO_PAYLOAD: Dict[str, Any] = {
    "recommendation_rationale": "The top-ranked scenario has the best scorecard.",
    "scenario_assessments": [{"scenario_id": "SC1", "assessment": "Cheapest option."}],
    "confidence": 0.75,
    "missing_information": [],
}

AUDIT_PAYLOAD: Dict[str, Any] = {
    "explanation": "The deterministic verdict follows the rule findings.",
    "regulatory_notes": ["No restricted country on the route."],
    "operational_policy_notes": ["Spend is below the approval threshold."],
    "confidence": 0.9,
    "missing_information": [],
}


class DispatchingGemini:
    """A Gemini double that answers each agent from its own canned payload.

    Responses are keyed by a marker that appears in that agent's prompt, so a
    single double can drive all five agents exactly as :func:`build_agents` wires
    them. A payload may also be an exception instance, which the double raises.
    """

    def __init__(self, overrides: Optional[Dict[str, Any]] = None) -> None:
        self._payloads: Dict[str, Any] = {
            SENSING_MARKER: dict(SENSING_PAYLOAD),
            REROUTING_MARKER: dict(REROUTING_PAYLOAD),
            REBALANCING_MARKER: dict(REBALANCING_PAYLOAD),
            SCENARIO_MARKER: dict(SCENARIO_PAYLOAD),
            AUDIT_MARKER: dict(AUDIT_PAYLOAD),
        }
        if overrides:
            self._payloads.update(overrides)
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
                if isinstance(payload, Exception):
                    raise payload
                return json.loads(json.dumps(payload))
        raise AssertionError(f"No scripted response for prompt: {prompt[:80]!r}")


def direct_path_gemini(overrides: Optional[Dict[str, Any]] = None) -> DispatchingGemini:
    """A double whose disruption matches no shipment, so no scenarios are warranted."""
    payloads: Dict[str, Any] = {
        SENSING_MARKER: dict(SENSING_SINGLE_SHIPMENT_PAYLOAD),
    }
    if overrides:
        payloads.update(overrides)
    return DispatchingGemini(payloads)


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------

#: Two carriers: one on the incumbent Sea mode, one on Rail.
DEFAULT_SERVICES = (
    make_carrier_service("CarrierA", "Sea", reliability=0.92, service_name="Alpha"),
    make_carrier_service("CarrierB", "Rail", reliability=0.95, service_name="Bravo"),
)

#: One material held at three plants, so a transfer can be recommended.
DEFAULT_INVENTORY = (
    make_inventory_item("MAT-TEST-001", "PlantA", on_hand=1000.0, safety_stock=200.0),
    make_inventory_item("MAT-TEST-001", "PlantB", on_hand=300.0, safety_stock=500.0),
    make_inventory_item("MAT-TEST-001", "PlantC", on_hand=300.0, safety_stock=500.0),
)


def make_report(**overrides: Any) -> DisruptionReport:
    payload: Dict[str, Any] = {
        "event_id": "EV-ORCH-1",
        "headline": "Port congestion at Mumbai",
        "description": "Severe congestion delays outbound vessels.",
        "source": "Reuters",
        "reported_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
        "location_hint": "Mumbai",
    }
    payload.update(overrides)
    return DisruptionReport(**payload)


def make_request(
    *,
    scenario: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> RecoveryRequest:
    """A complete supervisor request. ``overrides`` target ``RecoveryRequest`` itself."""
    payload: Dict[str, Any] = {
        "event_id": "EV-ORCH-1",
        "disruption_type": "Port Congestion",
        "location": "Mumbai",
        "severity": "Moderate",
        "origin": "Mumbai",
        "destination": "Rotterdam",
        "cargo_value_usd": 100_000.0,
        "available_budget_usd": 500_000.0,
        "risk_factors": ["Port closure or severe congestion"],
    }
    payload.update(scenario or {})
    return RecoveryRequest(
        disruption_report=make_report(),
        scenario_request=ScenarioRequest(**payload),
        applicable_rules=list(DEFAULT_COMPLIANCE_RULES),
        **overrides,
    )


def build_workflow(
    *,
    gemini: Optional[DispatchingGemini] = None,
    services: Optional[Sequence[Any]] = None,
    inventory: Optional[Sequence[Any]] = None,
    distance_km: float = 1000.0,
    is_estimated: bool = False,
    checkpointer: Any = None,
) -> SupervisorWorkflow:
    """Compile a supervisor around scripted agents and Step 3 connector fakes."""
    agents = build_agents(
        gemini=gemini or DispatchingGemini(),  # type: ignore[arg-type]
        repository=InMemorySupplyChainRepository(),
        sap=FakeSAPConnector(DEFAULT_INVENTORY if inventory is None else inventory),
        mapping=FakeMappingConnector(distance_km=distance_km, is_estimated=is_estimated),
        carriers=FakeCarrierConnector(DEFAULT_SERVICES if services is None else services),
    )
    graph = build_graph(
        agents=agents, checkpointer=checkpointer or in_memory_checkpointer()
    )
    return SupervisorWorkflow(graph)


# ---------------------------------------------------------------------------
# 1. A normal disruption, end to end
# ---------------------------------------------------------------------------


def test_normal_disruption_runs_end_to_end_through_the_scenario_path() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-normal")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_COMPLETED
    assert recommendation["status"] == STATUS_COMPLETED
    assert recommendation["event_id"] == "EV-ORCH-1"

    # Every delegated agent ran exactly once, in the order the supervisor chose.
    assert recommendation["delegated_agents"] == [
        AGENT_SENSING,
        AGENT_SCENARIO,
        AGENT_COMPLIANCE,
    ]
    assert [entry["action"] for entry in recommendation["decision_log"]] == [
        AGENT_SENSING,
        AGENT_SCENARIO,
        AGENT_COMPLIANCE,
        NODE_FINALIZE,
    ]
    assert recommendation["iterations"] == 3

    assert recommendation["recommended_scenario_id"] is not None
    assert recommendation["recommended_carrier"]
    assert recommendation["audit_verdict"] == "Approved"
    assert recommendation["requires_approval"] is False
    assert recommendation["headline"]


def test_every_supervisor_decision_states_its_reason() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-reasons")

    for entry in state["recommendation"]["decision_log"]:
        assert entry["step"] >= 1
        assert entry["action"]
        assert len(entry["reason"]) > 20
        assert entry["action"] in {*AGENT_NODES, NODE_FINALIZE, NODE_APPROVAL_GATE}


# ---------------------------------------------------------------------------
# 2. A disruption affecting more than one shipment
# ---------------------------------------------------------------------------


def test_multiple_affected_shipments_trigger_a_scenario_comparison() -> None:
    gemini = DispatchingGemini()
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-multi")

    # The sensing agent linked three demo shipments to the Mumbai disruption.
    assert len(state["assessment"]["affected_shipments"]) > 1

    # The supervisor therefore asked for a ranked comparison of alternatives
    # rather than a single lane analysis.
    assert state["scenario_plan"] is not None
    assert state.get("rerouting") is None
    assert state.get("rebalancing") is None

    # Scenario Planning composes the rerouting and inventory agents itself, so the
    # supervisor must not run them again as separate nodes.
    assert gemini.calls.count(REROUTING_MARKER) == 1
    assert gemini.calls.count(SCENARIO_MARKER) == 1


def test_direct_path_uses_the_logistics_analysis_when_scenarios_are_not_warranted() -> None:
    workflow = build_workflow(gemini=direct_path_gemini())
    state = workflow.invoke(make_request(), thread_id="t-direct")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_COMPLETED
    assert state.get("scenario_plan") is None
    assert recommendation["delegated_agents"] == [
        AGENT_SENSING,
        AGENT_REROUTING,
        AGENT_COMPLIANCE,
    ]
    assert recommendation["recommended_route_id"] is not None
    assert recommendation["recommended_scenario_id"] is None


def test_inventory_analysis_runs_only_when_the_caller_requests_it() -> None:
    workflow = build_workflow(gemini=direct_path_gemini())
    request = make_request(
        scenario={
            "inventory": {
                "material_id": "MAT-TEST-001",
                "target_plant": "PlantB",
                "demand_forecast": 1000.0,
            }
        }
    )

    state = workflow.invoke(request, thread_id="t-inventory")

    # The caller asked for inventory analysis, so the rebalancing node ran.
    assert state["rebalancing"] is not None

    # The allocator moves enough stock to count as a major redistribution, so the
    # audit correctly escalates to a human before any recommendation is issued.
    payload = pending_interrupt(state)
    assert payload is not None
    assert state["status"] == STATUS_AWAITING_APPROVAL

    resumed = workflow.resume(
        {"approved": True, "comment": "Approved"}, thread_id="t-inventory"
    )
    assert AGENT_REBALANCING in resumed["recommendation"]["delegated_agents"]


# ---------------------------------------------------------------------------
# 3. Missing route information
# ---------------------------------------------------------------------------


def test_missing_route_information_is_recorded_as_a_gap() -> None:
    workflow = build_workflow(gemini=direct_path_gemini(), is_estimated=True)
    state = workflow.invoke(
        make_request(scenario={"current_carrier": "Ghost Lines"}), thread_id="t-gaps"
    )

    assert state["status"] == STATUS_COMPLETED
    assert state["rerouting"] is not None

    gaps = state["recommendation"]["missing_information"]
    # The lane distance had to be derived...
    assert any("derived rather than measured" in gap for gap in gaps)
    # ...and the incumbent carrier is absent from the carrier master data.
    assert any("Ghost Lines" in gap for gap in gaps)


# ---------------------------------------------------------------------------
# 4. No feasible recovery
# ---------------------------------------------------------------------------


def test_no_feasible_recovery_short_circuits_before_the_audit() -> None:
    workflow = build_workflow(gemini=direct_path_gemini(), services=())
    state = workflow.invoke(make_request(), thread_id="t-norecovery")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_NO_FEASIBLE_RECOVERY
    assert recommendation["status"] == STATUS_NO_FEASIBLE_RECOVERY
    # A zero-cost proposal must never be audited as if it were a recovery.
    assert recommendation["audit_verdict"] is None
    assert AGENT_COMPLIANCE not in recommendation["delegated_agents"]
    assert "no feasible recovery" in recommendation["headline"].lower()


def test_unrelated_report_stops_the_workflow_without_delegating_further() -> None:
    gemini = DispatchingGemini({SENSING_MARKER: dict(SENSING_UNRELATED_PAYLOAD)})
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-unrelated")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_NO_ACTION
    assert recommendation["delegated_agents"] == [AGENT_SENSING]
    assert recommendation["recommended_scenario_id"] is None
    # Nothing beyond sensing was requested from the model.
    assert gemini.calls == [SENSING_MARKER]


# ---------------------------------------------------------------------------
# 5. Agent failure
# ---------------------------------------------------------------------------


def test_agent_failure_from_a_missing_key_is_not_retried() -> None:
    gemini = DispatchingGemini(
        {SENSING_MARKER: GeminiNotConfiguredError("GEMINI_API_KEY is not configured")}
    )
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-fail")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_FAILED
    assert gemini.calls == [SENSING_MARKER]
    assert recommendation["delegated_agents"] == []
    assert any("GEMINI_API_KEY" in error for error in recommendation["errors"])
    assert "failed" in recommendation["headline"].lower()


def test_agent_failure_stops_before_the_compliance_audit() -> None:
    gemini = DispatchingGemini({SCENARIO_MARKER: GeminiNotConfiguredError("no key")})
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-fail-late")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_FAILED
    assert AGENT_SENSING in recommendation["delegated_agents"]
    assert AGENT_SCENARIO not in recommendation["delegated_agents"]
    assert AGENT_COMPLIANCE not in recommendation["delegated_agents"]
    assert state.get("audit_report") is None
    assert AUDIT_MARKER not in gemini.calls


# ---------------------------------------------------------------------------
# 6. Invalid agent output
# ---------------------------------------------------------------------------


def test_invalid_agent_output_is_retried_once_then_fails() -> None:
    # A confidence above 1 violates the sensing schema, so the agent raises a
    # DisruptionSensingError — a transient-looking failure the supervisor retries.
    gemini = DispatchingGemini({SENSING_MARKER: {"confidence": 2.0}})
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-invalid")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_FAILED
    assert gemini.calls == [SENSING_MARKER, SENSING_MARKER]
    assert state["attempts"] == {AGENT_SENSING: 1}

    # The retry is visible in the decision log, and two failures are recorded.
    assert [entry["action"] for entry in recommendation["decision_log"]] == [
        AGENT_SENSING,
        AGENT_SENSING,
    ]
    assert any("does not match the expected schema" in error for error in recommendation["errors"])
    assert len(recommendation["errors"]) == 2


def test_invalid_output_from_a_later_agent_does_not_lose_earlier_work() -> None:
    gemini = DispatchingGemini({AUDIT_MARKER: {"confidence": 5.0}})
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-invalid-late")

    recommendation = state["recommendation"]
    assert state["status"] == STATUS_FAILED
    # The assessment and the scenario plan survived the later failure.
    assert state["assessment"] is not None
    assert state["scenario_plan"] is not None
    assert state.get("audit_report") is None
    assert AGENT_SENSING in recommendation["delegated_agents"]
    assert AGENT_SCENARIO in recommendation["delegated_agents"]
    assert AGENT_COMPLIANCE not in recommendation["delegated_agents"]


# ---------------------------------------------------------------------------
# Workflow interruption and resume
# ---------------------------------------------------------------------------


def test_approval_gate_interrupts_and_resumes_from_the_checkpoint() -> None:
    workflow = build_workflow()
    request = make_request(is_high_impact_reroute=True)

    paused = workflow.invoke(request, thread_id="t-approval")
    payload = pending_interrupt(paused)

    assert payload is not None
    assert payload["type"] == "approval_required"
    assert payload["approval_level"] == "Director"
    assert payload["is_compliant"] is True
    assert paused["status"] == STATUS_AWAITING_APPROVAL
    assert paused.get("approval") is None

    resumed = workflow.resume(
        {"approved": True, "comment": "Approved by Ops"}, thread_id="t-approval"
    )
    assert resumed["status"] == STATUS_COMPLETED
    assert resumed["approval"]["approved"] is True
    assert resumed["approval"]["comment"] == "Approved by Ops"
    assert resumed["approval"]["decided_by"] == "human"
    assert resumed["recommendation"]["status"] == STATUS_COMPLETED


def test_approval_gate_records_a_rejection() -> None:
    workflow = build_workflow()
    workflow.invoke(make_request(is_high_impact_reroute=True), thread_id="t-reject")
    resumed = workflow.resume(
        {"approved": False, "comment": "Margin too thin"}, thread_id="t-reject"
    )

    assert resumed["status"] == STATUS_APPROVAL_REJECTED
    assert resumed["approval"]["approved"] is False
    assert resumed["recommendation"]["status"] == STATUS_APPROVAL_REJECTED
    assert any(
        "Margin too thin" in error for error in resumed["recommendation"]["errors"]
    )


def test_a_business_as_usual_proposal_does_not_interrupt() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-noapproval")

    assert pending_interrupt(state) is None
    assert state["status"] == STATUS_COMPLETED
    assert state["recommendation"]["requires_approval"] is False


# ---------------------------------------------------------------------------
# Architectural contracts
# ---------------------------------------------------------------------------


def test_agent_nodes_store_json_dictionaries_not_pydantic_objects() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-json")

    for key in ("assessment", "scenario_plan", "audit_report", "recommendation"):
        assert isinstance(state[key], dict), key

    # The whole state must survive a JSON round-trip, which is what the
    # PostgreSQL checkpointer stores.
    json.dumps(state)


def test_missing_information_is_deduplicated_across_agents() -> None:
    workflow = build_workflow(gemini=direct_path_gemini(), is_estimated=True)
    state = workflow.invoke(make_request(), thread_id="t-dedupe")

    gaps = state["recommendation"]["missing_information"]
    assert len(gaps) == len(set(gaps))


def test_graph_exposes_a_mermaid_visualisation_of_every_node() -> None:
    workflow = build_workflow()
    diagram = mermaid_diagram(workflow.graph)

    for node in (NODE_SUPERVISOR, *AGENT_NODES, NODE_APPROVAL_GATE, NODE_ERROR, NODE_FINALIZE):
        assert node in diagram
    assert diagram.startswith("---")


def test_supervisor_stops_at_its_iteration_bound() -> None:
    from app.config.settings import get_settings
    from app.orchestration.workflow import build_supervisor_node

    # Bound = LANGGRAPH_MAX_ITERATIONS * five agents = 2 * 5 = 10 passes.
    settings = get_settings().model_copy(update={"LANGGRAPH_MAX_ITERATIONS": 2})
    supervisor = build_supervisor_node(settings)
    request = make_request()
    state = {
        "request": request.model_dump(mode="json"),
        "assessment": dict(SENSING_PAYLOAD),
        "step": 10,
    }

    update = supervisor(state)

    assert update["next_action"] == NODE_FINALIZE
    assert update["status"] == STATUS_ITERATION_LIMIT
    assert "safety bound" in update["decisions"][0]["reason"]


# ---------------------------------------------------------------------------
# Opt-in live check against the real Gemini API (simulated data connectors)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1",
    reason="Set RUN_LIVE_GEMINI=1 to call the live Gemini API.",
)
def test_live_supervisor_on_the_demo_lane() -> None:
    """Real Gemini calls; the connectors stay simulated so no credentials leak in."""
    from app.integrations.carriers import SimulatedCarrierConnector
    from app.integrations.mapping import SimulatedMappingConnector
    from app.integrations.sap import SimulatedSAPConnector

    agents = build_agents(
        repository=InMemorySupplyChainRepository(),
        sap=SimulatedSAPConnector(),
        mapping=SimulatedMappingConnector(),
        carriers=SimulatedCarrierConnector(),
    )
    workflow = SupervisorWorkflow(
        build_graph(agents=agents, checkpointer=in_memory_checkpointer())
    )
    state = workflow.invoke(
        make_request(
            scenario={
                "event_id": "EV-LIVE-ORCH",
                "severity": "High",
                "current_carrier": "Maersk",
            }
        ),
        thread_id="t-live",
    )

    recommendation = state["recommendation"]
    assert state["status"] in {STATUS_COMPLETED, STATUS_AWAITING_APPROVAL, STATUS_NO_FEASIBLE_RECOVERY}
    assert recommendation["decision_log"]
    assert recommendation["headline"]
