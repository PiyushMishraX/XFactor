"""Tests for the tools-layer risk scoring entry point (``app.tools.risk``).

The point of these tests is that the entry point is a *thin delegate*: it must
return exactly what the Step 1 engine returns, with no drift.
"""

from __future__ import annotations

from app.schemas.disruption_schemas import RiskFactor, Severity
from app.services.risk_scoring import compute_risk_score
from app.tools.risk import RISK_ENGINE_LOCATION, calculate_risk


def test_risk_engine_location_points_at_the_step_one_module() -> None:
    assert RISK_ENGINE_LOCATION == "app.services.risk_scoring"


def test_calculate_risk_matches_compute_risk_score_exactly() -> None:
    factors = [RiskFactor.ACTIVE_PHYSICAL_THREAT, RiskFactor.REPORTED_COST_INCREASE]

    delegated = calculate_risk(risk_factors=factors, shipment_count=2, supplier_count=1)
    direct = compute_risk_score(risk_factors=factors, shipment_count=2, supplier_count=1)

    assert delegated == direct
    # 22 (physical threat) + 8 (cost increase) + 2*5 shipments + 1*5 supplier = 45
    assert delegated.score == 22 + 8 + 2 * 5 + 1 * 5 == 45
    assert delegated.severity is Severity.MODERATE


def test_risk_breakdown_matches_the_step_one_engine() -> None:
    factors = [RiskFactor.REPORTED_COST_INCREASE]
    result = calculate_risk(risk_factors=factors)

    assert result.breakdown == {RiskFactor.REPORTED_COST_INCREASE.value: 8}
    assert result.score == 8


def test_irrelevant_report_scores_zero_through_the_entry_point() -> None:
    result = calculate_risk(
        risk_factors=[RiskFactor.ACTIVE_PHYSICAL_THREAT],
        shipment_count=5,
        supplier_count=5,
        is_supply_chain_disruption=False,
    )

    assert result == compute_risk_score(
        risk_factors=[RiskFactor.ACTIVE_PHYSICAL_THREAT],
        shipment_count=5,
        supplier_count=5,
        is_supply_chain_disruption=False,
    )
    assert result.score == 0
    assert result.severity is Severity.NEGLIGIBLE


def test_calculate_risk_is_repeatable() -> None:
    factors = [RiskFactor.PORT_CLOSURE_OR_SEVERE_CONGESTION, RiskFactor.ONGOING_OR_UNRESOLVED]

    first = calculate_risk(risk_factors=factors, shipment_count=1, supplier_count=1)
    second = calculate_risk(risk_factors=factors, shipment_count=1, supplier_count=1)

    assert first == second
    assert first.score == 14 + 12 + 5 + 5 == 36
