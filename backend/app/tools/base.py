"""Shared foundation for the deterministic engines (Step 2).

Every engine in this package:

* is a pure Python service — it performs real arithmetic and never calls an LLM;
* validates its inputs and raises :class:`ToolInputError` rather than returning a
  meaningless number;
* returns a structured Pydantic result that lists the assumptions it made;
* is independently reusable by any agent.

Assumptions
-----------
* All monetary values are US dollars.
* Rates and constants in the individual engines are *indicative planning
  values* for the hackathon dataset, documented in each module. They are
  configuration-style constants, deliberately kept in code so the maths is
  auditable, not hidden inside a prompt.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolInputError(ValueError):
    """Raised when a deterministic engine receives input it cannot compute on."""


class EngineResult(BaseModel):
    """Common shape for deterministic engine outputs."""

    model_config = ConfigDict(frozen=True)

    assumptions: tuple[str, ...] = Field(
        default=(),
        description="Documented assumptions the calculation relied on.",
    )


# ---------------------------------------------------------------------------
# Input guards
# ---------------------------------------------------------------------------


def require_number(value: object, name: str) -> float:
    """Return ``value`` as a float, or raise when it is not a real number."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ToolInputError(f"{name} must be a number, got {value!r}.") from exc
    if math.isnan(number) or math.isinf(number):
        raise ToolInputError(f"{name} must be a finite number, got {value!r}.")
    return number


def require_positive(value: object, name: str, *, allow_zero: bool = False) -> float:
    """Return ``value`` as a float and require it to be > 0 (or >= 0)."""
    number = require_number(value, name)
    if allow_zero:
        if number < 0:
            raise ToolInputError(f"{name} must be >= 0, got {number}.")
    elif number <= 0:
        raise ToolInputError(f"{name} must be > 0, got {number}.")
    return number


def require_non_empty(value: object, name: str) -> str:
    """Return a stripped non-empty string, or raise."""
    text = str(value or "").strip()
    if not text:
        raise ToolInputError(f"{name} must be a non-empty value.")
    return text


def require_choice(value: object, allowed: Iterable[str], name: str) -> str:
    """Return ``value`` when it is one of ``allowed`` (case-insensitive)."""
    text = str(value or "").strip()
    for candidate in allowed:
        if text.lower() == str(candidate).lower():
            return str(candidate)
    raise ToolInputError(f"{name} must be one of {sorted(str(a) for a in allowed)}, got {value!r}.")


# ---------------------------------------------------------------------------
# Scoring helpers (used by the ranking engines)
# ---------------------------------------------------------------------------


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` into the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))


def normalise_higher_is_better(value: float, worst: float, best: float) -> float:
    """Map ``value`` to 0..1 where a *larger* raw value scores higher."""
    if best == worst:
        return 1.0
    return clamp((value - worst) / (best - worst))


def normalise_lower_is_better(value: float, best: float, worst: float) -> float:
    """Map ``value`` to 0..1 where a *smaller* raw value scores higher."""
    return normalise_higher_is_better(-value, -worst, -best)


def normalise_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Return ``weights`` scaled to sum to 1.0 (raises when all are zero)."""
    total = sum(max(0.0, float(weight)) for weight in weights.values())
    if total <= 0:
        raise ToolInputError("Ranking weights must contain at least one positive value.")
    return {key: max(0.0, float(weight)) / total for key, weight in weights.items()}


def weighted_total(contributions: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted sum, assuming ``weights`` are already normalised."""
    return sum(contributions.get(key, 0.0) * weights.get(key, 0.0) for key in weights)


def round_money(value: float) -> float:
    """Round a monetary amount to cents."""
    return round(float(value), 2)


def round_units(value: float, digits: int = 3) -> float:
    """Round a non-monetary quantity (days, units, scores)."""
    return round(float(value), digits)


def optional_number(value: Optional[object]) -> Optional[float]:
    """Best-effort float conversion that returns ``None`` instead of raising."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
