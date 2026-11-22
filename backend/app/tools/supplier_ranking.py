"""Supplier Ranking Engine (Step 2).

Ranks a caller-supplied set of suppliers against a configurable, weighted
scorecard. Every supplier's raw metrics are normalised so that *higher always
means better* before the weights are applied. No LLM is involved.

Assumptions
-----------
* The five criteria and their default weights are
  :data:`DEFAULT_CRITERIA_WEIGHTS`; caller-supplied weights are re-normalised to
  sum to 1.0 first.
* Normalisation uses fixed anchors, so a score is comparable across runs:
  - ``reliability`` — higher-is-better, worst ``0.0`` / best ``1.0``.
  - ``quality`` — higher-is-better, worst ``0.0`` / best ``1.0``.
  - ``price`` — lower-is-better, best ``0.0`` / worst :data:`PRICE_INDEX_WORST`
    (a price index of 2.0 means "twice the reference price").
  - ``capacity`` (from ``capacity_utilisation``) — lower-is-better, best ``0.0``
    / worst ``1.0``: slack capacity is preferred over a fully loaded supplier.
  - ``lead_time`` — lower-is-better, best ``0`` days / worst
    :data:`MAX_LEAD_TIME_DAYS`.
* ``total_score = sum(criterion_score * weight)``, in ``0..1``.
* Ranking is deterministic: descending ``total_score``, then ascending
  ``supplier_id``. An empty input list is valid and yields an empty ranking.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from app.tools.base import (
    EngineResult,
    ToolInputError,
    normalise_higher_is_better,
    normalise_lower_is_better,
    normalise_weights,
    require_non_empty,
    require_number,
    require_positive,
    round_units,
    weighted_total,
)

#: Default scorecard weights across the five criteria.
DEFAULT_CRITERIA_WEIGHTS: dict[str, float] = {
    "reliability": 0.30,
    "quality": 0.20,
    "price": 0.20,
    "capacity": 0.15,
    "lead_time": 0.15,
}

#: Worst-case lead time (days) used as the normalisation anchor.
MAX_LEAD_TIME_DAYS = 60.0

#: Worst-case price index used as the normalisation anchor (2.0 = twice reference).
PRICE_INDEX_WORST = 2.0


class SupplierScore(BaseModel):
    """Raw, caller-supplied metrics for one supplier (all un-normalised)."""

    supplier_id: str
    name: str = ""
    reliability: float = Field(description="0..1, higher is better.")
    quality_score: float = Field(description="0..1, higher is better.")
    price_index: float = Field(description="0..2, lower is better; 2.0 = 2x reference.")
    capacity_utilisation: float = Field(description="0..1, lower is better (more slack).")
    lead_time_days: float = Field(description="Average lead time in days, lower is better.")


class RankedSupplier(BaseModel):
    """A normalised, scored, ranked supplier."""

    supplier_id: str
    name: str
    total_score: float = Field(description="0..1 weighted total, higher is better.")
    criteria: dict[str, float] = Field(
        description="Per-criterion 0..1 score where higher is always better."
    )
    rank: int = Field(description="1-based position; 1 is the best supplier.")


class SupplierRanking(EngineResult):
    """Outcome of deterministic supplier comparison."""

    ranked: list[RankedSupplier] = Field(default=(), description="Best supplier first.")
    criteria_weights: dict[str, float] = Field(
        description="Normalised weights actually applied to the criteria."
    )


def rank_suppliers(
    *,
    suppliers: Sequence[SupplierScore],
    weights: Optional[Mapping[str, float]] = None,
) -> SupplierRanking:
    """Score and rank the supplied :class:`SupplierScore` objects.

    Args:
        suppliers: The suppliers to compare. May be empty.
        weights: Criterion weights; defaults to :data:`DEFAULT_CRITERIA_WEIGHTS`.

    Returns:
        A :class:`SupplierRanking` with suppliers sorted best-first.

    Raises:
        ToolInputError: Two suppliers share an id, or any metric is outside its
            documented range.
    """
    resolved_weights = normalise_weights(weights or DEFAULT_CRITERIA_WEIGHTS)

    seen_ids: set[str] = set()
    computed: list[tuple[SupplierScore, dict[str, float], float]] = []
    for supplier in suppliers:
        supplier_id = require_non_empty(supplier.supplier_id, "suppliers[].supplier_id")
        if supplier_id in seen_ids:
            raise ToolInputError(
                f"Duplicate supplier_id {supplier_id!r} supplied; each supplier must be unique."
            )
        seen_ids.add(supplier_id)

        reliability = _require_range(supplier.reliability, "reliability", 0.0, 1.0)
        quality = _require_range(supplier.quality_score, "quality_score", 0.0, 1.0)
        price = _require_range(supplier.price_index, "price_index", 0.0, PRICE_INDEX_WORST)
        capacity = _require_range(supplier.capacity_utilisation, "capacity_utilisation", 0.0, 1.0)
        lead_time = require_positive(supplier.lead_time_days, "lead_time_days", allow_zero=True)

        criteria = {
            "reliability": round_units(normalise_higher_is_better(reliability, worst=0.0, best=1.0)),
            "quality": round_units(normalise_higher_is_better(quality, worst=0.0, best=1.0)),
            "price": round_units(normalise_lower_is_better(price, best=0.0, worst=PRICE_INDEX_WORST)),
            "capacity": round_units(normalise_lower_is_better(capacity, best=0.0, worst=1.0)),
            "lead_time": round_units(normalise_lower_is_better(lead_time, best=0.0, worst=MAX_LEAD_TIME_DAYS)),
        }
        total = round_units(weighted_total(criteria, resolved_weights), 6)
        computed.append((supplier, criteria, total))

    computed.sort(key=lambda item: (-item[2], item[0].supplier_id))

    ranked = [
        RankedSupplier(
            supplier_id=supplier.supplier_id,
            name=supplier.name,
            total_score=total,
            criteria=criteria,
            rank=position,
        )
        for position, (supplier, criteria, total) in enumerate(computed, start=1)
    ]

    return SupplierRanking(
        ranked=ranked,
        criteria_weights=resolved_weights,
        assumptions=(
            f"{len(ranked)} supplier(s) compared.",
            "All criteria normalised so higher is always better, using fixed anchors.",
            f"Price anchors 0.0 (cheapest) .. {PRICE_INDEX_WORST} (worst); "
            f"lead-time anchor {MAX_LEAD_TIME_DAYS} days (worst).",
            "Ranked by total score, then supplier_id.",
        ),
    )


def _require_range(value: object, name: str, low: float, high: float) -> float:
    """Return ``value`` as a float inside the inclusive ``[low, high]`` range."""
    number = require_number(value, name)
    if number < low or number > high:
        raise ToolInputError(f"{name} must be between {low} and {high}, got {number}.")
    return number
