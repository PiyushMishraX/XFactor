"""Step 3 tests for the Scenario Planning Agent (Agent 2).

Agent 2 is the composition point of Step 3: it requests Agent 3 (rerouting) and
Agent 4 (inventory rebalancing) and then scores the recovery alternatives with the
same deterministic engine Agent 3 uses. All three agents are driven by separate
Gemini stubs so the arithmetic can be checked by hand, and the tests assert both the
composition and the architectural contract (the model contributes no number).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Sequence, Tuple

import pytest

from app.agents.inventory_rebalancing import InventoryRebalancingAgent, InventoryRebalancingError
from app.agents.rerouting_logistics import ReroutingLogisticsAgent, ReroutingLogisticsError
from app.agents.scenario_planning import (
    LLM_SCENARIO_SCHEMA,
    ScenarioPlanningAgent,
    ScenarioPlanningError,
)
from app.schemas.rebalancing_schemas import RebalancingRequest
from app.schemas.scenario_schemas import ScenarioFeasibility, ScenarioRequest
from app.services.gemini_service import GeminiNotConfiguredError
from tests.fakes import (
    FakeCarrierConnector,
    FakeMappingConnector,
    FakeSAPConnector,
    StubGeminiService,
    make_carrier_service,
    make_inventory_item,
)

#: One Sea carrier (the incumbent), a second Sea carrier, and a Rail carrier. This is
#: the minimum data that lets the agent build all three recovery approaches.
FIXTURE_SERVICES = (
    make_carrier_service("CarrierA", "Sea", reliability=0.90, service_name="Alpha"),
    make_carrier_service("CarrierB", "Sea", reliability=0.95, service_name="Bravo"),
    make_carrier_service("CarrierC", "Rail", reliability=0.99, service_name="Charlie"),
)

REROUTING_LLM: Dict[str, Any] = {
    "explanation": "Rail is the fastest option on this lane.",
    "route_risks": [],
    "confidence": 0.8,
    "missing_information": [],
}

REBALANCING_LLM: Dict[str, Any] = {
    "explanation": "Balance is restored by moving surplus stock from PlantA.",
    "confidence": 0.7,
    "missing_information": [],
}


def three_plant_inventory() -> Tuple[Any, ...]:
    """The same hand-built inventory fixture Agent 4's tests use."""
    return (
        make_inventory_item("MAT-TEST-001", "PlantA", on_hand=1000.0, safety_stock=200.0),
        make_inventory_item("MAT-TEST-001", "PlantB", on_hand=300.0, safety_stock=500.0),
        make_inventory_item("MAT-TEST-001", "PlantC", on_hand=300.0, safety_stock=500.0),
    )


def llm_response(**overrides: Any) -> Dict[str, Any]:
    """A schema-shaped scenario narrative with sensible defaults."""
    response: Dict[str, Any] = {
        "recommendation_rationale": (
            "SC3 keeps the sea mode but improves carrier reliability at the same cost."
        ),
        "scenario_assessments": [
            {"scenario_id": "SC1", "assessment": "Cheapest but the least reliable carrier."},
            {"scenario_id": "SC2", "assessment": "Rail is faster but materially pricier."},
            {"scenario_id": "SC3", "assessment": "Best balance of cost and reliability."},
        ],
        "confidence": 0.85,
        "missing_information": [],
    }
    response.update(overrides)
    return response


def make_request(**overrides: Any) -> ScenarioRequest:
    payload: Dict[str, Any] = {
        "event_id": "EV-SCENARIO-1",
        "disruption_type": "Port congestion",
        "origin": "Mumbai",
        "destination": "Rotterdam",
        "cargo_value_usd": 100_000.0,
        "container_count": 1.0,
        "transport_mode": "Sea",
        "current_carrier": "CarrierA",
        "available_budget_usd": 1_000_000.0,
    }
    payload.update(overrides)
    return ScenarioRequest(**payload)


def build_agent(
    scenario_response: Any,
    *,
    rerouting_response: Any = REROUTING_LLM,
    rebalancing_response: Any = REBALANCING_LLM,
    services: Sequence[Any] = FIXTURE_SERVICES,
    inventory: Sequence[Any] = three_plant_inventory(),
    distance_km: float = 1000.0,
    is_estimated: bool = False,
) -> Tuple[ScenarioPlanningAgent, StubGeminiService]:
    scenario_stub = StubGeminiService(scenario_response)
    rerouting = ReroutingLogisticsAgent(
        gemini=StubGeminiService(rerouting_response),  # type: ignore[arg-type]
        mapping=FakeMappingConnector(distance_km=distance_km, is_estimated=is_estimated),
        carriers=FakeCarrierConnector(services),
    )
    rebalancing = InventoryRebalancingAgent(
        gemini=StubGeminiService(rebalancing_response),  # type: ignore[arg-type]
        sap=FakeSAPConnector(inventory),
    )
    agent = ScenarioPlanningAgent(
        gemini=scenario_stub,  # type: ignore[arg-type]
        rerouting=rerouting,
        rebalancing=rebalancing,
    )
    return agent, scenario_stub


# ---------------------------------------------------------------------------
# Deterministic scenario construction and ranking
# ---------------------------------------------------------------------------


def test_scenario_plan_builds_and_ranks_three_recovery_approaches() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request())

    assert [scenario.scenario_id for scenario in plan.scenarios] == ["SC3", "SC1", "SC2"]
    assert [scenario.rank for scenario in plan.scenarios] == [1, 2, 3]
    assert plan.recommended_scenario_id == "SC3"

    by_id = {scenario.scenario_id: scenario for scenario in plan.scenarios}
    assert by_id["SC1"].approach == "Continue existing route"
    assert by_id["SC2"].approach == "Change transport mode"
    assert by_id["SC3"].approach == "Change carrier"

    # Deterministic costs/days from app.tools at 1000 km, 1 container, 100k cargo.
    assert by_id["SC1"].total_cost_usd == 1010.00
    assert by_id["SC2"].total_cost_usd == 1520.00
    assert by_id["SC3"].total_cost_usd == 1010.00
    assert by_id["SC1"].total_days == 3.429
    assert by_id["SC2"].total_days == 2.75
    assert by_id["SC3"].total_days == 3.429

    # The scorecard decides the order: SC3 edges SC1/SC2 on carrier reliability.
    assert by_id["SC3"].weighted_score == 0.6556
    assert by_id["SC1"].weighted_score == 0.60
    assert by_id["SC2"].weighted_score == 0.60
    assert all(
        scenario.feasibility is ScenarioFeasibility.FEASIBLE for scenario in plan.scenarios
    )

    # The recommendation is the same mode and cost as the incumbent, so both deltas
    # are exactly zero — the agent does not manufacture an improvement.
    assert plan.cost_delta_vs_current_usd == 0.0
    assert plan.days_delta_vs_current == 0.0
    assert plan.confidence == 0.85


def test_scenario_plan_reports_only_two_scenarios_when_data_is_limited() -> None:
    # No second carrier on the incumbent mode, so the carrier-change approach
    # cannot be built.
    services = (FIXTURE_SERVICES[0], FIXTURE_SERVICES[2])
    agent, _ = build_agent(
        llm_response(
            scenario_assessments=[
                {"scenario_id": "SC1", "assessment": "Incumbent."},
                {"scenario_id": "SC2", "assessment": "Rail."},
            ]
        ),
        services=services,
    )
    plan = agent.plan(make_request())

    assert [scenario.scenario_id for scenario in plan.scenarios] == ["SC1", "SC2"]
    assert any(
        "at least three" in gap.lower() for gap in plan.missing_information
    )


def test_scenario_plan_notes_when_the_incumbent_is_not_in_master_data() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request(current_carrier="Unknown Lines"))

    continues = next(
        scenario for scenario in plan.scenarios if scenario.approach == "Continue existing route"
    )
    assert any(
        "not present in the carrier master data" in note for note in continues.notes
    )


# ---------------------------------------------------------------------------
# Feasibility tiering
# ---------------------------------------------------------------------------


def test_scenario_plan_marks_scenarios_needing_finance_approval() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request(available_budget_usd=1200.0))

    by_id = {scenario.scenario_id: scenario for scenario in plan.scenarios}
    assert by_id["SC1"].feasibility is ScenarioFeasibility.FEASIBLE
    assert by_id["SC3"].feasibility is ScenarioFeasibility.FEASIBLE
    assert by_id["SC2"].feasibility is ScenarioFeasibility.FEASIBLE_WITH_APPROVAL
    assert any("finance approval is required" in note for note in by_id["SC2"].notes)


def test_scenario_plan_reports_unknown_affordability_without_a_budget() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request(available_budget_usd=0.0))

    assert all(
        scenario.feasibility is ScenarioFeasibility.UNKNOWN for scenario in plan.scenarios
    )
    joined = " ".join(note for scenario in plan.scenarios for note in scenario.notes)
    assert "No available budget was supplied" in joined


# ---------------------------------------------------------------------------
# The model's per-scenario assessments
# ---------------------------------------------------------------------------


def test_scenario_plan_attaches_model_assessments_to_the_matching_scenarios() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request())

    by_id = {scenario.scenario_id: scenario for scenario in plan.scenarios}
    assert "Best balance of cost and reliability." in by_id["SC3"].notes
    assert "Cheapest but the least reliable carrier." in by_id["SC1"].notes


def test_scenario_plan_ignores_assessments_for_unknown_scenario_ids() -> None:
    agent, _ = build_agent(
        llm_response(
            scenario_assessments=[
                {"scenario_id": "SC9", "assessment": "This scenario does not exist."}
            ]
        )
    )
    plan = agent.plan(make_request())

    assert all(
        "This scenario does not exist." not in note
        for scenario in plan.scenarios
        for note in scenario.notes
    )


# ---------------------------------------------------------------------------
# Composition with Agents 3 and 4
# ---------------------------------------------------------------------------


def test_scenario_plan_flags_a_missing_inventory_analysis() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request())

    assert plan.inventory_impact == ""
    assert plan.inventory_shortage_after is None
    assert plan.inventory_can_cover_disruption is False
    assert any(
        "No inventory impact analysis was requested" in gap
        for gap in plan.missing_information
    )


def test_scenario_plan_folds_in_the_inventory_analysis_when_requested() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(
        make_request(
            inventory=RebalancingRequest(
                material_id="MAT-TEST-001",
                target_plant="PlantB",
                demand_forecast=1000.0,
            )
        )
    )

    assert plan.inventory_impact == REBALANCING_LLM["explanation"]
    assert plan.inventory_shortage_after == 400.0
    assert plan.inventory_can_cover_disruption is False
    assert any(item.source.endswith("[SIMULATED]") for item in plan.evidence)


def test_scenario_plan_carries_sub_agent_evidence_and_gaps() -> None:
    agent, _ = build_agent(llm_response())
    plan = agent.plan(make_request())

    assert plan.evidence
    assert plan.evidence[0].source == "Scenario Planning Agent"
    assert any(item.source.endswith("[SIMULATED]") for item in plan.evidence)
    assert any(
        "No disruption risk factors were supplied" in gap
        for gap in plan.missing_information
    )


# ---------------------------------------------------------------------------
# The model cannot be the source of a number
# ---------------------------------------------------------------------------


def test_number_producing_fields_are_not_offered_to_the_model() -> None:
    properties = LLM_SCENARIO_SCHEMA["properties"]
    for forbidden in (
        "rank",
        "weighted_score",
        "total_cost_usd",
        "total_days",
        "feasibility",
        "scenarios",
    ):
        assert forbidden not in properties


def test_model_cannot_change_the_recommendation() -> None:
    agent, stub = build_agent(
        llm_response(recommendation_rationale="SC1 is clearly the best choice.")
    )
    plan = agent.plan(make_request())

    assert plan.recommended_scenario_id == "SC3"
    prompt = stub.calls[0]["prompt"]
    assert "do not change these numbers" in prompt
    assert "DETERMINISTIC RECOMMENDATION: SC3" in prompt
    assert "SC1 | rank 2" in prompt


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_malformed_model_output_raises_a_clear_error() -> None:
    agent, _ = build_agent({"confidence": 2.0})
    with pytest.raises(ScenarioPlanningError) as excinfo:
        agent.plan(make_request())
    assert "does not match the expected schema" in str(excinfo.value)


def test_missing_api_key_surfaces_as_a_configuration_error() -> None:
    agent, _ = build_agent(GeminiNotConfiguredError("GEMINI_API_KEY is not configured"))
    with pytest.raises(GeminiNotConfiguredError):
        agent.plan(make_request())


def test_rerouting_failure_propagates() -> None:
    agent, _ = build_agent(llm_response(), rerouting_response={"confidence": 2.0})
    with pytest.raises(ReroutingLogisticsError):
        agent.plan(make_request())


def test_rebalancing_failure_propagates() -> None:
    agent, _ = build_agent(llm_response(), rebalancing_response={"confidence": 5.0})
    with pytest.raises(InventoryRebalancingError):
        agent.plan(
            make_request(
                inventory=RebalancingRequest(material_id="MAT-TEST-001", demand_forecast=10.0)
            )
        )


# ---------------------------------------------------------------------------
# Opt-in live check against the real Gemini API (simulated data connectors)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1",
    reason="Set RUN_LIVE_GEMINI=1 to call the live Gemini API.",
)
def test_live_gemini_scenario_plan_on_the_demo_lane() -> None:
    """Real Gemini calls (one per composed agent). Costs a few API requests."""
    from app.integrations.carriers import SimulatedCarrierConnector
    from app.integrations.mapping import SimulatedMappingConnector
    from app.integrations.sap import SimulatedSAPConnector

    agent = ScenarioPlanningAgent(
        rerouting=ReroutingLogisticsAgent(
            mapping=SimulatedMappingConnector(),
            carriers=SimulatedCarrierConnector(),
        ),
        rebalancing=InventoryRebalancingAgent(sap=SimulatedSAPConnector()),
    )
    plan = agent.plan(
        make_request(
            event_id="EV-LIVE-SCENARIO",
            current_carrier="Maersk",
            inventory=RebalancingRequest(
                material_id="MAT-ELEC-003",
                target_plant="Rotterdam DC",
                demand_forecast=9000.0,
            ),
        )
    )

    assert plan.scenarios
    assert plan.recommended_scenario_id is not None
    assert plan.recommendation_rationale
