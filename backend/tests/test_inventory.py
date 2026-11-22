"""Tests for the Inventory Calculation Engine (``app.tools.inventory``)."""

from __future__ import annotations

import pytest

from app.tools.base import ToolInputError
from app.tools.inventory import calculate_inventory_shortage


def test_shortage_is_required_minus_projected() -> None:
    result = calculate_inventory_shortage(
        on_hand=100,
        committed=20,
        in_transit=10,
        demand_forecast=120,
        safety_stock=30,
    )

    assert result.available_units == 80.0  # 100 - 20
    assert result.projected_available_units == 90.0  # 80 + 10
    assert result.required_units == 150.0  # 120 + 30
    assert result.shortage_units == 60.0  # 150 - 90
    assert result.surplus_units == 0.0
    assert result.is_short is True


def test_surplus_when_stock_is_ample() -> None:
    result = calculate_inventory_shortage(on_hand=200, demand_forecast=100, safety_stock=20)

    assert result.available_units == 200.0
    assert result.projected_available_units == 200.0
    assert result.required_units == 120.0
    assert result.shortage_units == 0.0
    assert result.surplus_units == 80.0  # 200 - 120
    assert result.is_short is False


def test_committed_stock_reduces_available_and_can_cause_a_shortage() -> None:
    result = calculate_inventory_shortage(on_hand=10, committed=30)

    assert result.available_units == -20.0  # 10 - 30
    assert result.projected_available_units == -20.0
    assert result.shortage_units == 20.0  # required 0 - projected -20
    assert result.is_short is True


def test_negative_quantities_are_rejected() -> None:
    with pytest.raises(ToolInputError):
        calculate_inventory_shortage(on_hand=-1)
    with pytest.raises(ToolInputError):
        calculate_inventory_shortage(on_hand=1, committed=-1)
    with pytest.raises(ToolInputError):
        calculate_inventory_shortage(on_hand=1, demand_forecast=-1)


def test_labels_are_recorded_without_changing_the_maths() -> None:
    labelled = calculate_inventory_shortage(on_hand=50, demand_forecast=10, product="Widget", warehouse="WH-1")
    plain = calculate_inventory_shortage(on_hand=50, demand_forecast=10)

    assert labelled.shortage_units == plain.shortage_units == 0.0
    assert any("Widget" in note for note in labelled.assumptions)


def test_inventory_position_is_repeatable() -> None:
    kwargs = dict(on_hand=100, committed=20, in_transit=10, demand_forecast=120, safety_stock=30)
    assert calculate_inventory_shortage(**kwargs) == calculate_inventory_shortage(**kwargs)
