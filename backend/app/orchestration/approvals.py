"""Deterministic approval mechanics for the human-in-the-loop gate (Step 6).

This module sits between the graph and the approval API and is free of FastAPI,
SQLAlchemy and (for the builders) LangGraph:

* :func:`build_proposal_snapshot` turns the paused workflow state into the exact
  :class:`~app.schemas.approval_schemas.ProposalSnapshot` a human reviews, with a
  deterministic SHA-256 version.
* :func:`parse_approval_decision` reads the value the graph was resumed with into
  an auditable :class:`~app.schemas.approval_schemas.ApprovalDecisionRecord`.
  Legacy ``{"approved": true}`` payloads still work and are attributed to
  ``"human"``, which is what the Step 4 tests exercise.
* :func:`build_modification_revision` converts a "request modifications" decision
  into concrete revision instructions for the Scenario agent, applying the same
  bounded-autonomy rule as the deterministic screening loop.

Bounded reconsideration: :data:`MAX_MODIFICATION_ROUNDS` caps how many times a
reviewer may send the same proposal back, so the workflow cannot loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.orchestration.state import RecoveryRequest
from app.schemas.approval_schemas import (
    ApprovalAction,
    ApprovalDecisionRecord,
    ApproverIdentity,
    ProposalSnapshot,
)
from app.schemas.scenario_schemas import ScenarioRevision
from app.services.execution import build_execution_plan

#: How many times a human may request modifications before the workflow closes.
MAX_MODIFICATION_ROUNDS = 2

_APPROVE_WORDS = {"approve", "approved", "yes", "true", "ok"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _plane(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The recommended scenario or route currently on the table."""
    plan = state.get("scenario_plan") or {}
    scenarios = plan.get("scenarios") or []
    if plan and scenarios:
        chosen = next(
            (
                item
                for item in scenarios
                if item.get("scenario_id") == plan.get("recommended_scenario_id")
            ),
            scenarios[0],
        )
        return {
            "source": "scenario",
            "scenario_id": str(chosen.get("scenario_id") or "") or None,
            "route_id": None,
            "carrier": str(chosen.get("carrier") or ""),
            "transport_mode": str(chosen.get("transport_mode") or ""),
            "total_cost_usd": float(chosen.get("total_cost_usd") or 0.0),
            "total_days": float(chosen.get("total_days") or 0.0),
        }

    analysis = state.get("rerouting") or {}
    routes = analysis.get("ranked_routes") or []
    if analysis and routes:
        chosen = next(
            (
                item
                for item in routes
                if item.get("route_id") == analysis.get("recommended_route_id")
            ),
            routes[0],
        )
        return {
            "source": "route",
            "scenario_id": None,
            "route_id": str(chosen.get("route_id") or "") or None,
            "carrier": str(chosen.get("carrier") or ""),
            "transport_mode": str(chosen.get("transport_mode") or ""),
            "total_cost_usd": float(chosen.get("total_cost_usd") or 0.0),
            "total_days": float(chosen.get("total_days") or 0.0),
        }
    return None


def build_proposal_snapshot(
    thread_id: str, state: Dict[str, Any]
) -> Optional[ProposalSnapshot]:
    """Build the reviewable proposal snapshot, or ``None`` when nothing was audited.

    ``thread_id`` is stored on the snapshot but excluded from its version, so the
    graph (which does not receive the thread id) and the API agree on the version.
    """
    audit = state.get("audit_report") or {}
    if not audit:
        return None
    request = RecoveryRequest.model_validate(state["request"])
    scenario = request.scenario_request
    chosen = _plane(state) or {
        "source": "",
        "scenario_id": None,
        "route_id": None,
        "carrier": "",
        "transport_mode": "",
        "total_cost_usd": 0.0,
        "total_days": 0.0,
    }
    approval = audit.get("approval") or {}
    event_id = scenario.event_id or request.disruption_report.derive_event_id()
    target = (
        f"scenario {chosen['scenario_id']}"
        if chosen["scenario_id"]
        else f"route {chosen['route_id']}"
    )
    carrier = chosen["carrier"]
    transfer_units = float(
        request.inventory_transfer_units
        or (state.get("rebalancing") or {}).get("total_transferred_units")
        or (state.get("scenario_plan") or {}).get("inventory_transfer_units")
        or 0.0
    )
    current_carrier = scenario.current_carrier.strip()
    carrier_change = bool(carrier) and carrier.strip().lower() != current_carrier.lower()

    snapshot = ProposalSnapshot(
        thread_id=thread_id,
        event_id=event_id,
        proposal_id=str(audit.get("proposal_id") or event_id),
        approval_level=str(approval.get("approval_level") or ""),
        requires_approval=bool(approval.get("requires_approval", True)),
        verdict=str(audit.get("verdict") or ""),
        is_compliant=bool(audit.get("is_compliant", False)),
        is_within_budget=bool(audit.get("is_within_budget", False)),
        reasons=[str(reason) for reason in (approval.get("reasons") or [])],
        violations=[
            str(item.get("detail"))
            for item in (audit.get("violations") or [])
            if isinstance(item, dict) and item.get("detail")
        ],
        headline=(
            f"{event_id}: {target} recommended via "
            f"{carrier or 'the incumbent carrier'}"
        ),
        summary=(
            f"Recommended {target} — carrier {carrier or 'unspecified'}, mode "
            f"{chosen['transport_mode'] or 'unspecified'}, cost "
            f"{chosen['total_cost_usd']:,.2f} USD, {chosen['total_days']:g} day(s) "
            f"transit. Human approval is required at "
            f"{approval.get('approval_level') or 'the approval gate'} level."
        ),
        recommended_scenario_id=chosen["scenario_id"],
        recommended_route_id=chosen["route_id"],
        recommended_carrier=carrier or None,
        transport_mode=chosen["transport_mode"] or None,
        total_cost_usd=chosen["total_cost_usd"],
        total_days=chosen["total_days"],
        shipment_value_usd=float(scenario.cargo_value_usd or 0.0),
        inventory_transfer_units=transfer_units,
        supplier_id=request.supplier_id,
        carrier_change_requested=carrier_change,
    )
    actions = [action.action_type.value for action in build_execution_plan(snapshot)]
    return snapshot.model_copy(update={"actions": actions}).with_version()


def proposal_version_of(thread_id: str, state: Dict[str, Any]) -> Optional[str]:
    """Convenience wrapper returning just the proposal version."""
    snapshot = build_proposal_snapshot(thread_id, state)
    return snapshot.proposal_version if snapshot is not None else None


# ---------------------------------------------------------------------------
# Resume payloads and decision records
# ---------------------------------------------------------------------------


def build_resume_payload(
    *,
    action: ApprovalAction,
    comment: str,
    proposal_version: str,
    identity: Optional[ApproverIdentity] = None,
    decided_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The value the graph is resumed with, carrying the full decision provenance."""
    return {
        "action": action.value,
        "approved": action is ApprovalAction.APPROVE,
        "comment": comment,
        "approver_id": identity.approver_id if identity is not None else "human",
        "approver_role": identity.role.value if identity is not None else "",
        "proposal_version": proposal_version,
        "decided_at": (decided_at or _utc_now()).isoformat(),
    }


def parse_approval_decision(value: Any) -> ApprovalDecisionRecord:
    """Read a resume value into a decision record.

    Supports the Step 6 payload built by :func:`build_resume_payload` and the
    simpler Step 4 payloads (``{"approved": bool}``, a bare bool or a word), which
    are attributed to ``"human"`` so existing behaviour is preserved.
    """
    if isinstance(value, dict):
        raw_action = str(value.get("action") or "").strip().lower()
        if raw_action in {item.value for item in ApprovalAction}:
            action = ApprovalAction(raw_action)
        else:
            action = (
                ApprovalAction.APPROVE
                if bool(value.get("approved"))
                else ApprovalAction.REJECT
            )
        comment = str(value.get("comment") or value.get("reason") or "")
        approver_id = str(value.get("approver_id") or value.get("decided_by") or "human")
        approver_role = str(value.get("approver_role") or "")
        proposal_version = str(value.get("proposal_version") or "")
        decided_at = _parse_time(value.get("decided_at"))
    elif isinstance(value, bool):
        action = ApprovalAction.APPROVE if value else ApprovalAction.REJECT
        comment = approver_role = proposal_version = ""
        approver_id = "human"
        decided_at = _utc_now()
    elif isinstance(value, str):
        text = value.strip()
        action = (
            ApprovalAction.APPROVE
            if text.lower() in _APPROVE_WORDS
            else ApprovalAction.REJECT
        )
        comment = text
        approver_role = proposal_version = ""
        approver_id = "human"
        decided_at = _utc_now()
    else:
        action = ApprovalAction.REJECT
        comment = "" if value is None else str(value)
        approver_role = proposal_version = ""
        approver_id = "human"
        decided_at = _utc_now()

    return ApprovalDecisionRecord(
        action=action,
        approver_id=approver_id,
        approver_role=approver_role,
        comment=comment,
        proposal_version=proposal_version,
        decided_at=decided_at,
    )


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _utc_now()
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return _utc_now()


# ---------------------------------------------------------------------------
# Modification feedback
# ---------------------------------------------------------------------------


def build_modification_revision(
    state: Dict[str, Any],
    *,
    round_number: int,
    comment: str,
) -> ScenarioRevision:
    """Turn a reviewer's modification request into revision instructions."""
    plan = state.get("scenario_plan") or {}
    scenario_ids = [
        str(item.get("scenario_id"))
        for item in (plan.get("scenarios") or [])
        if item.get("scenario_id")
    ]
    recommended = plan.get("recommended_scenario_id")
    rejected_ids = [recommended] if recommended else scenario_ids
    if not rejected_ids:
        route = _plane(state)
        if route is not None:
            rejected_ids = [
                route["scenario_id"] or route["route_id"] or "current-recommendation"
            ]

    audit = state.get("audit_report") or {}
    reasons = _deduplicate(
        [
            *(
                str(item.get("detail"))
                for item in (audit.get("violations") or [])
                if isinstance(item, dict) and item.get("detail")
            ),
            *[str(reason) for reason in ((audit.get("approval") or {}).get("reasons") or [])],
            comment,
        ]
    )
    feedback = (
        f"Human review requested modifications: {comment or 'no comment supplied'}."
        + (f" Reviewer notes: {'; '.join(reasons)}" if reasons else "")
    )
    return ScenarioRevision(
        round=round_number,
        rejected_scenario_ids=[str(item) for item in rejected_ids if item],
        rejection_reasons=reasons,
        excluded_carriers=[],
        feedback=feedback,
    )


def _deduplicate(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


__all__ = [
    "MAX_MODIFICATION_ROUNDS",
    "build_modification_revision",
    "build_proposal_snapshot",
    "build_resume_payload",
    "parse_approval_decision",
    "proposal_version_of",
]
