"""Budget Validation Engine (Step 2).

Deterministic budget check for a single proposed spend: does it fit inside the
available budget, and by how much does it miss or under-use it? No LLM is
involved.

Assumptions
-----------
* Both the proposed cost and the available budget are non-negative US-dollar
  amounts; negatives are rejected rather than interpreted.
* ``remaining_budget_usd = available_budget_usd - proposed_cost_usd`` (may be
  negative when the proposal overspends).
* ``overage_usd = max(0, proposed_cost_usd - available_budget_usd)`` — zero when
  the proposal fits.
* ``is_within_budget`` is ``proposed_cost_usd <= available_budget_usd`` (a spend
  of exactly the budget is *within* budget).
* ``utilisation_percent = proposed_cost_usd / available_budget_usd * 100``
  rounded to 2 dp while the budget is positive.
* **Zero-budget convention (explicit):** when the available budget is ``0`` the
  ratio is undefined, so the engine special-cases it —
  - a zero-cost proposal reports ``utilisation_percent = 0.0`` (nothing spent,
    nothing to spend), and
  - a positive-cost proposal reports ``utilisation_percent = float("inf")``, a
    value *above 100* that signals "spend against zero budget", paired with the
    concrete ``overage_usd``.
* Money is rounded with :func:`app.tools.base.round_money`.
"""

from __future__ import annotations

from app.tools.base import EngineResult, require_positive, round_money


class BudgetValidation(EngineResult):
    """Deterministic budget-check outcome for one proposal."""

    proposed_cost_usd: float
    available_budget_usd: float
    is_within_budget: bool
    remaining_budget_usd: float
    overage_usd: float
    utilisation_percent: float


def validate_budget(
    *,
    proposed_cost_usd: float,
    available_budget_usd: float,
) -> BudgetValidation:
    """Return the deterministic :class:`BudgetValidation` for one proposal.

    Args:
        proposed_cost_usd: Cost of the proposal being checked (>= 0).
        available_budget_usd: Budget available for it (>= 0).

    Raises:
        ToolInputError: Either amount is negative or non-numeric.
    """
    proposed = require_positive(proposed_cost_usd, "proposed_cost_usd", allow_zero=True)
    available = require_positive(available_budget_usd, "available_budget_usd", allow_zero=True)

    remaining = available - proposed
    overage = max(0.0, proposed - available)
    is_within_budget = proposed <= available

    if available > 0:
        utilisation = round(proposed / available * 100.0, 2)
    elif proposed == 0:
        utilisation = 0.0
    else:
        utilisation = float("inf")

    return BudgetValidation(
        proposed_cost_usd=round_money(proposed),
        available_budget_usd=round_money(available),
        is_within_budget=is_within_budget,
        remaining_budget_usd=round_money(remaining),
        overage_usd=round_money(overage),
        utilisation_percent=utilisation,
        assumptions=(
            "remaining = available - proposed; overage = max(0, proposed - available).",
            "A spend exactly equal to the budget is considered within budget.",
            "Zero budget with a zero proposal reports utilisation 0.0.",
            "Zero budget with a positive proposal reports utilisation = infinity (above 100).",
        ),
    )
