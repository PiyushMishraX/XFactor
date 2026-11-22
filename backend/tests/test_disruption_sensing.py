"""Step 1 scenario tests for the Disruption Sensing Agent.

The five scenarios required by the roadmap are covered, plus reference validation
and failure handling. Gemini and PostgreSQL are replaced with deterministic test
doubles so the assertions are exact; live integration is verified separately by
``tests/test_supply_chain_repository.py`` (real database) and the opt-in live test
at the bottom of this module.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from app.agents.disruption_sensing import (
    LLM_ASSESSMENT_SCHEMA,
    NO_DISRUPTION_ACTION,
    UNKNOWN_LOCATION,
    DisruptionSensingAgent,
    DisruptionSensingError,
)
from app.schemas.disruption_schemas import (
    DISRUPTION_CATEGORIES,
    DisruptionCategory,
    DisruptionReport,
    RiskFactor,
    Severity,
)
from app.services.gemini_service import GeminiNotConfiguredError
from tests.fakes import InMemorySupplyChainRepository, StubGeminiService

REPORTED_AT = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def llm_response(**overrides: Any) -> Dict[str, Any]:
    """A schema-shaped LLM response with sensible defaults."""
    response: Dict[str, Any] = {
        "is_supply_chain_disruption": True,
        "disruption_type": DisruptionCategory.TRANSPORTATION_DELAY.value,
        "description": "A generic disruption.",
        "affected_locations": [],
        "risk_factors": [],
        "potential_impact": [],
        "mentioned_shipment_ids": [],
        "mentioned_supplier_ids": [],
        "recommended_next_action": "Review the report.",
        "confidence": 0.5,
        "evidence": [],
        "missing_information": [],
        "contradictions": [],
    }
    response.update(overrides)
    return response


def make_report(**overrides: Any) -> DisruptionReport:
    payload: Dict[str, Any] = {
        "headline": "Generic headline",
        "description": "Generic body text.",
        "source": "Reuters",
        "reported_at": REPORTED_AT,
    }
    payload.update(overrides)
    return DisruptionReport(**payload)


def build_agent(response: Any) -> tuple[DisruptionSensingAgent, StubGeminiService]:
    stub = StubGeminiService(response)
    agent = DisruptionSensingAgent(
        gemini=stub,  # type: ignore[arg-type]
        repository=InMemorySupplyChainRepository(),
    )
    return agent, stub


# ---------------------------------------------------------------------------
# 1. Maritime disruption
# ---------------------------------------------------------------------------


def test_maritime_disruption_is_scored_deterministically() -> None:
    agent, _ = build_agent(
        llm_response(
            disruption_type=DisruptionCategory.MARITIME_SECURITY_THREAT.value,
            description=(
                "Attacks on commercial shipping in the Red Sea have forced carriers "
                "to divert around the Cape of Good Hope."
            ),
            affected_locations=["Red Sea", "Bab-el-Mandeb"],
            risk_factors=[
                RiskFactor.ACTIVE_PHYSICAL_THREAT.value,
                RiskFactor.ROUTE_CLOSURE_OR_DIVERSION.value,
                RiskFactor.CARRIER_SERVICE_SUSPENSION.value,
                RiskFactor.HIGH_VOLUME_TRADE_LANE.value,
                RiskFactor.ONGOING_OR_UNRESOLVED.value,
            ],
            potential_impact=["Transit times increase by 10-14 days"],
            mentioned_shipment_ids=["SH001", "SH002"],
            recommended_next_action=(
                "Evaluate alternative shipping routes and quantify diversion cost."
            ),
            confidence=0.94,
            evidence=[{"source": "Reuters", "description": "Carriers divert around Africa."}],
        )
    )

    assessment = agent.assess(
        make_report(
            headline="Red Sea attacks force carrier diversions",
            description="Houthi attacks on commercial vessels have intensified.",
            source_url="https://example.com/red-sea",
        )
    )

    assert assessment.disruption_type is DisruptionCategory.MARITIME_SECURITY_THREAT
    assert assessment.location == "Red Sea"
    assert assessment.is_supply_chain_disruption is True

    # 22 + 20 + 14 + 12 + 12 (factors) + 15 (5 validated shipments, capped) = 95
    assert assessment.risk_score == 95
    assert assessment.severity is Severity.CRITICAL
    assert assessment.risk_breakdown == {
        RiskFactor.ACTIVE_PHYSICAL_THREAT.value: 22,
        RiskFactor.ROUTE_CLOSURE_OR_DIVERSION.value: 20,
        RiskFactor.CARRIER_SERVICE_SUSPENSION.value: 14,
        RiskFactor.HIGH_VOLUME_TRADE_LANE.value: 12,
        RiskFactor.ONGOING_OR_UNRESOLVED.value: 12,
    }
    assert assessment.reference_contributions["Validated affected shipments"] == 15
    # Referenced ids plus every shipment whose lane transits the Red Sea.
    assert sorted(assessment.affected_shipments) == ["SH001", "SH002", "SH003", "SH005", "SH010"]
    assert assessment.affected_suppliers == []
    assert assessment.unvalidated_shipment_references == []
    assert assessment.confidence == 0.94


# ---------------------------------------------------------------------------
# 2. Severe weather
# ---------------------------------------------------------------------------


def test_severe_weather_event_reports_affected_shipments_and_suppliers() -> None:
    agent, _ = build_agent(
        llm_response(
            disruption_type=DisruptionCategory.SEVERE_WEATHER.value,
            description="Typhoon forces the closure of Shanghai port terminals.",
            affected_locations=["Shanghai", "China"],
            risk_factors=[
                RiskFactor.PORT_CLOSURE_OR_SEVERE_CONGESTION.value,
                RiskFactor.REPORTED_SCHEDULE_DELAY.value,
                RiskFactor.ONGOING_OR_UNRESOLVED.value,
            ],
            potential_impact=["Berth closures halt loading"],
            recommended_next_action="Confirm berth availability before the next sailing.",
            confidence=0.88,
        )
    )

    assessment = agent.assess(
        make_report(
            headline="Typhoon closes Shanghai port",
            description="All container terminals are shut until the storm passes.",
            source="Internal alert feed",
        )
    )

    assert assessment.disruption_type is DisruptionCategory.SEVERE_WEATHER
    assert assessment.location == "Shanghai"
    # 14 + 10 + 12 (factors) + 15 (3 shipments) + 5 (1 supplier) = 56
    assert assessment.risk_score == 56
    assert assessment.severity is Severity.MODERATE
    assert sorted(assessment.affected_shipments) == ["SH003", "SH004", "SH010"]
    # The Chinese supplier is exposed through geography, not through a reference.
    assert assessment.affected_suppliers == ["SUP003"]
    assert assessment.reference_contributions["Validated affected suppliers"] == 5


# ---------------------------------------------------------------------------
# 3. Supplier failure
# ---------------------------------------------------------------------------


def test_supplier_failure_exposes_that_suppliers_shipments() -> None:
    agent, _ = build_agent(
        llm_response(
            disruption_type=DisruptionCategory.SUPPLIER_FAILURE.value,
            description="Shenzhen Micro Components has halted production indefinitely.",
            affected_locations=["Shenzhen"],
            risk_factors=[
                RiskFactor.SUPPLIER_OPERATIONS_HALTED.value,
                RiskFactor.ONGOING_OR_UNRESOLVED.value,
                RiskFactor.HIGH_VOLUME_TRADE_LANE.value,
            ],
            potential_impact=["Component supply stops"],
            mentioned_supplier_ids=["SUP003"],
            recommended_next_action="Qualify an alternate supplier for the affected parts.",
            confidence=0.9,
        )
    )

    assessment = agent.assess(
        make_report(
            headline="Key electronics supplier halts production",
            description="The Shenzhen plant has stopped all output.",
            source="Supplier watchlist",
        )
    )

    assert assessment.disruption_type is DisruptionCategory.SUPPLIER_FAILURE
    assert assessment.affected_suppliers == ["SUP003"]
    # Every shipment fulfilled by the failed supplier is exposed.
    assert sorted(assessment.affected_shipments) == ["SH003", "SH004", "SH010"]
    # 20 + 12 + 12 (factors) + 15 (3 shipments) + 5 (1 supplier) = 64
    assert assessment.risk_score == 64
    assert assessment.severity is Severity.HIGH
    assert assessment.unvalidated_supplier_references == []


# ---------------------------------------------------------------------------
# 4. Irrelevant news article
# ---------------------------------------------------------------------------


def test_irrelevant_news_scores_zero_and_claims_no_impact() -> None:
    agent, _ = build_agent(
        llm_response(
            is_supply_chain_disruption=False,
            disruption_type=DisruptionCategory.UNRELATED.value,
            description="A regional sporting event was announced.",
            recommended_next_action="Investigate whether any lane is affected.",
            confidence=0.97,
        )
    )

    assessment = agent.assess(
        make_report(
            headline="City to host international sporting final",
            description="The venue was confirmed this morning.",
            source="General news wire",
        )
    )

    assert assessment.is_supply_chain_disruption is False
    assert assessment.disruption_type is DisruptionCategory.UNRELATED
    assert assessment.risk_score == 0
    assert assessment.severity is Severity.NEGLIGIBLE
    assert assessment.affected_shipments == []
    assert assessment.affected_suppliers == []
    assert assessment.risk_breakdown == {}
    assert assessment.recommended_next_action == NO_DISRUPTION_ACTION
    assert assessment.location == UNKNOWN_LOCATION


def test_irrelevant_news_does_not_contradict_itself_when_type_is_unrelated() -> None:
    agent, _ = build_agent(
        llm_response(
            is_supply_chain_disruption=False,
            disruption_type=DisruptionCategory.UNRELATED.value,
        )
    )
    assessment = agent.assess(make_report())
    assert assessment.contradictions == []


# ---------------------------------------------------------------------------
# 5. Incomplete disruption report
# ---------------------------------------------------------------------------


def test_incomplete_report_lists_what_is_missing_and_stays_low_severity() -> None:
    agent, _ = build_agent(
        llm_response(
            disruption_type=DisruptionCategory.TRANSPORTATION_DELAY.value,
            description="A port is reported to be experiencing problems.",
            risk_factors=[RiskFactor.ONGOING_OR_UNRESOLVED.value],
            recommended_next_action="Obtain the affected port and the expected duration.",
            confidence=0.31,
            missing_information=["Which port is affected", "Expected duration of the delay"],
        )
    )

    assessment = agent.assess(
        make_report(
            headline="Port problems reported",
            description="",
            source="Unverified social media post",
            reported_at=None,
        )
    )

    assert assessment.risk_score == 12
    assert assessment.severity is Severity.LOW
    assert assessment.location == UNKNOWN_LOCATION
    assert assessment.affected_shipments == []
    assert assessment.affected_suppliers == []
    assert assessment.confidence == 0.31
    # The model's two gaps plus three the deterministic layer detected.
    assert "Which port is affected" in assessment.missing_information
    assert any("no timestamp" in gap.lower() for gap in assessment.missing_information)
    assert any("no affected location" in gap.lower() for gap in assessment.missing_information)
    assert any("master data" in gap.lower() for gap in assessment.missing_information)


# ---------------------------------------------------------------------------
# Reference validation and contradictions
# ---------------------------------------------------------------------------


def test_invented_references_are_flagged_and_excluded_from_affected_lists() -> None:
    agent, _ = build_agent(
        llm_response(
            disruption_type=DisruptionCategory.PORT_CONGESTION.value,
            description="Berth congestion at Rotterdam.",
            affected_locations=["Rotterdam"],
            risk_factors=[RiskFactor.PORT_CLOSURE_OR_SEVERE_CONGESTION.value],
            # SH001 is real; SH999 and SUP404 are hallucinated.
            mentioned_shipment_ids=["SH001", "SH999"],
            mentioned_supplier_ids=["SUP404"],
        )
    )

    assessment = agent.assess(make_report(headline="Rotterdam congestion"))

    assert "SH001" in assessment.affected_shipments
    assert "SH999" not in assessment.affected_shipments
    assert assessment.unvalidated_shipment_references == ["SH999"]
    assert assessment.unvalidated_supplier_references == ["SUP404"]
    assert assessment.affected_suppliers == []


def test_all_references_being_unknown_raises_a_contradiction() -> None:
    agent, _ = build_agent(
        llm_response(
            disruption_type=DisruptionCategory.MARITIME_SECURITY_THREAT.value,
            description="Attack in the Gulf of Aden.",
            affected_locations=["Gulf of Aden"],
            risk_factors=[RiskFactor.ACTIVE_PHYSICAL_THREAT.value],
            mentioned_shipment_ids=["SH999"],
            mentioned_supplier_ids=["SUP999"],
        )
    )

    assessment = agent.assess(make_report(headline="Gulf of Aden attack"))

    assert any("shipment id named" in conflict.lower() for conflict in assessment.contradictions)
    assert any("supplier id named" in conflict.lower() for conflict in assessment.contradictions)
    assert assessment.unvalidated_shipment_references == ["SH999"]
    assert assessment.unvalidated_supplier_references == ["SUP999"]


def test_unrelated_report_with_a_disruption_type_is_flagged() -> None:
    agent, _ = build_agent(
        llm_response(
            is_supply_chain_disruption=False,
            disruption_type=DisruptionCategory.SEVERE_WEATHER.value,
        )
    )
    assessment = agent.assess(make_report())
    assert any("marked as unrelated" in conflict.lower() for conflict in assessment.contradictions)


# ---------------------------------------------------------------------------
# Provenance, contract and failure handling
# ---------------------------------------------------------------------------


def test_assessment_always_carries_the_source_report_as_evidence() -> None:
    agent, _ = build_agent(llm_response())
    assessment = agent.assess(
        make_report(headline="Nothing cited by the model", source="Customs bulletin")
    )

    assert assessment.evidence[0].source == "Customs bulletin"
    assert assessment.source == "Customs bulletin"
    assert assessment.reported_at == REPORTED_AT
    assert assessment.assessed_at is not None


def test_event_id_is_derived_deterministically_when_absent() -> None:
    agent, _ = build_agent(llm_response())
    report = make_report(headline="Stable headline", event_id=None)

    first = agent.assess(report)
    second = agent.assess(make_report(headline="Stable headline", event_id=None))

    assert first.event_id == second.event_id
    assert first.event_id.startswith("EV-")


def test_caller_supplied_event_id_is_preserved() -> None:
    agent, _ = build_agent(llm_response())
    assert agent.assess(make_report(event_id="EV001")).event_id == "EV001"


def test_all_eight_disruption_categories_are_offered_to_the_model() -> None:
    assert len(DISRUPTION_CATEGORIES) == 8
    offered = set(LLM_ASSESSMENT_SCHEMA["properties"]["disruption_type"]["enum"])
    for category in DISRUPTION_CATEGORIES:
        assert category.value in offered
        agent, _ = build_agent(llm_response(disruption_type=category.value))
        assert agent.assess(make_report()).disruption_type is category


def test_risk_scoring_is_not_delegated_to_the_model() -> None:
    properties = LLM_ASSESSMENT_SCHEMA["properties"]
    assert "risk_score" not in properties
    assert "severity" not in properties

    agent, stub = build_agent(llm_response())
    agent.assess(make_report(headline="Unmistakable headline text"))
    prompt = stub.calls[0]["prompt"]
    assert "Unmistakable headline text" in prompt
    assert "Do not output a risk score or severity" in stub.calls[0]["system_instruction"]


def test_malformed_model_output_raises_a_clear_error() -> None:
    agent, _ = build_agent({"disruption_type": "Not A Real Category"})
    with pytest.raises(DisruptionSensingError) as excinfo:
        agent.assess(make_report())
    assert "does not match the expected schema" in str(excinfo.value)


def test_missing_api_key_surfaces_as_a_configuration_error() -> None:
    agent, _ = build_agent(GeminiNotConfiguredError("GEMINI_API_KEY is not configured"))
    with pytest.raises(GeminiNotConfiguredError):
        agent.assess(make_report())


# ---------------------------------------------------------------------------
# Opt-in live check against the real Gemini API
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI") != "1",
    reason="Set RUN_LIVE_GEMINI=1 to call the live Gemini API.",
)
def test_live_gemini_maritime_report() -> None:
    """Real Gemini call, real PostgreSQL lookups. Costs one API request."""
    from app.database.session import get_session_factory
    from app.services.supply_chain_repository import PostgresSupplyChainRepository

    with get_session_factory()() as session:
        agent = DisruptionSensingAgent(
            repository=PostgresSupplyChainRepository(session),
        )
        assessment = agent.assess(
            make_report(
                headline="Red Sea shipping attacks intensify",
                description=(
                    "Attacks on commercial vessels in the Red Sea have intensified, "
                    "prompting several container lines to suspend Suez Canal transits "
                    "and route around the Cape of Good Hope."
                ),
                source="Live integration test",
            )
        )

    assert assessment.disruption_type is DisruptionCategory.MARITIME_SECURITY_THREAT
    assert assessment.risk_score > 0
    assert assessment.affected_shipments, "expected Red Sea shipments from PostgreSQL"
