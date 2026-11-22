"""Tests for the Route Optimization Engine (``app.tools.route_optimization``).

Numbers are computed by hand from the documented costing, lead-time and risk
formulas so the assertions pin the real arithmetic, not just the shape.
"""

from __future__ import annotations

import pytest

from app.schemas.disruption_schemas import RiskFactor
from app.tools.base import ToolInputError
from app.tools.route_optimization import RouteOption, rank_routes


def test_cheaper_faster_more_reliable_route_wins() -> None:
    cheap = RouteOption(
        route_id="A",
        distance_km=1000,
        transport_mode="Road",
        carrier="RoadFast",
        cargo_value_usd=100000,
        carrier_reliability=0.95,
    )
    expensive = RouteOption(
        route_id="B",
        distance_km=2000,
        transport_mode="Road",
        carrier="RoadSlow",
        cargo_value_usd=100000,
        container_count=2.0,
        carrier_reliability=0.80,
        risk_factors=(RiskFactor.ACTIVE_PHYSICAL_THREAT.value,),
    )

    ranking = rank_routes(options=[cheap, expensive])

    assert ranking.recommended_route_id == "A"
    assert [score.route_id for score in ranking.ranked] == ["A", "B"]

    top = ranking.ranked[0]
    assert top.rank == 1
    # Cost: 1000 km * 1 container * 1.60 + handling 120 + insurance (100000 * 0.005)
    assert top.total_cost_usd == round_money_reference(1000 * 1.0 * 1.60 + 120.0 + 500.0) == 2220.00
    # Days: 1000 / 900 + 0.5 handling
    assert top.total_days == round(1000 / 900 + 0.5, 3)  # 1.611
    assert top.risk_score == 0
    # Every criterion is a decisive win, so A scores 1.0 on all of them.
    assert top.criteria == {"cost": 1.0, "time": 1.0, "risk": 1.0, "reliability": 1.0}
    assert top.weighted_score == 1.0

    last = ranking.ranked[1]
    assert last.rank == 2
    assert last.total_cost_usd == round_money_reference(2000 * 2.0 * 1.60 + 240.0 + 500.0) == 7140.00
    assert last.risk_score == 22  # ACTIVE_PHYSICAL_THREAT weight
    assert last.weighted_score == 0.0


def test_single_option_ties_on_every_criterion_and_scores_one() -> None:
    ranking = rank_routes(
        options=[
            RouteOption(
                route_id="Solo",
                distance_km=500,
                transport_mode="Air",
                carrier="AirCo",
                cargo_value_usd=5000,
            )
        ]
    )

    solo = ranking.ranked[0]
    assert solo.criteria == {"cost": 1.0, "time": 1.0, "risk": 1.0, "reliability": 1.0}
    assert solo.weighted_score == 1.0
    assert solo.rank == 1


def test_ties_break_on_lower_cost_then_route_id() -> None:
    # These two options tie on the weighted score (0.50 each); the cheaper one
    # must rank first.
    road = RouteOption(
        route_id="ROAD",
        distance_km=1000,
        transport_mode="Road",
        carrier="X",
        cargo_value_usd=100000,
        carrier_reliability=0.90,
    )
    rail = RouteOption(
        route_id="RAIL",
        distance_km=1000,
        transport_mode="Rail",
        carrier="Y",
        cargo_value_usd=100000,
        carrier_reliability=0.95,
        risk_factors=(RiskFactor.REPORTED_COST_INCREASE.value,),
    )

    ranking = rank_routes(options=[road, rail])

    assert ranking.ranked[0].weighted_score == ranking.ranked[1].weighted_score == 0.5
    # road cost = 1600 + 120 + 500 = 2220; rail cost = 800 + 220 + 500 = 1520 -> rail is cheaper.
    assert ranking.ranked[0].total_cost_usd == 1520.00
    assert [score.route_id for score in ranking.ranked] == ["RAIL", "ROAD"]
    assert ranking.recommended_route_id == "RAIL"


def test_empty_option_list_is_valid() -> None:
    ranking = rank_routes(options=[])

    assert ranking.ranked == []
    assert ranking.recommended_route_id is None
    assert ranking.criteria_weights["cost"] == pytest.approx(0.40)


def test_duplicate_route_ids_are_rejected() -> None:
    first = RouteOption(
        route_id="DUP", distance_km=100, transport_mode="Road", carrier="A", cargo_value_usd=1
    )
    second = RouteOption(
        route_id="DUP", distance_km=200, transport_mode="Road", carrier="B", cargo_value_usd=1
    )

    with pytest.raises(ToolInputError):
        rank_routes(options=[first, second])


def test_invalid_option_raises_tool_input_error() -> None:
    bad = RouteOption(
        route_id="BAD",
        distance_km=0,  # distance must be > 0
        transport_mode="Road",
        carrier="A",
        cargo_value_usd=1,
    )

    with pytest.raises(ToolInputError):
        rank_routes(options=[bad])


def test_custom_weights_are_normalised() -> None:
    ranking = rank_routes(
        options=[
            RouteOption(
                route_id="Solo",
                distance_km=100,
                transport_mode="Road",
                carrier="A",
                cargo_value_usd=1,
            )
        ],
        weights={"cost": 2.0, "time": 1.0, "risk": 1.0, "reliability": 0.0},
    )

    assert sum(ranking.criteria_weights.values()) == pytest.approx(1.0)
    assert ranking.criteria_weights["cost"] == pytest.approx(2.0 / 4.0)  # 0.5


def test_ranking_is_repeatable() -> None:
    options = [
        RouteOption(
            route_id="A", distance_km=1000, transport_mode="Road", carrier="A", cargo_value_usd=1000
        ),
        RouteOption(
            route_id="B", distance_km=1000, transport_mode="Rail", carrier="B", cargo_value_usd=1000
        ),
    ]

    assert rank_routes(options=options) == rank_routes(options=options)


def round_money_reference(value: float) -> float:
    """Local mirror of the engine's money rounding, for expected values."""
    return round(float(value), 2)
