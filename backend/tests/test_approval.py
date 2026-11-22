"""Tests for the Approval Management Engine (``app.tools.approval``)."""

from __future__ import annotations

import pytest

from app.tools.approval import (
    DEFAULT_POLICY,
    ApprovalPolicy,
    ApprovalRequest,
    evaluate_approval,
)
from app.tools.base import ToolInputError


def test_low_impact_in_budget_proposal_needs_no_approval() -> None:
    request = ApprovalRequest(
        proposal_id="P1",
        action_type="Reroute shipment",
        total_cost_usd=1000.0,
        shipment_value_usd=1000.0,
        supplier_risk_tier="Low",
    )

    decision = evaluate_approval(request=request)

    assert decision.requires_approval is False
    assert decision.approval_level is None
    assert decision.reasons == []


def test_explicit_high_impact_reroute_is_director_level() -> None:
    request = ApprovalRequest(
        proposal_id="P2",
        action_type="Reroute shipment",
        shipment_value_usd=1_500_000.0,
        is_high_impact_reroute=True,
    )

    decision = evaluate_approval(request=request)

    assert decision.requires_approval is True
    assert decision.approval_level == "Director"
    assert any("High-impact reroute" in reason for reason in decision.reasons)


def test_high_value_shipment_alone_triggers_manager_approval() -> None:
    request = ApprovalRequest(
        proposal_id="P3",
        action_type="Reroute shipment",
        shipment_value_usd=1_500_000.0,
    )

    decision = evaluate_approval(request=request)

    assert decision.requires_approval is True
    assert decision.approval_level == "Manager"  # high value, but not flagged as a reroute
    assert any("High-impact reroute" in reason for reason in decision.reasons)


def test_cost_above_threshold_requires_manager_approval() -> None:
    request = ApprovalRequest(proposal_id="P4", action_type="Purchase", total_cost_usd=300_000.0)

    decision = evaluate_approval(request=request)

    assert decision.requires_approval is True
    assert decision.approval_level == "Manager"
    assert any("300000.0" in reason for reason in decision.reasons)


def test_cost_at_or_above_director_threshold_is_director() -> None:
    threshold = DEFAULT_POLICY.director_threshold_multiplier * DEFAULT_POLICY.budget_approval_threshold_usd
    assert threshold == 500_000.0

    at_threshold = evaluate_approval(
        request=ApprovalRequest(proposal_id="P5", action_type="Purchase", total_cost_usd=500_000.0)
    )
    assert at_threshold.approval_level == "Director"

    above = evaluate_approval(
        request=ApprovalRequest(proposal_id="P6", action_type="Purchase", total_cost_usd=800_000.0)
    )
    assert above.approval_level == "Director"


def test_cost_exactly_at_approval_threshold_is_allowed() -> None:
    decision = evaluate_approval(
        request=ApprovalRequest(proposal_id="P7", action_type="Purchase", total_cost_usd=250_000.0)
    )

    assert decision.requires_approval is False
    assert decision.reasons == []


def test_major_inventory_redistribution_triggers_approval() -> None:
    request = ApprovalRequest(
        proposal_id="P8", action_type="Redistribute stock", inventory_transfer_units=600.0
    )

    decision = evaluate_approval(request=request)

    assert decision.requires_approval is True
    assert decision.approval_level == "Manager"
    assert any("Major inventory redistribution" in reason for reason in decision.reasons)


def test_sensitive_supplier_tier_is_case_insensitive() -> None:
    decision = evaluate_approval(
        request=ApprovalRequest(
            proposal_id="P9", action_type="Switch supplier", supplier_risk_tier="critical"
        )
    )

    assert decision.requires_approval is True
    assert any("sensitive" in reason for reason in decision.reasons)


def test_compliance_flag_triggers_approval() -> None:
    decision = evaluate_approval(
        request=ApprovalRequest(
            proposal_id="P10", action_type="Import", compliance_requires_approval=True
        )
    )

    assert decision.requires_approval is True
    assert decision.approval_level == "Manager"


def test_custom_policy_thresholds_are_honoured() -> None:
    policy = ApprovalPolicy(budget_approval_threshold_usd=1000.0, director_threshold_multiplier=2.0)

    at_limit = evaluate_approval(
        request=ApprovalRequest(proposal_id="P11", action_type="Purchase", total_cost_usd=1000.0),
        policy=policy,
    )
    assert at_limit.requires_approval is False  # must be strictly greater

    over = evaluate_approval(
        request=ApprovalRequest(proposal_id="P12", action_type="Purchase", total_cost_usd=1001.0),
        policy=policy,
    )
    assert over.requires_approval is True
    assert over.approval_level == "Manager"  # 1001 < 2 * 1000


def test_negative_values_are_rejected() -> None:
    with pytest.raises(ToolInputError):
        evaluate_approval(
            request=ApprovalRequest(proposal_id="P13", action_type="Purchase", total_cost_usd=-1.0)
        )
    with pytest.raises(ToolInputError):
        evaluate_approval(
            request=ApprovalRequest(proposal_id="", action_type="Purchase")
        )


def test_approval_decision_is_repeatable() -> None:
    request = ApprovalRequest(
        proposal_id="P14", action_type="Reroute shipment", shipment_value_usd=2_000_000.0
    )

    assert evaluate_approval(request=request) == evaluate_approval(request=request)
