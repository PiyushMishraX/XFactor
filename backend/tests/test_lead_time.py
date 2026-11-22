"""Tests for the Lead-Time Estimation Engine (``app.tools.lead_time``)."""

from __future__ import annotations

import pytest

from app.tools.base import ToolInputError
from app.tools.costing import TransportMode
from app.tools.lead_time import (
    MODE_EFFECTIVE_SPEED_KM_PER_DAY,
    MODE_HANDLING_DAYS,
    calculate_delivery_time,
)


def test_mode_tables_cover_the_costing_modes() -> None:
    expected = {mode.value for mode in TransportMode}
    assert set(MODE_EFFECTIVE_SPEED_KM_PER_DAY) == expected
    assert set(MODE_HANDLING_DAYS) == expected


def test_sea_transit_is_distance_divided_by_speed() -> None:
    result = calculate_delivery_time(distance_km=11000, transport_mode="Sea")

    assert result.transit_days == round(11000 / 700, 3)  # 15.714 days
    assert result.handling_days == MODE_HANDLING_DAYS["Sea"] == 2.0
    assert result.delay_days == 0.0
    # total = transit + handling = 15.714285... + 2
    assert result.total_days == round(11000 / 700 + 2.0, 3)  # 17.714
    assert result.adjusted_total_days == result.total_days
    assert result.transport_mode == "Sea"
    assert result.distance_km == 11000.0


def test_delays_and_reliability_buffer_are_added() -> None:
    result = calculate_delivery_time(
        distance_km=900,
        transport_mode="Road",
        congestion_days=1.0,
        weather_delay_days=0.5,
        reliability_buffer_days=2.0,
    )

    assert result.transit_days == round(900 / 900, 3) == 1.0
    assert result.handling_days == 0.5
    # delay = congestion + weather = 1.5
    assert result.delay_days == 1.5
    # total = 1.0 + 0.5 + 1.0 + 0.5 = 3.0
    assert result.total_days == 3.0
    # adjusted = total + buffer = 3.0 + 2.0 = 5.0
    assert result.adjusted_total_days == 5.0


def test_explicit_handling_overrides_the_mode_default() -> None:
    result = calculate_delivery_time(distance_km=8000, transport_mode="Air", handling_days=5.0)

    assert result.transit_days == round(8000 / 8000, 3) == 1.0
    assert result.handling_days == 5.0  # not the Air default of 1.0
    assert result.total_days == 6.0


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ToolInputError):
        calculate_delivery_time(distance_km=100, transport_mode="Teleport")


def test_zero_or_negative_distance_is_rejected() -> None:
    with pytest.raises(ToolInputError):
        calculate_delivery_time(distance_km=0, transport_mode="Sea")
    with pytest.raises(ToolInputError):
        calculate_delivery_time(distance_km=-10, transport_mode="Sea")


def test_negative_delays_are_rejected() -> None:
    with pytest.raises(ToolInputError):
        calculate_delivery_time(distance_km=100, transport_mode="Sea", congestion_days=-1.0)
    with pytest.raises(ToolInputError):
        calculate_delivery_time(distance_km=100, transport_mode="Sea", weather_delay_days=-1.0)
    with pytest.raises(ToolInputError):
        calculate_delivery_time(distance_km=100, transport_mode="Sea", reliability_buffer_days=-1.0)


def test_estimate_is_repeatable() -> None:
    first = calculate_delivery_time(distance_km=2500, transport_mode="Rail", congestion_days=0.5)
    second = calculate_delivery_time(distance_km=2500, transport_mode="Rail", congestion_days=0.5)

    assert first == second
