"""Tests for the Budget Validation Engine (``app.tools.budget``)."""

from __future__ import annotations

import math

import pytest

from app.tools.base import ToolInputError
from app.tools.budget import validate_budget


def test_proposal_within_budget() -> None:
    result = validate_budget(proposed_cost_usd=5000.0, available_budget_usd=10000.0)

    assert result.is_within_budget is True
    assert result.remaining_budget_usd == 5000.0  # 10000 - 5000
    assert result.overage_usd == 0.0
    assert result.utilisation_percent == 50.0  # 5000 / 10000 * 100


def test_proposal_over_budget() -> None:
    result = validate_budget(proposed_cost_usd=12000.0, available_budget_usd=10000.0)

    assert result.is_within_budget is False
    assert result.remaining_budget_usd == -2000.0  # 10000 - 12000
    assert result.overage_usd == 2000.0  # 12000 - 10000
    assert result.utilisation_percent == 120.0  # 12000 / 10000 * 100


def test_spend_exactly_equal_to_budget_is_within_budget() -> None:
    result = validate_budget(proposed_cost_usd=10000.0, available_budget_usd=10000.0)

    assert result.is_within_budget is True
    assert result.overage_usd == 0.0
    assert result.utilisation_percent == 100.0


def test_zero_cost_with_zero_budget_reports_zero_utilisation() -> None:
    result = validate_budget(proposed_cost_usd=0.0, available_budget_usd=0.0)

    assert result.is_within_budget is True
    assert result.remaining_budget_usd == 0.0
    assert result.overage_usd == 0.0
    assert result.utilisation_percent == 0.0


def test_zero_budget_with_positive_proposal_is_infinite_utilisation() -> None:
    result = validate_budget(proposed_cost_usd=100.0, available_budget_usd=0.0)

    assert result.is_within_budget is False
    assert result.overage_usd == 100.0
    assert math.isinf(result.utilisation_percent)
    assert result.utilisation_percent > 100


def test_negative_amounts_are_rejected() -> None:
    with pytest.raises(ToolInputError):
        validate_budget(proposed_cost_usd=-1.0, available_budget_usd=100.0)
    with pytest.raises(ToolInputError):
        validate_budget(proposed_cost_usd=1.0, available_budget_usd=-100.0)


def test_budget_validation_is_repeatable() -> None:
    first = validate_budget(proposed_cost_usd=1234.56, available_budget_usd=2000.0)
    second = validate_budget(proposed_cost_usd=1234.56, available_budget_usd=2000.0)

    assert first == second
    assert first.utilisation_percent == round(1234.56 / 2000.0 * 100, 2)  # 61.73
