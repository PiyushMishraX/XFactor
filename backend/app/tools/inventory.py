"""Inventory Calculation Engine (Step 2).

Deterministic inventory-position and shortage calculation for one product at
one location. It answers a single auditable question — *is stock short, and by
how much?* — with plain arithmetic. No LLM is involved.

Assumptions
-----------
* ``available_units = on_hand - committed``: committed stock is already promised
  and cannot be used to cover new demand.
* ``projected_available_units = available_units + in_transit``: replenishment
  already on its way counts toward coverage.
* ``required_units = demand_forecast + safety_stock``: the safety stock must be
  preserved, so it is added to the demand that must be met.
* ``shortage_units = max(0, required_units - projected_available_units)`` and
  ``surplus_units = max(0, projected_available_units - required_units)``; the two
  are mutually exclusive and ``is_short`` is simply ``shortage_units > 0``.
* Every input is a non-negative quantity; the engine rejects negatives rather
  than silently absorbing an impossible value.
* Quantities are rounded with :func:`app.tools.base.round_units` (3 dp).
"""

from __future__ import annotations

from typing import Optional

from app.tools.base import EngineResult, require_positive, round_units


class InventoryPosition(EngineResult):
    """Deterministic inventory position for one product/location."""

    on_hand: float
    committed: float
    in_transit: float
    demand_forecast: float
    safety_stock: float
    available_units: float
    projected_available_units: float
    required_units: float
    shortage_units: float
    surplus_units: float
    is_short: bool


def calculate_inventory_shortage(
    *,
    on_hand: float,
    committed: float = 0.0,
    in_transit: float = 0.0,
    demand_forecast: float = 0.0,
    safety_stock: float = 0.0,
    product: Optional[str] = None,
    warehouse: Optional[str] = None,
) -> InventoryPosition:
    """Return the deterministic :class:`InventoryPosition` for one product.

    Args:
        on_hand: Physical stock currently on the shelf (>= 0).
        committed: Stock already promised to other demand (>= 0).
        in_transit: Replenishment expected to arrive (>= 0).
        demand_forecast: Demand the stock must cover (>= 0).
        safety_stock: Buffer that must be preserved (>= 0).
        product: Optional label recorded in the assumptions for traceability.
        warehouse: Optional label recorded in the assumptions for traceability.

    Raises:
        ToolInputError: Any quantity is negative or non-numeric.
    """
    on_hand_units = require_positive(on_hand, "on_hand", allow_zero=True)
    committed_units = require_positive(committed, "committed", allow_zero=True)
    in_transit_units = require_positive(in_transit, "in_transit", allow_zero=True)
    demand_units = require_positive(demand_forecast, "demand_forecast", allow_zero=True)
    safety_units = require_positive(safety_stock, "safety_stock", allow_zero=True)

    available = on_hand_units - committed_units
    projected = available + in_transit_units
    required = demand_units + safety_units
    shortage = max(0.0, required - projected)
    surplus = max(0.0, projected - required)

    scope = "inventory position"
    if product or warehouse:
        scope = f"inventory position for {product or 'unspecified product'} at {warehouse or 'unspecified warehouse'}"

    return InventoryPosition(
        on_hand=round_units(on_hand_units),
        committed=round_units(committed_units),
        in_transit=round_units(in_transit_units),
        demand_forecast=round_units(demand_units),
        safety_stock=round_units(safety_units),
        available_units=round_units(available),
        projected_available_units=round_units(projected),
        required_units=round_units(required),
        shortage_units=round_units(shortage),
        surplus_units=round_units(surplus),
        is_short=shortage > 0,
        assumptions=(
            f"Computed the {scope}.",
            "available = on_hand - committed; projected = available + in_transit.",
            "required = demand_forecast + safety_stock.",
            "shortage and surplus are mutually exclusive (max 0).",
        ),
    )
