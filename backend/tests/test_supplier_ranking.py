"""Tests for the Supplier Ranking Engine (``app.tools.supplier_ranking``)."""

from __future__ import annotations

import pytest

from app.tools.base import ToolInputError
from app.tools.supplier_ranking import (
    DEFAULT_CRITERIA_WEIGHTS,
    MAX_LEAD_TIME_DAYS,
    PRICE_INDEX_WORST,
    SupplierScore,
    rank_suppliers,
)


def _supplier(supplier_id: str, **overrides: object) -> SupplierScore:
    data: dict[str, object] = {
        "supplier_id": supplier_id,
        "name": supplier_id,
        "reliability": 0.5,
        "quality_score": 0.5,
        "price_index": 1.0,
        "capacity_utilisation": 0.5,
        "lead_time_days": 30.0,
    }
    data.update(overrides)
    return SupplierScore(**data)  # type: ignore[arg-type]


def test_perfect_supplier_beats_average_supplier() -> None:
    best = _supplier(
        "S1",
        reliability=1.0,
        quality_score=1.0,
        price_index=0.0,
        capacity_utilisation=0.0,
        lead_time_days=0.0,
    )
    average = _supplier("S2")  # all mid-points

    ranking = rank_suppliers(suppliers=[average, best])

    assert [item.supplier_id for item in ranking.ranked] == ["S1", "S2"]

    top = ranking.ranked[0]
    assert top.rank == 1
    assert top.criteria == {
        "reliability": 1.0,
        "quality": 1.0,
        "price": 1.0,
        "capacity": 1.0,
        "lead_time": 1.0,
    }
    assert top.total_score == 1.0

    mid = ranking.ranked[1]
    assert mid.rank == 2
    # reliability 0.5/1, quality 0.5/1, price (2-1)/2, capacity (1-0.5)/1, lead (60-30)/60
    assert mid.criteria == {
        "reliability": 0.5,
        "quality": 0.5,
        "price": 0.5,
        "capacity": 0.5,
        "lead_time": 0.5,
    }
    assert mid.total_score == 0.5  # every criterion 0.5 * weights summing to 1


def test_normalisation_anchors_are_respected() -> None:
    worst = _supplier(
        "WORST",
        reliability=0.0,
        quality_score=0.0,
        price_index=PRICE_INDEX_WORST,
        capacity_utilisation=1.0,
        lead_time_days=MAX_LEAD_TIME_DAYS,
    )

    ranking = rank_suppliers(suppliers=[worst])

    assert ranking.ranked[0].criteria == {
        "reliability": 0.0,
        "quality": 0.0,
        "price": 0.0,
        "capacity": 0.0,
        "lead_time": 0.0,
    }
    assert ranking.ranked[0].total_score == 0.0


def test_default_weights_are_applied() -> None:
    ranking = rank_suppliers(suppliers=[_supplier("S1")])

    assert ranking.criteria_weights["reliability"] == pytest.approx(0.30)
    assert ranking.criteria_weights["price"] == pytest.approx(0.20)
    assert sum(ranking.criteria_weights.values()) == pytest.approx(1.0)
    assert set(ranking.criteria_weights) == set(DEFAULT_CRITERIA_WEIGHTS)


def test_empty_supplier_list_is_valid() -> None:
    ranking = rank_suppliers(suppliers=[])

    assert ranking.ranked == []
    assert ranking.criteria_weights["reliability"] == pytest.approx(0.30)


def test_duplicate_supplier_ids_are_rejected() -> None:
    with pytest.raises(ToolInputError):
        rank_suppliers(suppliers=[_supplier("DUP"), _supplier("DUP", reliability=0.9)])


def test_out_of_range_metrics_are_rejected() -> None:
    with pytest.raises(ToolInputError):
        rank_suppliers(suppliers=[_supplier("BAD", reliability=1.5)])
    with pytest.raises(ToolInputError):
        rank_suppliers(suppliers=[_supplier("BAD", price_index=2.5)])
    with pytest.raises(ToolInputError):
        rank_suppliers(suppliers=[_supplier("BAD", lead_time_days=-1.0)])


def test_custom_weights_are_normalised() -> None:
    ranking = rank_suppliers(
        suppliers=[_supplier("S1")],
        weights={"reliability": 2.0, "quality": 1.0, "price": 1.0, "capacity": 0.0, "lead_time": 0.0},
    )

    assert sum(ranking.criteria_weights.values()) == pytest.approx(1.0)
    assert ranking.criteria_weights["reliability"] == pytest.approx(0.5)


def test_ranking_is_repeatable() -> None:
    suppliers = [_supplier("S1", reliability=0.3), _supplier("S2", reliability=0.7)]
    assert rank_suppliers(suppliers=suppliers) == rank_suppliers(suppliers=suppliers)
