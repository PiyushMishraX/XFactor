"""Step 3 tests for the Rerouting & Logistics Agent (Agent 3).

Gemini and the mapping / carrier connectors are replaced with deterministic test
doubles so the assertions are exact: every cost, transit time, risk score and rank
below is produced by ``app.tools`` and can be checked by hand.

The scenarios covered map onto the Step 3 checklist: deterministic ranking,
incumbent detection, mode filtering, no inventing a route, deterministic gap
detection, the "the model cannot change a number" contract, and failure handling.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

import pytest

from app.agents.rerouting_logistics import (
    LLM_REROUTING_SCHEMA,
    ReroutingLogisticsAgent,
    ReroutingLogisticsError,
)
from app.integrations.carriers import SimulatedCarrierConnector
from app.integrations.mapping import SimulatedMappingConnector
from app.schemas.rerouting_schemas import ReroutingRequest
from app.services.gemini_service import GeminiNotConfiguredError
from tests.fakes import (
    FakeCarrierConnector,
    FakeMappingConnector,
    StubGeminiService,
    make_carrier_service,
)

#: Sea / Rail / Air, one service per mode, with hand-checkable reliability.
FIXTURE_SERVICES = (
    make_carrier_service("CarrierA", "Sea", reliability=0.90, service_name="Alpha"),
    make_carrier_service("CarrierB", "Rail", reliability=0.95, service_name="Bravo"),
    make_carrier_service("CarrierC", "Air", reliability=0.99, service_name="Charlie"),
)

SEA_ID = "sea-carriera-alpha"
RAIL_ID = "rail-carrierb-bravo"
AIR_ID = "air-carrierc-charlie"


def llm_response(**overrides: Any) -> Dict[str, Any]:
    """A schema-shaped LLM response with sensible defaults."""
    response: Dict[str, Any] = {
        "explanation": "The rail option wins on cost and transit time.",
        "route_risks": [],
        "confidence": 0.8,
        "missing_information": [],
    }
    response.update(overrides)
    return response


def make_request(**overrides: Any) -> ReroutingRequest:
    payload: Dict[str, Any] = {
        "disruption_id": "EV-REROUTE-1",
        "origin": "Mumbai",
        "destination": "Rotterdam",
        "cargo_value_usd": 100000.0,
        "container_count": 1.0,
    }
    payload.update(overrides)
    return ReroutingRequest(**payload)


def build_agent(
    response: Any,
    *,
    services: Tuple[Any, ...] = FIXTURE_SERVICES,
    distance_km: float = 1000.0,
    is_estimated: bool = False,
) -> Tuple[ReroutingLogisticsAgent, StubGeminiService]:
    stub = StubGeminiService(response)
    agent = ReroutingLogisticsAgent(
        gemini=stub,  # type: ignore[arg-type]
        mapping=FakeMappingConnector(distance_km=distance_km, is_estimated=is_estimated),
        carriers=FakeCarrierConnector(services),
    )
    return agent, stub


# ---------------------------------------------------------------------------
# Deterministic ranking
# ---------------------------------------------------------------------------


def test_rerouting_scores_and_ranks_services_deterministically() -> None:
    agent, _ = build_agent(llm_response())
    analysis = agent.analyse(make_request())

    assert analysis.lane_distance_km == 1000.0
    assert analysis.lane_is_estimated is False

    by_id = {option.route_id: option for option in analysis.ranked_routes}
    assert set(by_id) == {SEA_ID, RAIL_ID, AIR_ID}

    # Costs from app.tools.costing at 1000 km, 1 container, 100k USD cargo,
    # no tariff: freight + handling + insurance.
    assert by_id[SEA_ID].total_cost_usd == 1010.00
    assert by_id[RAIL_ID].total_cost_usd == 1520.00
    assert by_id[AIR_ID].total_cost_usd == 9950.00

    # Days from app.tools.lead_time: distance/speed + mode handling.
    assert by_id[SEA_ID].total_days == 3.429
    assert by_id[RAIL_ID].total_days == 2.75
    assert by_id[AIR_ID].total_days == 1.125

    # No risk factors were supplied, so every option scores zero risk.
    assert {option.risk_score for option in analysis.ranked_routes} == {0}

    # The rail option wins the weighted scorecard; the two 0.60 options are
    # separated by cost, so the sea option outranks the air option.
    assert [option.route_id for option in analysis.ranked_routes] == [
        RAIL_ID,
        SEA_ID,
        AIR_ID,
    ]
    assert [option.rank for option in analysis.ranked_routes] == [1, 2, 3]
    assert analysis.recommended_route_id == RAIL_ID
    assert analysis.explanation == "The rail option wins on cost and transit time."
    assert analysis.confidence == 0.8


def test_rerouting_marks_the_incumbent_option_and_its_rank() -> None:
    agent, _ = build_agent(llm_response())
    analysis = agent.analyse(
        make_request(current_carrier="CarrierA", current_mode="Sea")
    )

    current = [option for option in analysis.ranked_routes if option.is_current_route]
    assert len(current) == 1
    assert current[0].route_id == SEA_ID
    assert analysis.current_route_rank == 2


def test_rerouting_leaves_current_route_unset_when_carrier_is_unknown() -> None:
    agent, _ = build_agent(llm_response())
    analysis = agent.analyse(
        make_request(current_carrier="Unknown Lines", current_mode="Sea")
    )

    assert all(option.is_current_route is False for option in analysis.ranked_routes)
    assert analysis.current_route_rank is None


def test_rerouting_filters_candidates_by_mode_case_insensitively() -> None:
    agent, _ = build_agent(llm_response())
    analysis = agent.analyse(make_request(candidate_modes=["air"]))

    assert [option.route_id for option in analysis.ranked_routes] == [AIR_ID]
    assert analysis.recommended_route_id == AIR_ID


def test_rerouting_never_invents_a_route_when_no_service_matches() -> None:
    agent, _ = build_agent(llm_response())
    analysis = agent.analyse(make_request(candidate_modes=["Road"]))

    assert analysis.ranked_routes == []
    assert analysis.recommended_route_id is None
    assert any(
        "no carrier service matched" in gap.lower()
        for gap in analysis.missing_information
    )


# ---------------------------------------------------------------------------
# Deterministic gap detection and provenance
# ---------------------------------------------------------------------------


def test_rerouting_reports_gaps_the_deterministic_layer_can_see() -> None:
    agent, _ = build_agent(llm_response(), is_estimated=True)
    analysis = agent.analyse(
        make_request(current_carrier="Unknown Lines", current_mode="Sea")
    )

    gaps = " ".join(analysis.missing_information).lower()
    assert "derived rather than measured" in gaps
    assert "is not among the configured carrier services" in gaps
    assert "no disruption risk factors were supplied" in gaps


def test_rerouting_evidence_keeps_simulated_data_unmistakable() -> None:
    agent, _ = build_agent(llm_response())
    analysis = agent.analyse(make_request())

    sources = [item.source for item in analysis.evidence]
    assert any(source.endswith("[SIMULATED]") for source in sources)
    assert any("1000.0 km" in item.description for item in analysis.evidence)


# ---------------------------------------------------------------------------
# The model cannot be the source of a number
# ---------------------------------------------------------------------------


def test_number_producing_fields_are_not_offered_to_the_model() -> None:
    properties = LLM_REROUTING_SCHEMA["properties"]
    for forbidden in (
        "total_cost_usd",
        "total_days",
        "risk_score",
        "weighted_score",
        "rank",
        "route_id",
        "recommended_route_id",
    ):
        assert forbidden not in properties


def test_model_cannot_change_the_recommendation() -> None:
    # The model claims the air option is best; the deterministic engine disagrees.
    agent, stub = build_agent(
        llm_response(explanation="Air is clearly the best choice.")
    )
    analysis = agent.analyse(make_request())

    assert analysis.recommended_route_id == RAIL_ID
    prompt = stub.calls[0]["prompt"]
    assert "1000.0 km" in prompt
    assert RAIL_ID in prompt
    assert "Do not re-rank" in stub.calls[0]["system_instruction"]


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_malformed_model_output_raises_a_clear_error() -> None:
    agent, _ = build_agent({"confidence": 2.0})
    with pytest.raises(ReroutingLogisticsError) as excinfo:
        agent.analyse(make_request())
    assert "does not match the expected schema" in str(excinfo.value)


def test_missing_api_key_surfaces_as_a_configuration_error() -> None:
    agent, _ = build_agent(GeminiNotConfiguredError("GEMINI_API_KEY is not configured"))
    with pytest.raises(GeminiNotConfiguredError):
        agent.analyse(make_request())


# ---------------------------------------------------------------------------
# Opt-in live check against the real Gemini API (simulated data connectors)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1",
    reason="Set RUN_LIVE_GEMINI=1 to call the live Gemini API.",
)
def test_live_gemini_rerouting_on_a_real_demo_lane() -> None:
    """Real Gemini call over the demo lane table. Costs one API request."""
    agent = ReroutingLogisticsAgent(
        mapping=SimulatedMappingConnector(),
        carriers=SimulatedCarrierConnector(),
    )
    analysis = agent.analyse(
        make_request(disruption_id="EV-LIVE-REROUTE", current_carrier="Maersk")
    )

    assert analysis.recommended_route_id is not None
    assert analysis.ranked_routes
    assert analysis.explanation
