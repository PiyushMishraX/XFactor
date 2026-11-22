"""Tests for the deterministic risk scoring function.

These assertions pin the weight table, so any future re-tuning of the scoring
model is a deliberate, visible change rather than a silent drift.
"""

from __future__ import annotations

import pytest

from app.schemas.disruption_schemas import RiskFactor, Severity
from app.services.risk_scoring import (
    MAX_AFFECTED_SHIPMENT_POINTS,
    MAX_AFFECTED_SUPPLIER_POINTS,
    MAX_RISK_SCORE,
    RISK_FACTOR_WEIGHTS,
    compute_risk_score,
    exposure_points,
    score_risk_factors,
    severity_for_score,
)

ALL_FACTORS = list(RiskFactor)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, Severity.NEGLIGIBLE),
        (9, Severity.NEGLIGIBLE),
        (10, Severity.LOW),
        (34, Severity.LOW),
        (35, Severity.MODERATE),
        (59, Severity.MODERATE),
        (60, Severity.HIGH),
        (84, Severity.HIGH),
        (85, Severity.CRITICAL),
        (100, Severity.CRITICAL),
    ],
)
def test_severity_bands(score: int, expected: Severity) -> None:
    assert severity_for_score(score) is expected


def test_every_risk_factor_has_a_positive_weight() -> None:
    assert set(RISK_FACTOR_WEIGHTS) == set(RiskFactor)
    assert all(weight > 0 for weight in RISK_FACTOR_WEIGHTS.values())


def test_score_is_the_sum_of_the_observed_factor_weights() -> None:
    factors = [RiskFactor.ACTIVE_PHYSICAL_THREAT, RiskFactor.ROUTE_CLOSURE_OR_DIVERSION]
    result = compute_risk_score(risk_factors=factors)

    assert result.score == 22 + 20
    assert result.severity is Severity.MODERATE
    assert result.breakdown == {
        RiskFactor.ACTIVE_PHYSICAL_THREAT.value: 22,
        RiskFactor.ROUTE_CLOSURE_OR_DIVERSION.value: 20,
    }
    assert result.reference_contributions == {
        "Validated affected shipments": 0,
        "Validated affected suppliers": 0,
    }


def test_duplicate_factors_are_counted_once() -> None:
    factors = [RiskFactor.REPORTED_COST_INCREASE] * 5
    result = compute_risk_score(risk_factors=factors)

    assert result.score == 8
    assert len(result.breakdown) == 1


def test_unknown_factor_contributes_nothing() -> None:
    assert score_risk_factors(["not a real factor"]) == {}
    assert compute_risk_score(risk_factors=["not a real factor"]).score == 0


def test_no_evidence_scores_zero() -> None:
    result = compute_risk_score(risk_factors=[])

    assert result.score == 0
    assert result.severity is Severity.NEGLIGIBLE
    assert result.breakdown == {}


def test_irrelevant_report_scores_zero_even_with_factors_listed() -> None:
    result = compute_risk_score(
        risk_factors=ALL_FACTORS,
        shipment_count=10,
        supplier_count=10,
        is_supply_chain_disruption=False,
    )

    assert result.score == 0
    assert result.severity is Severity.NEGLIGIBLE
    assert result.breakdown == {}
    assert result.reference_contributions == {}


def test_exposure_points_are_capped() -> None:
    contributions = exposure_points(shipment_count=20, supplier_count=20)

    assert contributions["Validated affected shipments"] == MAX_AFFECTED_SHIPMENT_POINTS
    assert contributions["Validated affected suppliers"] == MAX_AFFECTED_SUPPLIER_POINTS


def test_negative_reference_counts_do_not_reduce_the_score() -> None:
    assert exposure_points(shipment_count=-4, supplier_count=-2) == {
        "Validated affected shipments": 0,
        "Validated affected suppliers": 0,
    }


def test_score_is_capped_at_one_hundred() -> None:
    result = compute_risk_score(
        risk_factors=ALL_FACTORS,
        shipment_count=10,
        supplier_count=10,
    )

    assert result.score == MAX_RISK_SCORE
    assert result.severity is Severity.CRITICAL
    # The breakdown still exposes the untruncated arithmetic.
    assert sum(result.breakdown.values()) > MAX_RISK_SCORE


def test_scoring_is_repeatable() -> None:
    factors = ALL_FACTORS[:4]
    first = compute_risk_score(risk_factors=factors, shipment_count=2, supplier_count=1)
    second = compute_risk_score(risk_factors=factors, shipment_count=2, supplier_count=1)

    assert first == second
