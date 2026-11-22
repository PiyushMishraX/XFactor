"""Deterministic risk scoring for disruption assessments (Step 1).

This module contains **no LLM calls and no prompt text**. Gemini is only allowed
to report which :class:`RiskFactor` signals it observed; every number below is
plain arithmetic over a fixed weight table, so the same evidence always produces
the same score.

Step 2 will extend this into the full Risk Scoring Engine; the public functions
here are already stateless and independently reusable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Sequence

from app.schemas.disruption_schemas import RiskFactor, Severity

# ---------------------------------------------------------------------------
# Weights and thresholds — the single source of truth for scoring
# ---------------------------------------------------------------------------

#: Points contributed by each observed risk signal.
RISK_FACTOR_WEIGHTS: Dict[RiskFactor, int] = {
    RiskFactor.ACTIVE_PHYSICAL_THREAT: 22,
    RiskFactor.ROUTE_CLOSURE_OR_DIVERSION: 20,
    RiskFactor.SUPPLIER_OPERATIONS_HALTED: 20,
    RiskFactor.CONFIRMED_DAMAGE_OR_LOSS: 16,
    RiskFactor.INFRASTRUCTURE_OUTAGE: 16,
    RiskFactor.CARRIER_SERVICE_SUSPENSION: 14,
    RiskFactor.PORT_CLOSURE_OR_SEVERE_CONGESTION: 14,
    RiskFactor.GOVERNMENT_RESTRICTION: 12,
    RiskFactor.HIGH_VOLUME_TRADE_LANE: 12,
    RiskFactor.ONGOING_OR_UNRESOLVED: 12,
    RiskFactor.REPORTED_SCHEDULE_DELAY: 10,
    RiskFactor.REPORTED_COST_INCREASE: 8,
}

#: Exposure bonus for shipments confirmed to exist in PostgreSQL.
POINTS_PER_AFFECTED_SHIPMENT = 5
MAX_AFFECTED_SHIPMENT_POINTS = 15

#: Exposure bonus for suppliers confirmed to exist in PostgreSQL.
POINTS_PER_AFFECTED_SUPPLIER = 5
MAX_AFFECTED_SUPPLIER_POINTS = 10

#: Severity bands, highest threshold first.
_SEVERITY_BANDS: Sequence[tuple[int, Severity]] = (
    (85, Severity.CRITICAL),
    (60, Severity.HIGH),
    (35, Severity.MODERATE),
    (10, Severity.LOW),
    (0, Severity.NEGLIGIBLE),
)

MAX_RISK_SCORE = 100


@dataclass(frozen=True)
class RiskScore:
    """Deterministic scoring result, including the arithmetic behind it."""

    score: int
    severity: Severity
    breakdown: Dict[str, int] = field(default_factory=dict)
    reference_contributions: Dict[str, int] = field(default_factory=dict)


def severity_for_score(score: int) -> Severity:
    """Map a 0-100 risk score onto a severity band."""
    for threshold, severity in _SEVERITY_BANDS:
        if score >= threshold:
            return severity
    return Severity.NEGLIGIBLE


def score_risk_factors(risk_factors: Iterable[RiskFactor]) -> Dict[str, int]:
    """Sum the weight of each distinct observed factor, keyed by factor label.

    Unknown factors contribute nothing, and duplicates are counted once.
    """
    breakdown: Dict[str, int] = {}
    for factor in risk_factors:
        weight = RISK_FACTOR_WEIGHTS.get(factor, 0)
        if weight:
            breakdown[factor.value] = weight
    return breakdown


def exposure_points(*, shipment_count: int, supplier_count: int) -> Dict[str, int]:
    """Exposure bonus for references that were validated against PostgreSQL."""
    shipments = min(max(shipment_count, 0) * POINTS_PER_AFFECTED_SHIPMENT, MAX_AFFECTED_SHIPMENT_POINTS)
    suppliers = min(max(supplier_count, 0) * POINTS_PER_AFFECTED_SUPPLIER, MAX_AFFECTED_SUPPLIER_POINTS)
    return {
        "Validated affected shipments": shipments,
        "Validated affected suppliers": suppliers,
    }


def compute_risk_score(
    *,
    risk_factors: Iterable[RiskFactor],
    shipment_count: int = 0,
    supplier_count: int = 0,
    is_supply_chain_disruption: bool = True,
) -> RiskScore:
    """Compute the deterministic risk score and severity for an assessment.

    Args:
        risk_factors: Signals observed by the LLM in the source report.
        shipment_count: Shipments confirmed to exist in PostgreSQL.
        supplier_count: Suppliers confirmed to exist in PostgreSQL.
        is_supply_chain_disruption: When False the report is irrelevant and
            scores zero regardless of any factors listed.

    Returns:
        A :class:`RiskScore` whose components add up to ``score`` before the
        cap at :data:`MAX_RISK_SCORE`.
    """
    if not is_supply_chain_disruption:
        return RiskScore(score=0, severity=Severity.NEGLIGIBLE)

    breakdown = score_risk_factors(risk_factors)
    contributions = exposure_points(shipment_count=shipment_count, supplier_count=supplier_count)
    total = min(sum(breakdown.values()) + sum(contributions.values()), MAX_RISK_SCORE)

    return RiskScore(
        score=total,
        severity=severity_for_score(total),
        breakdown=breakdown,
        reference_contributions=contributions,
    )
