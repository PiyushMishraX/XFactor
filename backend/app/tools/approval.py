"""Approval Management Engine (Step 2).

Decides **whether a human must approve a proposal, and at what level** — and
does nothing else. It never executes an action, never sends a message and never
calls an LLM; it returns an explainable decision so the workflow layer can route
the proposal to a person.

Assumptions
-----------
* Policy thresholds come from an :class:`ApprovalPolicy`, defaulting to
  :data:`DEFAULT_POLICY`. A reason is added for every rule that fires, so the
  decision is fully auditable.
* High-impact reroute: triggered by the explicit
  ``is_high_impact_reroute`` flag **or** by ``shipment_value_usd`` reaching
  ``high_impact_shipment_value_usd``.
* Major inventory redistribution: ``inventory_transfer_units`` at or above
  ``major_inventory_transfer_units``.
* Cost above the approval threshold: ``total_cost_usd`` *strictly greater than*
  ``budget_approval_threshold_usd`` (a cost exactly at the threshold is allowed).
* Sensitive supplier change: ``supplier_risk_tier`` matches one of
  ``sensitive_supplier_risk_tiers`` case-insensitively.
* Compliance mandated approval: the ``compliance_requires_approval`` flag is set.
* ``requires_approval`` is true whenever at least one reason fired; an empty
  ``reasons`` list is the correct answer for a low-impact, in-budget proposal.
* ``approval_level`` is ``"Director"`` when ``total_cost_usd`` reaches
  ``director_threshold_multiplier * budget_approval_threshold_usd`` or the
  proposal is an explicit high-impact reroute; otherwise ``"Manager"`` when
  approval is required; otherwise ``None``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.tools.base import (
    EngineResult,
    require_non_empty,
    require_positive,
    round_money,
)


class ApprovalPolicy(BaseModel):
    """Configurable thresholds that decide when a human must approve."""

    high_impact_shipment_value_usd: float = 1_000_000.0
    major_inventory_transfer_units: float = 500.0
    budget_approval_threshold_usd: float = 250_000.0
    sensitive_supplier_risk_tiers: tuple[str, ...] = ("High", "Critical")
    director_threshold_multiplier: float = 2.0


#: The policy applied when the caller does not supply one.
DEFAULT_POLICY = ApprovalPolicy(
    high_impact_shipment_value_usd=1_000_000.0,
    major_inventory_transfer_units=500.0,
    budget_approval_threshold_usd=250_000.0,
    sensitive_supplier_risk_tiers=("High", "Critical"),
    director_threshold_multiplier=2.0,
)


class ApprovalRequest(BaseModel):
    """The deterministic facts of a proposal that the policy is evaluated on."""

    proposal_id: str
    action_type: str = Field(description="Human-readable action, e.g. 'Reroute shipment'.")
    total_cost_usd: float = 0.0
    shipment_value_usd: float = 0.0
    inventory_transfer_units: float = 0.0
    supplier_risk_tier: str = ""
    is_high_impact_reroute: bool = False
    compliance_requires_approval: bool = False


class ApprovalDecision(EngineResult):
    """Outcome of deterministic approval evaluation (a decision, not an action)."""

    proposal_id: str
    requires_approval: bool
    approval_level: Optional[str] = Field(
        default=None, description="None, 'Manager' or 'Director'."
    )
    reasons: list[str] = Field(
        default=(), description="One human-readable sentence per policy rule that fired."
    )


def evaluate_approval(
    *,
    request: ApprovalRequest,
    policy: Optional[ApprovalPolicy] = None,
) -> ApprovalDecision:
    """Return the deterministic :class:`ApprovalDecision` for ``request``.

    Args:
        request: The proposal's deterministic facts.
        policy: Thresholds to apply; defaults to :data:`DEFAULT_POLICY`.

    Raises:
        ToolInputError: The request is missing an id/action, or carries a
            negative cost, shipment value or transfer quantity.
    """
    applied = policy or DEFAULT_POLICY

    require_non_empty(request.proposal_id, "request.proposal_id")
    require_non_empty(request.action_type, "request.action_type")
    total_cost = require_positive(request.total_cost_usd, "request.total_cost_usd", allow_zero=True)
    shipment_value = require_positive(request.shipment_value_usd, "request.shipment_value_usd", allow_zero=True)
    transfer_units = require_positive(
        request.inventory_transfer_units, "request.inventory_transfer_units", allow_zero=True
    )

    reasons: list[str] = []

    if request.is_high_impact_reroute or shipment_value >= applied.high_impact_shipment_value_usd:
        reasons.append(
            f"High-impact reroute: shipment value {round_money(shipment_value)} USD against "
            f"the threshold {round_money(applied.high_impact_shipment_value_usd)} USD."
        )

    if transfer_units >= applied.major_inventory_transfer_units:
        reasons.append(
            f"Major inventory redistribution of {round_money(transfer_units)} units against "
            f"the threshold {round_money(applied.major_inventory_transfer_units)} units."
        )

    if total_cost > applied.budget_approval_threshold_usd:
        reasons.append(
            f"Cost {round_money(total_cost)} USD exceeds the approval threshold "
            f"{round_money(applied.budget_approval_threshold_usd)} USD."
        )

    sensitive_tiers = {tier.strip().lower() for tier in applied.sensitive_supplier_risk_tiers}
    if request.supplier_risk_tier.strip().lower() in sensitive_tiers:
        reasons.append(
            f"Supplier risk tier '{request.supplier_risk_tier}' is sensitive and requires review."
        )

    if request.compliance_requires_approval:
        reasons.append("Compliance rules mandate human approval for this proposal.")

    requires_approval = bool(reasons)

    director_threshold = applied.director_threshold_multiplier * applied.budget_approval_threshold_usd
    if total_cost >= director_threshold or request.is_high_impact_reroute:
        approval_level: Optional[str] = "Director"
    elif requires_approval:
        approval_level = "Manager"
    else:
        approval_level = None

    return ApprovalDecision(
        proposal_id=request.proposal_id,
        requires_approval=requires_approval,
        approval_level=approval_level,
        reasons=reasons,
        assumptions=(
            f"Policy: high-impact at {round_money(applied.high_impact_shipment_value_usd)} USD, "
            f"major transfer at {round_money(applied.major_inventory_transfer_units)} units, "
            f"cost threshold at {round_money(applied.budget_approval_threshold_usd)} USD.",
            "Director level at "
            f"{round_money(director_threshold)} USD or on an explicit high-impact reroute.",
            "This engine only decides; it never executes the action.",
        ),
    )
