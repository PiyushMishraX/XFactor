"""Cost Calculation Engine (Step 2).

Deterministic freight-cost estimation from distance, transport mode, cargo value
and optional tariff / fuel inputs. No LLM is involved and no arithmetic happens
inside any prompt.

Assumptions
-----------
* Indicative planning rates per container-equivalent, per km, by mode
  (:data:`MODE_FREIGHT_RATE_PER_KM_USD`). These are planning estimates for the
  hackathon dataset, not negotiated carrier rates.
* Fuel surcharge is a proportional uplift on the base freight driven by the fuel
  price index: ``index 1.0`` adds nothing, ``index 1.2`` adds 20%.
* Handling is a flat fee per container-equivalent, by mode.
* Insurance is a fixed percentage of declared cargo value.
* Duties use the caller's ad-valorem tariff rate applied to cargo value.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from app.tools.base import (
    EngineResult,
    require_choice,
    require_positive,
    round_money,
)

#: Base freight rate per container-equivalent per km, by mode (USD).
MODE_FREIGHT_RATE_PER_KM_USD: dict[str, float] = {
    "Sea": 0.33,
    "Rail": 0.80,
    "Road": 1.60,
    "Air": 9.00,
}

#: Flat handling fee per container-equivalent, by mode (USD).
MODE_HANDLING_USD: dict[str, float] = {
    "Sea": 180.0,
    "Rail": 220.0,
    "Road": 120.0,
    "Air": 450.0,
}

#: Cargo insurance as a fraction of declared value.
INSURANCE_RATE = 0.005

DEFAULT_FUEL_PRICE_INDEX = 1.0


class TransportMode(str, Enum):
    """Supported transport modes."""

    SEA = "Sea"
    RAIL = "Rail"
    ROAD = "Road"
    AIR = "Air"


class CostBreakdown(EngineResult):
    """Itemised cost estimate for one movement."""

    transport_mode: TransportMode
    distance_km: float
    container_count: float
    cargo_value_usd: float
    freight_usd: float
    fuel_surcharge_usd: float
    handling_usd: float
    insurance_usd: float
    duty_usd: float = Field(description="Ad-valorem duty on declared cargo value.")
    total_usd: float


def calculate_route_cost(
    *,
    distance_km: float,
    transport_mode: str | TransportMode,
    cargo_value_usd: float,
    container_count: float = 1.0,
    fuel_price_index: float = DEFAULT_FUEL_PRICE_INDEX,
    tariff_rate_percent: float = 0.0,
) -> CostBreakdown:
    """Return a deterministic :class:`CostBreakdown` for one movement.

    Args:
        distance_km: Great-circle or route distance in kilometres (> 0).
        transport_mode: One of :class:`TransportMode`.
        cargo_value_usd: Declared cargo value, used for insurance and duty.
        container_count: Container-equivalents moved (> 0).
        fuel_price_index: Multiplier where 1.0 means "no surcharge".
        tariff_rate_percent: Ad-valorem duty rate, e.g. ``7.5`` for 7.5%.

    Raises:
        ToolInputError: Any argument is missing, non-numeric or out of range.
    """
    distance = require_positive(distance_km, "distance_km")
    containers = require_positive(container_count, "container_count")
    cargo_value = require_positive(cargo_value_usd, "cargo_value_usd", allow_zero=True)
    fuel_index = require_positive(fuel_price_index, "fuel_price_index", allow_zero=True)
    tariff_percent = require_positive(tariff_rate_percent, "tariff_rate_percent", allow_zero=True)
    mode_name = require_choice(transport_mode, [m.value for m in TransportMode], "transport_mode")
    mode = TransportMode(mode_name)

    freight = round_money(distance * containers * MODE_FREIGHT_RATE_PER_KM_USD[mode.value])
    fuel_surcharge = round_money(freight * max(0.0, fuel_index - 1.0))
    handling = round_money(MODE_HANDLING_USD[mode.value] * containers)
    insurance = round_money(cargo_value * INSURANCE_RATE)
    duty = round_money(cargo_value * (tariff_percent / 100.0))
    total = round_money(freight + fuel_surcharge + handling + insurance + duty)

    return CostBreakdown(
        transport_mode=mode,
        distance_km=round(distance, 3),
        container_count=round(containers, 3),
        cargo_value_usd=round_money(cargo_value),
        freight_usd=freight,
        fuel_surcharge_usd=fuel_surcharge,
        handling_usd=handling,
        insurance_usd=insurance,
        duty_usd=duty,
        total_usd=total,
        assumptions=(
            f"Freight uses the indicative {mode.value.lower()} planning rate "
            f"{MODE_FREIGHT_RATE_PER_KM_USD[mode.value]} USD per container-km.",
            f"Fuel surcharge is {round(max(0.0, fuel_index - 1.0) * 100, 2)}% of base freight "
            f"(index {fuel_index}).",
            f"Insurance is {INSURANCE_RATE * 100:.1f}% of declared cargo value.",
            f"Duty uses an ad-valorem rate of {tariff_percent}%.",
        ),
    )
