"""Step 3 tests for the Inventory Rebalancing Agent (Agent 4).

The SAP connector and Gemini are replaced with deterministic test doubles so the
arithmetic below can be checked by hand. The most important assertions are the ones
that prove the roadmap rule *"never transfer inventory that is unavailable or
already committed"* is enforced by arithmetic, not by prompting:

* only stock **above** a plant's safety stock is ever released;
* committed stock is excluded from the available balance.

The remaining scenarios cover the single-plant case, the no-shortage case, the
calculated safety-stock path, provenance labelling and failure handling.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Sequence, Tuple

import pytest

from app.agents.inventory_rebalancing import (
    LLM_REBALANCING_SCHEMA,
    InventoryRebalancingAgent,
    InventoryRebalancingError,
)
from app.integrations.sap import SimulatedSAPConnector
from app.schemas.rebalancing_schemas import RebalancingRequest
from app.services.gemini_service import GeminiNotConfiguredError
from tests.fakes import FakeSAPConnector, StubGeminiService, make_inventory_item


def llm_response(**overrides: Any) -> Dict[str, Any]:
    """A schema-shaped LLM response with sensible defaults."""
    response: Dict[str, Any] = {
        "explanation": "Balance is restored by moving surplus stock from PlantA.",
        "confidence": 0.7,
        "missing_information": [],
    }
    response.update(overrides)
    return response


def build_agent(
    response: Any, inventory: Sequence[Any]
) -> Tuple[InventoryRebalancingAgent, StubGeminiService]:
    stub = StubGeminiService(response)
    agent = InventoryRebalancingAgent(
        gemini=stub,  # type: ignore[arg-type]
        sap=FakeSAPConnector(inventory),
    )
    return agent, stub


def three_plant_inventory() -> Tuple[Any, ...]:
    """One plant with surplus, the target, and one plant already below safety."""
    return (
        make_inventory_item("MAT-TEST-001", "PlantA", on_hand=1000.0, safety_stock=200.0),
        make_inventory_item("MAT-TEST-001", "PlantB", on_hand=300.0, safety_stock=500.0),
        make_inventory_item("MAT-TEST-001", "PlantC", on_hand=300.0, safety_stock=500.0),
    )


# ---------------------------------------------------------------------------
# Deterministic allocation
# ---------------------------------------------------------------------------


def test_rebalancing_releases_only_the_surplus_above_safety_stock() -> None:
    agent, _ = build_agent(llm_response(), three_plant_inventory())
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-TEST-001",
            target_plant="PlantB",
            demand_forecast=1000.0,
        )
    )

    assert plan.target_plant == "PlantB"
    # Safety stock falls back to the SAP-recorded value because no demand history
    # was supplied.
    assert plan.safety_stock_requirement == 500
    # required = 1000 demand + 500 safety = 1500; available = 300 on hand.
    assert plan.required_units == 1500.0
    assert plan.available_units == 300.0
    assert plan.shortage_before == 1200.0

    assert len(plan.transfer_recommendations) == 1
    transfer = plan.transfer_recommendations[0]
    assert (transfer.from_plant, transfer.to_plant) == ("PlantA", "PlantB")
    assert transfer.units == 800.0
    assert transfer.source_on_hand_before == 1000.0
    assert transfer.source_on_hand_after == 200.0
    assert transfer.preserves_safety_stock is True
    # The source still holds exactly its safety stock afterwards, never less.
    assert transfer.source_on_hand_after >= 200.0

    assert plan.total_transferred_units == 800.0
    assert plan.shortage_after == 400.0
    assert plan.availability_improvement_percent == 66.67

    # PlantC holds nothing above its safety stock, so its stock is refused, not used.
    assert len(plan.rejected_transfers) == 1
    rejection = plan.rejected_transfers[0]
    assert rejection.from_plant == "PlantC"
    assert "safety stock" in rejection.reason


def test_rebalancing_excludes_committed_stock_from_the_available_balance() -> None:
    inventory = (
        make_inventory_item("MAT-COMMIT-001", "PlantA", on_hand=1000.0, safety_stock=100.0),
        make_inventory_item("MAT-COMMIT-001", "PlantB", on_hand=1000.0, safety_stock=100.0),
    )
    agent, _ = build_agent(llm_response(), inventory)
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-COMMIT-001",
            target_plant="PlantA",
            demand_forecast=1500.0,
            committed=400.0,
        )
    )

    # available = 1000 - 400 committed = 600; required = 1500 + 100 = 1600.
    assert plan.available_units == 600.0
    assert plan.shortage_before == 1000.0
    assert plan.total_transferred_units == 900.0
    assert plan.shortage_after == 100.0
    assert any("committed" in gap for gap in plan.missing_information)


def test_rebalancing_reports_every_plant_position_with_the_target_flagged() -> None:
    agent, _ = build_agent(llm_response(), three_plant_inventory())
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-TEST-001", target_plant="PlantB", demand_forecast=1000.0
        )
    )

    positions = {position.plant: position for position in plan.inventory_positions}
    assert set(positions) == {"PlantA", "PlantB", "PlantC"}
    assert positions["PlantA"].transferable_units == 800.0
    assert positions["PlantC"].transferable_units == 0.0
    assert positions["PlantB"].is_target is True
    assert positions["PlantA"].is_target is False


def test_rebalancing_uses_the_largest_plant_when_no_target_is_supplied() -> None:
    agent, _ = build_agent(llm_response(), three_plant_inventory())
    plan = agent.plan(
        RebalancingRequest(material_id="MAT-TEST-001", demand_forecast=1000.0)
    )

    # PlantA holds the largest stock, so it is chosen deterministically.
    assert plan.target_plant == "PlantA"


# ---------------------------------------------------------------------------
# Calculated safety stock
# ---------------------------------------------------------------------------


def test_rebalancing_calculates_safety_stock_when_demand_history_is_supplied() -> None:
    inventory = (
        make_inventory_item("MAT-CALC-001", "PlantA", on_hand=5000.0, safety_stock=100.0),
        make_inventory_item("MAT-CALC-001", "PlantB", on_hand=3000.0, safety_stock=100.0),
    )
    agent, _ = build_agent(llm_response(), inventory)
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-CALC-001",
            target_plant="PlantA",
            average_daily_demand=100.0,
            lead_time_days=5.0,
            demand_std_dev=10.0,
            lead_time_std_dev=0.0,
            service_level_percent=95.0,
        )
    )

    # z(95%) * sqrt(5 * 10^2) = 1.65 * 22.3607 = 36.895 -> rounded up to 37.
    assert plan.safety_stock_requirement == 37
    assert any("app.tools.safety_stock" in line for line in plan.assumptions)


# ---------------------------------------------------------------------------
# No shortage / no alternative warehouse
# ---------------------------------------------------------------------------


def test_rebalancing_reports_no_transfer_when_there_is_no_shortage() -> None:
    inventory = (
        make_inventory_item("MAT-COVER-001", "PlantA", on_hand=1000.0, safety_stock=200.0),
        make_inventory_item("MAT-COVER-001", "PlantB", on_hand=500.0, safety_stock=100.0),
    )
    agent, _ = build_agent(llm_response(), inventory)
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-COVER-001", target_plant="PlantA", demand_forecast=100.0
        )
    )

    assert plan.shortage_before == 0.0
    assert plan.transfer_recommendations == []
    assert plan.shortage_after == 0.0
    assert plan.availability_improvement_percent == 0.0
    assert any("no shortage" in gap.lower() for gap in plan.missing_information)


def test_rebalancing_flags_a_single_plant_material() -> None:
    inventory = (
        make_inventory_item("MAT-SOLO-001", "PlantX", on_hand=500.0, safety_stock=100.0),
    )
    agent, _ = build_agent(llm_response(), inventory)
    plan = agent.plan(
        RebalancingRequest(material_id="MAT-SOLO-001", demand_forecast=2000.0)
    )

    assert plan.target_plant == "PlantX"
    assert plan.transfer_recommendations == []
    assert plan.shortage_before == 1600.0
    assert plan.shortage_after == 1600.0
    assert any(
        "only plant holding this material" in gap.lower()
        for gap in plan.missing_information
    )


# ---------------------------------------------------------------------------
# Provenance and the "the model cannot decide" contract
# ---------------------------------------------------------------------------


def test_rebalancing_evidence_keeps_simulated_data_unmistakable() -> None:
    agent, _ = build_agent(llm_response(), three_plant_inventory())
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-TEST-001", target_plant="PlantB", demand_forecast=1000.0
        )
    )

    assert plan.evidence
    assert all(item.source.endswith("[SIMULATED]") for item in plan.evidence)


def test_number_producing_fields_are_not_offered_to_the_model() -> None:
    properties = LLM_REBALANCING_SCHEMA["properties"]
    for forbidden in (
        "shortage_before",
        "shortage_after",
        "total_transferred_units",
        "transfer_recommendations",
        "safety_stock_requirement",
    ):
        assert forbidden not in properties


def test_model_cannot_change_the_allocation() -> None:
    agent, stub = build_agent(
        llm_response(explanation="Move all 1000 units from PlantA immediately."),
        three_plant_inventory(),
    )
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-TEST-001", target_plant="PlantB", demand_forecast=1000.0
        )
    )

    # The arithmetic decides: 800 units, not the 1000 the narrative suggests.
    assert plan.total_transferred_units == 800.0
    prompt = stub.calls[0]["prompt"]
    assert "800.0 units" in prompt
    assert "Never suggest using it" in stub.calls[0]["system_instruction"]


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_unknown_material_raises_a_clear_error() -> None:
    agent, _ = build_agent(llm_response(), three_plant_inventory())
    with pytest.raises(InventoryRebalancingError) as excinfo:
        agent.plan(RebalancingRequest(material_id="MAT-NONE-999", demand_forecast=10.0))
    assert "not present in any plant" in str(excinfo.value)


def test_unknown_target_plant_raises_a_clear_error() -> None:
    agent, _ = build_agent(llm_response(), three_plant_inventory())
    with pytest.raises(InventoryRebalancingError) as excinfo:
        agent.plan(
            RebalancingRequest(
                material_id="MAT-TEST-001", target_plant="PlantZ", demand_forecast=10.0
            )
        )
    assert "does not hold material" in str(excinfo.value)


def test_malformed_model_output_raises_a_clear_error() -> None:
    agent, _ = build_agent({"confidence": 5.0}, three_plant_inventory())
    with pytest.raises(InventoryRebalancingError) as excinfo:
        agent.plan(
            RebalancingRequest(
                material_id="MAT-TEST-001", target_plant="PlantB", demand_forecast=1000.0
            )
        )
    assert "does not match the expected schema" in str(excinfo.value)


def test_missing_api_key_surfaces_as_a_configuration_error() -> None:
    agent, _ = build_agent(
        GeminiNotConfiguredError("GEMINI_API_KEY is not configured"),
        three_plant_inventory(),
    )
    with pytest.raises(GeminiNotConfiguredError):
        agent.plan(
            RebalancingRequest(
                material_id="MAT-TEST-001", target_plant="PlantB", demand_forecast=1000.0
            )
        )


# ---------------------------------------------------------------------------
# Opt-in live check against the real Gemini API (simulated SAP data)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1",
    reason="Set RUN_LIVE_GEMINI=1 to call the live Gemini API.",
)
def test_live_gemini_rebalancing_on_demo_inventory() -> None:
    """Real Gemini call over the demo SAP inventory. Costs one API request."""
    agent = InventoryRebalancingAgent(sap=SimulatedSAPConnector())
    plan = agent.plan(
        RebalancingRequest(
            material_id="MAT-ELEC-003", target_plant="Rotterdam DC", demand_forecast=9000.0
        )
    )

    assert plan.target_plant == "Rotterdam DC"
    assert plan.explanation
    assert plan.missing_information is not None
