"""Authorized execution of an approved recovery proposal (Step 6).

Nothing here runs unless a human approval has already been recorded. The service
is separate from the agents and from the LLM: it takes the exact
:class:`~app.schemas.approval_schemas.ProposalSnapshot` a human approved, builds
a deterministic execution plan, and applies it through one adapter.

Safety properties
-----------------
* **No authorization, no execution.** :meth:`ExecutionService.execute` refuses a
  proposal that did not require approval and carry a proposal version.
* **Idempotent.** Every action has an idempotency key derived from the thread and
  proposal version, and a completed report for that version is replayed instead
  of executed again. The live adapter additionally sends the key as an
  ``Idempotency-Key`` header.
* **Clearly labelled simulations.** The default adapter never touches an
  operational system; it returns deterministic ``[SIMULATED]`` references.
* **Honest failures.** An adapter failure is recorded as a failed action and
  produces a ``partial``/``failed`` report instead of being swallowed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Protocol

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpJsonClient,
    IntegrationNotConfiguredError,
    IntegrationRequestError,
    stable_seed,
)
from app.schemas.approval_schemas import ProposalSnapshot
from app.schemas.execution_schemas import (
    ExecutionAction,
    ExecutionActionStatus,
    ExecutionActionType,
    ExecutionReport,
    ExecutionRunStatus,
)

logger = logging.getLogger(__name__)


class ExecutionNotAuthorizedError(RuntimeError):
    """Execution was requested for a proposal that was not approved for action."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionAdapter(Protocol):
    """Applies one execution action to the target system."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def execute(self, action: ExecutionAction) -> ExecutionAction: ...


class ExecutionStore(Protocol):
    """Persistence the service needs to replay idempotent executions."""

    def get_execution(self, thread_id: str, proposal_version: str) -> Optional[ExecutionReport]: ...

    def save_execution(self, thread_id: str, report: ExecutionReport) -> Any: ...


# ---------------------------------------------------------------------------
# Deterministic execution plan
# ---------------------------------------------------------------------------


def build_execution_plan(proposal: ProposalSnapshot) -> List[ExecutionAction]:
    """Translate an approved proposal into the operational actions to perform."""
    common = {
        "event_id": proposal.event_id,
        "proposal_id": proposal.proposal_id,
        "proposal_version": proposal.proposal_version,
        "scenario_id": proposal.recommended_scenario_id,
        "route_id": proposal.recommended_route_id,
        "carrier": proposal.recommended_carrier,
        "transport_mode": proposal.transport_mode,
    }
    actions: List[ExecutionAction] = [
        _action(
            proposal,
            index=1,
            action_type=ExecutionActionType.SHIPMENT_PLAN_UPDATE,
            description=(
                f"Apply the approved recovery plan for {proposal.event_id} via "
                f"{proposal.recommended_carrier or 'the approved carrier'}."
            ),
            payload={
                **common,
                "total_cost_usd": proposal.total_cost_usd,
                "total_days": proposal.total_days,
            },
        )
    ]
    if proposal.inventory_transfer_units > 0:
        actions.append(
            _action(
                proposal,
                index=len(actions) + 1,
                action_type=ExecutionActionType.INVENTORY_TRANSFER,
                description=(
                    f"Request the approved transfer of {proposal.inventory_transfer_units:g} "
                    f"unit(s)."
                ),
                payload={
                    **common,
                    "units": proposal.inventory_transfer_units,
                    "supplier_id": proposal.supplier_id,
                },
            )
        )
    if proposal.carrier_change_requested:
        actions.append(
            _action(
                proposal,
                index=len(actions) + 1,
                action_type=ExecutionActionType.CARRIER_CHANGE,
                description=(
                    "Request the carrier change to "
                    f"{proposal.recommended_carrier or 'the approved carrier'}."
                ),
                payload=dict(common),
            )
        )
    if proposal.supplier_id:
        actions.append(
            _action(
                proposal,
                index=len(actions) + 1,
                action_type=ExecutionActionType.SAP_EXECUTION,
                description=(
                    f"Record the approved recovery against supplier {proposal.supplier_id} "
                    f"in SAP."
                ),
                payload={**common, "supplier_id": proposal.supplier_id},
            )
        )
    return actions


def _action(
    proposal: ProposalSnapshot,
    *,
    index: int,
    action_type: ExecutionActionType,
    description: str,
    payload: Mapping[str, Any],
) -> ExecutionAction:
    return ExecutionAction(
        action_id=f"{index}-{action_type.value}",
        action_type=action_type,
        description=description,
        idempotency_key=(
            f"{proposal.thread_id}:{proposal.proposal_version}:{action_type.value}"
        ),
        payload=dict(payload),
    )


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class SimulatedExecutionAdapter:
    """Clearly labelled execution double; changes no operational system."""

    name = "simulated-execution"
    is_mock = True
    provider = "[SIMULATED] X FACTOR execution adapter"

    def execute(self, action: ExecutionAction) -> ExecutionAction:
        reference = (
            f"SIM-{action.action_type.value.upper()}-"
            f"{stable_seed(action.idempotency_key):08X}"
        )
        return action.model_copy(
            update={
                "status": ExecutionActionStatus.EXECUTED,
                "adapter": self.provider,
                "is_mock": True,
                "external_reference": reference,
                "message": (
                    "[SIMULATED] Action accepted by the simulated adapter; no operational "
                    "system was changed."
                ),
                "executed_at": _utc_now(),
            }
        )


#: The gateway endpoint each action type is posted to.
_EXECUTION_ENDPOINTS = {
    ExecutionActionType.SHIPMENT_PLAN_UPDATE: "/shipments/plan",
    ExecutionActionType.INVENTORY_TRANSFER: "/inventory/transfers",
    ExecutionActionType.CARRIER_CHANGE: "/carriers/change",
    ExecutionActionType.SAP_EXECUTION: "/sap/execute",
}


class HttpExecutionAdapter:
    """Live execution through the configured enterprise gateway."""

    name = "live-execution"
    is_mock = False
    provider = "Live execution gateway"

    def __init__(
        self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None
    ) -> None:
        settings = settings or get_settings()
        self._client_id = settings.EXECUTION_CLIENT_ID
        self._client = client or HttpJsonClient(
            connector_name=self.name,
            base_url=settings.EXECUTION_BASE_URL,
            api_key=settings.EXECUTION_CLIENT_SECRET,
            timeout=settings.EXECUTION_TIMEOUT_SECONDS,
            max_attempts=settings.EXECUTION_MAX_ATTEMPTS,
        )

    def execute(self, action: ExecutionAction) -> ExecutionAction:
        endpoint = _EXECUTION_ENDPOINTS[action.action_type]
        try:
            response = self._client.post_json(
                endpoint,
                payload={**action.payload, "idempotency_key": action.idempotency_key},
                idempotency_key=action.idempotency_key,
                headers={"x-client-id": self._client_id} if self._client_id else None,
            )
        except IntegrationNotConfiguredError:
            raise
        except IntegrationRequestError as exc:
            logger.warning("Execution action %s failed: %s", action.action_id, exc)
            return action.model_copy(
                update={
                    "status": ExecutionActionStatus.FAILED,
                    "adapter": self.provider,
                    "is_mock": False,
                    "message": str(exc),
                    "executed_at": _utc_now(),
                }
            )
        reference = ""
        if isinstance(response, Mapping):
            reference = str(
                response.get("reference")
                or response.get("id")
                or response.get("request_id")
                or ""
            )
        return action.model_copy(
            update={
                "status": ExecutionActionStatus.EXECUTED,
                "adapter": self.provider,
                "is_mock": False,
                "external_reference": reference,
                "message": "Accepted by the live execution gateway.",
                "executed_at": _utc_now(),
            }
        )


def get_execution_adapter(settings: Optional[Settings] = None) -> ExecutionAdapter:
    """Return the simulated adapter by default, or the live one when configured.

    Raises:
        IntegrationNotConfiguredError: Mock mode is off but no execution gateway
            credentials are configured.
    """
    settings = settings or get_settings()
    if settings.EXECUTION_USE_MOCK:
        logger.info("EXECUTION_USE_MOCK is enabled — using the simulated execution adapter.")
        return SimulatedExecutionAdapter()
    if not settings.execution_configured:
        raise IntegrationNotConfiguredError(
            "EXECUTION_USE_MOCK is false but EXECUTION_BASE_URL / EXECUTION_CLIENT_ID / "
            "EXECUTION_CLIENT_SECRET are not all configured. Configure them or set "
            "EXECUTION_USE_MOCK=true."
        )
    return HttpExecutionAdapter(settings)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ExecutionService:
    """Execute an approved proposal once, idempotently and with a full report."""

    def __init__(self, *, adapter: ExecutionAdapter, store: ExecutionStore) -> None:
        self._adapter = adapter
        self._store = store

    def execute(self, proposal: ProposalSnapshot) -> ExecutionReport:
        """Execute ``proposal`` unless an identical execution already exists.

        Raises:
            ExecutionNotAuthorizedError: The proposal was not approved for action
                or has no version to key the execution on.
        """
        if not proposal.requires_approval:
            raise ExecutionNotAuthorizedError(
                f"Proposal {proposal.proposal_id!r} does not require approval and therefore "
                f"cannot be executed by the approval execution path."
            )
        if not proposal.proposal_version:
            raise ExecutionNotAuthorizedError(
                f"Proposal {proposal.proposal_id!r} has no version; execution is refused "
                f"because it could not be made idempotent."
            )
        if not proposal.thread_id:
            raise ExecutionNotAuthorizedError(
                f"Proposal {proposal.proposal_id!r} is not bound to a workflow thread."
            )

        existing = self._store.get_execution(
            proposal.thread_id, proposal.proposal_version
        )
        if existing is not None:
            logger.info(
                "Replaying idempotent execution %s for thread %s",
                existing.execution_id,
                proposal.thread_id,
            )
            return existing.model_copy(update={"idempotent_replay": True})

        started_at = _utc_now()
        outcomes: List[ExecutionAction] = []
        for action in build_execution_plan(proposal):
            outcomes.append(self._run(action))

        failures = sum(
            1 for item in outcomes if item.status is ExecutionActionStatus.FAILED
        )
        if failures == 0:
            status = ExecutionRunStatus.COMPLETED
        elif failures == len(outcomes):
            status = ExecutionRunStatus.FAILED
        else:
            status = ExecutionRunStatus.PARTIAL

        report = ExecutionReport(
            execution_id=f"exec-{proposal.thread_id}-{proposal.proposal_version}",
            thread_id=proposal.thread_id,
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.proposal_version,
            status=status,
            actions=outcomes,
            started_at=started_at,
            completed_at=_utc_now(),
        )
        self._store.save_execution(proposal.thread_id, report)
        logger.info(
            "Executed proposal %s for thread %s: %s",
            proposal.proposal_id,
            proposal.thread_id,
            status.value,
        )
        return report

    def _run(self, action: ExecutionAction) -> ExecutionAction:
        try:
            return self._adapter.execute(action)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, never hidden
            logger.exception("Execution action %s raised", action.action_id)
            return action.model_copy(
                update={
                    "status": ExecutionActionStatus.FAILED,
                    "adapter": getattr(self._adapter, "name", "unknown"),
                    "is_mock": bool(getattr(self._adapter, "is_mock", True)),
                    "message": f"{type(exc).__name__}: {exc}",
                    "executed_at": _utc_now(),
                }
            )


__all__ = [
    "ExecutionAdapter",
    "ExecutionNotAuthorizedError",
    "ExecutionService",
    "ExecutionStore",
    "HttpExecutionAdapter",
    "SimulatedExecutionAdapter",
    "build_execution_plan",
    "get_execution_adapter",
]
