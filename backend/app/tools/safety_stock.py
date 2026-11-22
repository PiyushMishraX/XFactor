"""Safety Stock Calculation Engine (Step 2).

Standard inventory-theory safety stock, computed deterministically. No LLM is
involved.

Assumptions
-----------
* Demand and lead time are treated as independent normal variables, so the
  combined standard deviation is
  ``sqrt(lead_time * demand_sd^2 + demand^2 * lead_time_sd^2)``.
* Safety stock is ``z * combined_sd`` and the reorder point is
  ``average_daily_demand * lead_time + safety_stock``.
* Results are rounded **up** to whole units: holding a fraction of a unit is not
  physically meaningful.
* The service factor ``z`` is supplied by the caller, or looked up from the
  common service levels in :data:`SERVICE_LEVEL_Z`.
"""

from __future__ import annotations

import math
from decimal import Decimal

from pydantic import Field

from app.tools.base import EngineResult, ToolInputError, require_number, require_positive

#: Service factor (z) for common target service levels, in percent.
SERVICE_LEVEL_Z: dict[int, float] = {
    90: 1.28,
    95: 1.65,
    97: 1.88,
    98: 2.05,
    99: 2.33,
    99.9: 3.09,
}

DEFAULT_SERVICE_LEVEL_PERCENT = 95


def service_factor_for(service_level_percent: int | float) -> float:
    """Return the z factor for a service level, using the nearest tabulated value."""
    target = require_positive(service_level_percent, "service_level_percent")
    if target in SERVICE_LEVEL_Z:
        return SERVICE_LEVEL_Z[int(target)]
    nearest = min(SERVICE_LEVEL_Z, key=lambda level: abs(level - target))
    return SERVICE_LEVEL_Z[nearest]


class SafetyStockResult(EngineResult):
    """Recommended safety stock and reorder point for one material."""

    average_daily_demand: float
    demand_std_dev: float
    lead_time_days: float
    lead_time_std_dev: float
    service_level_z: float
    combined_demand_variability: float = Field(
        description="Standard deviation of demand over the lead time."
    )
    safety_stock_units: int
    reorder_point_units: int


def calculate_safety_stock(
    *,
    average_daily_demand: float | Decimal,
    lead_time_days: float | Decimal,
    demand_std_dev: float | Decimal = 0.0,
    lead_time_std_dev: float | Decimal = 0.0,
    service_level_z: float | Decimal | None = None,
    service_level_percent: int | float = DEFAULT_SERVICE_LEVEL_PERCENT,
) -> SafetyStockResult:
    """Calculate safety stock and the reorder point for one material.

    Args:
        average_daily_demand: Mean demand per day (>= 0).
        lead_time_days: Mean replenishment lead time in days (> 0).
        demand_std_dev: Standard deviation of daily demand (>= 0).
        lead_time_std_dev: Standard deviation of lead time in days (>= 0).
        service_level_z: Explicit service factor. When omitted,
            ``service_level_percent`` is used instead.
        service_level_percent: Target service level used to look up ``z``.

    Raises:
        ToolInputError: Any argument is negative, non-numeric, or the lead time
            is zero.
    """
    demand = require_positive(average_daily_demand, "average_daily_demand", allow_zero=True)
    lead_time = require_positive(lead_time_days, "lead_time_days")
    demand_sd = require_positive(demand_std_dev, "demand_std_dev", allow_zero=True)
    lead_time_sd = require_positive(lead_time_std_dev, "lead_time_std_dev", allow_zero=True)

    if service_level_z is None:
        z = service_factor_for(service_level_percent)
        z_source = f"service level {service_level_percent}% (table lookup)"
    else:
        z = require_number(service_level_z, "service_level_z")
        if z <= 0:
            raise ToolInputError(f"service_level_z must be > 0, got {z}.")
        z_source = f"caller-supplied z = {round(z, 4)}"

    combined_variability = math.sqrt(
        (lead_time * (demand_sd**2)) + ((demand**2) * (lead_time_sd**2))
    )
    safety_stock = math.ceil(z * combined_variability)
    reorder_point = math.ceil((demand * lead_time) + safety_stock)

    return SafetyStockResult(
        average_daily_demand=round(demand, 3),
        demand_std_dev=round(demand_sd, 3),
        lead_time_days=round(lead_time, 3),
        lead_time_std_dev=round(lead_time_sd, 3),
        service_level_z=round(z, 4),
        combined_demand_variability=round(combined_variability, 3),
        safety_stock_units=safety_stock,
        reorder_point_units=reorder_point,
        assumptions=(
            "Demand and lead time are independent normal variables.",
            f"Service factor z = {round(z, 4)} taken from {z_source}.",
            "Safety stock and reorder point are rounded up to whole units.",
        ),
    )
