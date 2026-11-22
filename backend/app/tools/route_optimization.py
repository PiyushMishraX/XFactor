"""Route Optimization Engine (Step 2).

Compares a caller-supplied set of concrete route options and ranks them against
a transparent, weighted scorecard. The engine **only ever compares the options
it is given** — it never invents, infers or recommends a route that the caller
did not supply. No LLM is involved.

Assumptions
-----------
* Each option's cost comes from :func:`app.tools.costing.calculate_route_cost`,
  its transit time from :func:`app.tools.lead_time.calculate_delivery_time`
  (using the option's own congestion/weather delays), and its risk from
  :func:`app.services.risk_scoring.compute_risk_score` (using the option's own
  ``risk_factors`` and validated shipment/supplier counts). The engine reuses
  those engines rather than re-deriving anything.
* ``RouteOption.risk_factors`` is a tuple of raw factor *value strings* (per the
  schema); they are mapped to :class:`~app.schemas.disruption_schemas.RiskFactor`
  members before scoring, because the Step 1 engine needs the enum. Entries that
  are not recognised factor values are ignored, matching the risk engine's own
  "unknown factor contributes nothing" behaviour.
* The ``time`` criterion uses the raw ``total_days`` from the lead-time engine;
  any reliability contingency belongs to the separate ``reliability`` criterion.
* Criteria are normalised across the supplied option set so that *higher is
  always better*: cost, time and risk are lower-is-better; carrier reliability
  is higher-is-better. When every option ties on a criterion, the helper returns
  ``1.0`` for all of them (see :mod:`app.tools.base`).
* Criterion weights are normalised to sum to 1.0 before scoring
  (:data:`DEFAULT_CRITERIA_WEIGHTS` is used when the caller supplies none).
* Ranking is fully deterministic: descending ``weighted_score``, then lower
  ``total_cost_usd``, then ascending ``route_id``. Ranks start at 1.
* An empty option list is a valid input and yields an empty ranking.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from app.schemas.disruption_schemas import RiskFactor
from app.services.risk_scoring import compute_risk_score
from app.tools.base import (
    EngineResult,
    ToolInputError,
    normalise_higher_is_better,
    normalise_lower_is_better,
    normalise_weights,
    require_non_empty,
    round_money,
    round_units,
    weighted_total,
)
from app.tools.costing import calculate_route_cost
from app.tools.lead_time import calculate_delivery_time

#: Default scorecard weights. Must sum to 1.0 (they are re-normalised anyway).
DEFAULT_CRITERIA_WEIGHTS: dict[str, float] = {
    "cost": 0.40,
    "time": 0.30,
    "risk": 0.20,
    "reliability": 0.10,
}


class RouteOption(BaseModel):
    """One concrete route the caller wants scored. Nothing here is inferred."""

    route_id: str
    distance_km: float
    transport_mode: str
    carrier: str
    cargo_value_usd: float
    container_count: float = 1.0
    tariff_rate_percent: float = 0.0
    congestion_days: float = 0.0
    weather_delay_days: float = 0.0
    carrier_reliability: float = 1.0
    risk_factors: tuple[str, ...] = ()
    shipment_count: int = 0
    supplier_count: int = 0


class RouteScore(BaseModel):
    """The scored, ranked view of one :class:`RouteOption`."""

    route_id: str
    total_cost_usd: float
    total_days: float
    risk_score: int
    carrier_reliability: float
    criteria: dict[str, float] = Field(
        description="Per-criterion 0..1 score where higher is always better."
    )
    weighted_score: float = Field(description="0..1 weighted total, higher is better.")
    rank: int = Field(description="1-based position; 1 is the best route.")


class RouteRanking(EngineResult):
    """Outcome of deterministic route comparison."""

    ranked: list[RouteScore] = Field(default=(), description="Best route first.")
    recommended_route_id: Optional[str] = Field(
        default=None, description="Top route's id, or None when no options were supplied."
    )
    criteria_weights: dict[str, float] = Field(
        description="Normalised weights actually applied to the criteria."
    )


def rank_routes(
    *,
    options: Sequence[RouteOption],
    weights: Optional[Mapping[str, float]] = None,
    fuel_price_index: float = 1.0,
) -> RouteRanking:
    """Score and rank the supplied :class:`RouteOption` objects.

    Args:
        options: The concrete routes to compare. May be empty.
        weights: Criterion weights; defaults to :data:`DEFAULT_CRITERIA_WEIGHTS`.
        fuel_price_index: Passed to the cost engine (1.0 means "no surcharge").

    Returns:
        A :class:`RouteRanking` with the options sorted best-first.

    Raises:
        ToolInputError: Two options share a ``route_id``, or any option has an
            invalid field (raised by the underlying costing/lead-time engines).
    """
    resolved_weights = normalise_weights(weights or DEFAULT_CRITERIA_WEIGHTS)

    seen_ids: set[str] = set()
    for option in options:
        route_id = require_non_empty(option.route_id, "options[].route_id")
        if route_id in seen_ids:
            raise ToolInputError(
                f"Duplicate route_id {route_id!r} supplied; each option must be unique."
            )
        seen_ids.add(route_id)

    # Compute the three underlying quantities for every option up front.
    measurements: list[tuple[RouteOption, float, float, int]] = []
    for option in options:
        cost = calculate_route_cost(
            distance_km=option.distance_km,
            transport_mode=option.transport_mode,
            cargo_value_usd=option.cargo_value_usd,
            container_count=option.container_count,
            fuel_price_index=fuel_price_index,
            tariff_rate_percent=option.tariff_rate_percent,
        )
        lead_time = calculate_delivery_time(
            distance_km=option.distance_km,
            transport_mode=option.transport_mode,
            congestion_days=option.congestion_days,
            weather_delay_days=option.weather_delay_days,
        )
        risk = compute_risk_score(
            risk_factors=_to_risk_factors(option.risk_factors),
            shipment_count=option.shipment_count,
            supplier_count=option.supplier_count,
        )
        measurements.append((option, cost.total_usd, lead_time.total_days, risk.score))

    ranked: list[RouteScore] = []
    if measurements:
        costs = [item[1] for item in measurements]
        days = [item[2] for item in measurements]
        risks = [item[3] for item in measurements]
        reliabilities = [item[0].carrier_reliability for item in measurements]

        min_cost, max_cost = min(costs), max(costs)
        min_days, max_days = min(days), max(days)
        min_risk, max_risk = min(risks), max(risks)
        min_rel, max_rel = min(reliabilities), max(reliabilities)

        # (weighted_score, cost, route_id, RouteScore-with-placeholder-rank)
        draft: list[tuple[float, float, str, RouteScore]] = []
        for option, cost_usd, total_days, risk_score in measurements:
            criteria = {
                "cost": round_units(
                    normalise_lower_is_better(cost_usd, best=min_cost, worst=max_cost)
                ),
                "time": round_units(
                    normalise_lower_is_better(total_days, best=min_days, worst=max_days)
                ),
                "risk": round_units(
                    normalise_lower_is_better(float(risk_score), best=min_risk, worst=max_risk)
                ),
                "reliability": round_units(
                    normalise_higher_is_better(
                        option.carrier_reliability, worst=min_rel, best=max_rel
                    )
                ),
            }
            weighted = round_units(weighted_total(criteria, resolved_weights), 6)
            draft.append(
                (
                    weighted,
                    cost_usd,
                    option.route_id,
                    RouteScore(
                        route_id=option.route_id,
                        total_cost_usd=round_money(cost_usd),
                        total_days=round_units(total_days),
                        risk_score=risk_score,
                        carrier_reliability=round_units(option.carrier_reliability),
                        criteria=criteria,
                        weighted_score=weighted,
                        rank=0,
                    ),
                )
            )

        # Stable, repeatable order: best score, then cheaper, then route_id.
        draft.sort(key=lambda row: (-row[0], row[1], row[2]))
        ranked = [
            score.model_copy(update={"rank": position})
            for position, (_, _, _, score) in enumerate(draft, start=1)
        ]

    return RouteRanking(
        ranked=ranked,
        recommended_route_id=ranked[0].route_id if ranked else None,
        criteria_weights=resolved_weights,
        assumptions=(
            f"{len(ranked)} route option(s) compared; no route was invented.",
            "Costs from app.tools.costing, days from app.tools.lead_time, "
            "risk from app.services.risk_scoring.",
            "Criteria normalised across the supplied set so higher is always better; "
            "ties on a criterion score 1.0 for every option.",
            "Ranked by weighted score, then lower cost, then route_id.",
        ),
    )


#: Reverse lookup from a factor's value string to its :class:`RiskFactor` member.
_RISK_FACTOR_BY_VALUE: dict[str, RiskFactor] = {factor.value: factor for factor in RiskFactor}


def _to_risk_factors(values: Iterable[str]) -> tuple[RiskFactor, ...]:
    """Map raw factor value strings to :class:`RiskFactor` members.

    Unknown entries are dropped, mirroring the risk engine's rule that an
    unrecognised factor contributes no weight.
    """
    factors: list[RiskFactor] = []
    for value in values:
        factor = _RISK_FACTOR_BY_VALUE.get(value)
        if factor is not None:
            factors.append(factor)
    return tuple(factors)
