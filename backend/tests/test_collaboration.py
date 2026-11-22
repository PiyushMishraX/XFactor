"""Step 5 tests for multi-agent collaboration and autonomous replanning.

These tests exercise the collaboration layer end to end through the compiled
supervisor graph, reusing the scripted Gemini double and connector fakes from the
Step 4 tests. They assert only things that actually happened:

* every issued task matches a supervisor decision that really occurred;
* every recorded tool call was made by the agent that really ran;
* screening reuses the deterministic compliance, budget and approval engines;
* a rejected recommendation opens a bounded feedback loop that preserves the
  previous plan;
* unavailable integrations are recorded and skipped rather than faked;
* retries produce one execution record per real attempt.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from app.integrations.base import IntegrationNotConfiguredError
from app.orchestration.collaboration import AGENT_TOOLS, MAX_REPLAN_ROUNDS
from app.orchestration.state import (
    AGENT_COMPLIANCE,
    AGENT_REBALANCING,
    AGENT_REROUTING,
    AGENT_SCENARIO,
    AGENT_SENSING,
    STATUS_COMPLETED,
    STATUS_NO_COMPLIANT_RECOVERY,
)
from app.orchestration.workflow import SupervisorWorkflow, build_agents, build_graph
from app.tools.compliance import ComplianceRule, RuleType
from tests.fakes import (
    FakeCarrierConnector,
    FakeMappingConnector,
    FakeSAPConnector,
    InMemorySupplyChainRepository,
)
from tests.test_orchestration import (
    DEFAULT_INVENTORY,
    DEFAULT_SERVICES,
    SENSING_MARKER,
    DispatchingGemini,
    direct_path_gemini,
    make_request,
)

_ALL_TOOLS = {tool for tools in AGENT_TOOLS.values() for tool in tools}


class UnavailableSAPConnector:
    """A SAP connector whose live credentials are missing."""

    name = "sap"
    is_mock = False

    def list_inventory(self) -> Any:
        raise IntegrationNotConfiguredError("SAP credentials are not configured")


def build_workflow(
    *,
    gemini: Optional[DispatchingGemini] = None,
    sap: Any = None,
) -> SupervisorWorkflow:
    agents = build_agents(
        gemini=gemini or DispatchingGemini(),  # type: ignore[arg-type]
        repository=InMemorySupplyChainRepository(),
        sap=sap or FakeSAPConnector(DEFAULT_INVENTORY),
        mapping=FakeMappingConnector(distance_km=1000.0),
        carriers=FakeCarrierConnector(DEFAULT_SERVICES),
    )
    return SupervisorWorkflow(build_graph(agents=agents))


def executions_for(recommendation: dict, agent: str) -> list:
    return [item for item in recommendation["agent_executions"] if item["agent"] == agent]


def tasks_for(recommendation: dict, agent: str) -> list:
    return [item for item in recommendation["tasks"] if item["agent"] == agent]


def request_with_rules(rules: list) -> Any:
    """A standard supervisor request with an explicit compliance rule set."""
    return make_request().model_copy(update={"applicable_rules": rules})


# ---------------------------------------------------------------------------
# Tasks, executions and tool calls reflect real work
# ---------------------------------------------------------------------------


def test_every_task_matches_a_supervisor_decision_that_occurred() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-task-decisions")
    recommendation = state["recommendation"]

    decisions = {
        (entry["step"], entry["action"]): entry["reason"]
        for entry in recommendation["decision_log"]
    }
    for task in recommendation["tasks"]:
        assert (task["step"], task["agent"]) in decisions, task
        assert task["reason"] == decisions[(task["step"], task["agent"])]
        assert task["objective"]
        assert task["tools"]

    assert [task["agent"] for task in recommendation["tasks"]] == [
        AGENT_SENSING,
        AGENT_SCENARIO,
        AGENT_COMPLIANCE,
    ]
    # One completed execution per task, in the same order.
    assert [item["task_id"] for item in recommendation["agent_executions"]] == [
        task["task_id"] for task in recommendation["tasks"]
    ]
    assert all(
        item["status"] == "completed" for item in recommendation["agent_executions"]
    )


def test_recorded_tool_calls_are_the_calls_the_agents_actually_made() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-tool-calls")
    recommendation = state["recommendation"]

    recorded = recommendation["tool_calls"]
    assert recorded, "no tool call was recorded"
    assert {call["tool"] for call in recorded} <= _ALL_TOOLS

    # The flat list is exactly the executions' tool calls, not a second account.
    flattened = [
        call
        for execution in recommendation["agent_executions"]
        for call in execution["tool_calls"]
    ]
    assert recorded == flattened

    sensing = executions_for(recommendation, AGENT_SENSING)[0]
    sensing_tools = {call["tool"] for call in sensing["tool_calls"]}
    assert {
        "supply_chain_repository.snapshot",
        "risk_scoring.compute_risk_score",
        "gemini.generate_structured_json",
    } <= sensing_tools

    scenario = executions_for(recommendation, AGENT_SCENARIO)[0]
    scenario_tools = {call["tool"] for call in scenario["tool_calls"]}
    assert {
        "mapping.get_route",
        "carriers.list_services",
        "rerouting_logistics.analyse",
        "route_optimization.rank_routes",
        "gemini.generate_structured_json",
    } <= scenario_tools

    compliance = executions_for(recommendation, AGENT_COMPLIANCE)[0]
    compliance_tools = {call["tool"] for call in compliance["tool_calls"]}
    assert {
        "compliance.validate_compliance",
        "budget.validate_budget",
        "approval.evaluate_approval",
        "gemini.generate_structured_json",
    } <= compliance_tools

    assert all(call["status"] == "ok" for call in recorded)


def test_tool_calls_carry_mock_labelling_and_real_durations() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-tool-meta")
    calls = {call["tool"]: call for call in state["recommendation"]["tool_calls"]}

    assert calls["mapping.get_route"]["is_mock"] is True
    assert calls["carriers.list_services"]["is_mock"] is True
    assert calls["compliance.validate_compliance"]["is_mock"] is False
    for call in calls.values():
        assert call["duration_ms"] >= 0.0


# ---------------------------------------------------------------------------
# Deterministic screening of the scenario plan
# ---------------------------------------------------------------------------


def test_screening_evaluates_every_scenario_with_the_audit_engines() -> None:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-screening")
    recommendation = state["recommendation"]

    screening = recommendation["scenario_screening"]
    assert screening is not None
    plan = state["scenario_plan"]
    assert screening["scenario_count"] == len(plan["scenarios"]) == 3
    assert [item["scenario_id"] for item in screening["evaluations"]] == [
        item["scenario_id"] for item in plan["scenarios"]
    ]

    recommended = [item for item in screening["evaluations"] if item["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["scenario_id"] == plan["recommended_scenario_id"]
    assert screening["recommended_verdict"] == "Approved"
    assert screening["all_rejected"] is False

    assert recommendation["replanning_rounds"] == 0
    assert recommendation["replanning"] == []
    assert recommendation["scenario_history"] == []


# ---------------------------------------------------------------------------
# Conditional replanning with history preservation
# ---------------------------------------------------------------------------


def test_rejected_recommendation_triggers_a_revision_that_preserves_the_old_plan() -> None:
    # A 3-day lead-time ceiling rejects the slower Sea scenarios (3.43 days) and
    # keeps the Rail alternative (2.75 days), so the first plan has no compliant
    # recommendation and the supervisor must ask for a revision.
    rules = [
        ComplianceRule(
            rule_id="POL-TEST-LEAD-TIME",
            description="Test ceiling for the replanning path.",
            rule_type=RuleType.MAX_LEAD_TIME,
            max_value=3.0,
        )
    ]
    workflow = build_workflow()
    state = workflow.invoke(request_with_rules(rules), thread_id="t-replan")
    recommendation = state["recommendation"]

    assert state["status"] == STATUS_COMPLETED
    assert recommendation["replanning_rounds"] == 1

    # Exactly one screening rejected the first plan, for stated reasons.
    assert len(recommendation["replanning"]) == 1
    record = recommendation["replanning"][0]
    assert record["round"] == 1
    assert record["trigger"] == "deterministic screening"
    assert set(record["rejected_scenario_ids"]) == {"SC1", "SC3"}
    assert set(record["previous_scenario_ids"]) == {"SC1", "SC2", "SC3"}
    assert record["revision"]["round"] == 1
    assert record["reasons"]

    # The rejected plan and its evaluation are preserved, not overwritten.
    assert len(recommendation["scenario_history"]) == 1
    history = recommendation["scenario_history"][0]
    assert history["round"] == 1
    assert len(history["plan"]["scenarios"]) == 3
    assert len(history["evaluations"]) == 3
    assert set(history["rejected_scenario_ids"]) == {"SC1", "SC3"}

    # The revised plan contains only the alternative that still validates.
    final_plan = state["scenario_plan"]
    assert [item["scenario_id"] for item in final_plan["scenarios"]] == ["SC2"]
    assert final_plan["revision_round"] == 1
    assert set(final_plan["rejected_scenario_ids"]) == {"SC1", "SC3"}

    # Every scenario execution is a real, separate attempt with its own task.
    scenario_executions = executions_for(recommendation, AGENT_SCENARIO)
    assert [item["attempt"] for item in scenario_executions] == [1, 2]
    scenario_tasks = tasks_for(recommendation, AGENT_SCENARIO)
    assert len(scenario_tasks) == 2
    assert scenario_tasks[0]["revision"] is None
    assert scenario_tasks[1]["revision"]["round"] == 1
    assert set(scenario_tasks[1]["revision"]["rejected_scenario_ids"]) == {"SC1", "SC3"}
    assert "revision round 1" in scenario_tasks[1]["reason"]


def test_replanning_stops_without_a_compliant_recovery() -> None:
    # No carrier in the catalogue meets this floor, so every alternative fails.
    rules = [
        ComplianceRule(
            rule_id="POL-TEST-RELIABILITY",
            description="Impossible reliability floor for the bound test.",
            rule_type=RuleType.MIN_CARRIER_RELIABILITY,
            max_value=1.5,
        )
    ]
    workflow = build_workflow()
    state = workflow.invoke(
        request_with_rules(rules), thread_id="t-replan-stop"
    )
    recommendation = state["recommendation"]

    assert state["status"] == STATUS_NO_COMPLIANT_RECOVERY
    assert recommendation["status"] == STATUS_NO_COMPLIANT_RECOVERY
    assert recommendation["replanning_rounds"] <= MAX_REPLAN_ROUNDS
    assert len(executions_for(recommendation, AGENT_SCENARIO)) == 2
    assert "no compliant recovery" in recommendation["headline"].lower()
    # Nothing was audited: no proposal ever passed deterministic validation.
    assert AGENT_COMPLIANCE not in recommendation["delegated_agents"]
    assert state.get("audit_report") is None


# ---------------------------------------------------------------------------
# Unavailable tools
# ---------------------------------------------------------------------------


def test_unavailable_sap_is_recorded_and_the_task_is_skipped() -> None:
    workflow = build_workflow(gemini=direct_path_gemini(), sap=UnavailableSAPConnector())
    request = make_request(
        scenario={
            "inventory": {
                "material_id": "MAT-TEST-001",
                "target_plant": "PlantB",
                "demand_forecast": 1000.0,
            }
        }
    )

    state = workflow.invoke(request, thread_id="t-unavailable-sap")
    recommendation = state["recommendation"]

    assert state["status"] == STATUS_COMPLETED
    assert recommendation["skipped_agents"] == [AGENT_REBALANCING]
    assert AGENT_REBALANCING not in recommendation["delegated_agents"]

    skipped = executions_for(recommendation, AGENT_REBALANCING)
    assert len(skipped) == 1
    assert skipped[0]["status"] == "skipped"
    assert {call["tool"] for call in skipped[0]["tool_calls"]} == {"sap.list_inventory"}
    assert skipped[0]["tool_calls"][0]["status"] == "unavailable"
    assert any(
        "integration is unavailable" in gap
        for gap in recommendation["missing_information"]
    )


def test_unavailable_inventory_inside_scenario_planning_degrades_gracefully() -> None:
    workflow = build_workflow(sap=UnavailableSAPConnector())
    request = make_request(
        scenario={
            "inventory": {
                "material_id": "MAT-TEST-001",
                "target_plant": "PlantB",
                "demand_forecast": 1000.0,
            }
        }
    )

    state = workflow.invoke(request, thread_id="t-unavailable-inventory")
    recommendation = state["recommendation"]

    assert state["status"] == STATUS_COMPLETED
    assert state["scenario_plan"] is not None

    scenario = executions_for(recommendation, AGENT_SCENARIO)[0]
    unavailable = {
        call["tool"]: call["status"]
        for call in scenario["tool_calls"]
        if call["status"] == "unavailable"
    }
    assert unavailable == {
        "sap.list_inventory": "unavailable",
        "inventory_rebalancing.plan": "unavailable",
    }
    assert any(
        "inventory integration is unavailable" in gap
        for gap in recommendation["missing_information"]
    )


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_each_retry_is_recorded_as_its_own_failed_execution() -> None:
    gemini = DispatchingGemini({SENSING_MARKER: {"confidence": 2.0}})
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-retry-executions")
    recommendation = state["recommendation"]

    sensing = executions_for(recommendation, AGENT_SENSING)
    assert [item["attempt"] for item in sensing] == [1, 2]
    assert [item["status"] for item in sensing] == ["failed", "failed"]
    assert all(item["error"] for item in sensing)
    assert state["attempts"] == {AGENT_SENSING: 1}

    # The failed Gemini call itself is recorded, not invented.
    for execution in sensing:
        tools = {call["tool"] for call in execution["tool_calls"]}
        assert "gemini.generate_structured_json" in tools


# ---------------------------------------------------------------------------
# Architectural contracts
# ---------------------------------------------------------------------------


def test_collaboration_state_survives_a_json_round_trip() -> None:
    rules = [
        ComplianceRule(
            rule_id="POL-TEST-LEAD-TIME",
            description="Test ceiling for the JSON contract.",
            rule_type=RuleType.MAX_LEAD_TIME,
            max_value=3.0,
        )
    ]
    workflow = build_workflow()
    state = workflow.invoke(request_with_rules(rules), thread_id="t-json")

    json.dumps(state)
    assert state["recommendation"]["tool_calls"]
    assert state["recommendation"]["scenario_screening"] is not None
    assert state["recommendation"]["scenario_history"]
    assert state["recommendation"]["replanning"]


def test_only_selected_agents_receive_tasks() -> None:
    gemini = DispatchingGemini()
    workflow = build_workflow(gemini=gemini)
    state = workflow.invoke(make_request(), thread_id="t-unrelated-tasks")

    recommendation = state["recommendation"]
    task_agents = [task["agent"] for task in recommendation["tasks"]]
    assert task_agents == recommendation["delegated_agents"]
    assert AGENT_REROUTING not in task_agents
    assert AGENT_REBALANCING not in task_agents


@pytest.mark.parametrize("agent", [AGENT_SENSING, AGENT_SCENARIO, AGENT_COMPLIANCE])
def test_tasks_name_the_tools_the_agent_owns(agent: str) -> None:
    assert agent in AGENT_TOOLS
    assert all("." in tool for tool in AGENT_TOOLS[agent])
