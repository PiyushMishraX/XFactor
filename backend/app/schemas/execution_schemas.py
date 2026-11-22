"""Structured records for authorized execution (Step 6).

An execution report is the audit trail of what the platform actually did *after*
a human approved a proposal. It is produced only by
:mod:`app.services.execution`, never by an agent or an LLM.

The four action types mirror the roadmap's execution capabilities:

* ``shipment_plan_update`` — apply the approved shipment/route plan.
* ``inventory_transfer`` — request the approved stock transfer.
* ``carrier_change`` — request the approved carrier change.
* ``sap_execution`` — record the approved action in SAP.

Every action carries an idempotency key so a retried approval can never execute
the same operational action twice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExecutionActionType(str, Enum):
    """The operational actions the execution service can perform."""

    SHIPMENT_PLAN_UPDATE = "shipment_plan_update"
    INVENTORY_TRANSFER = "inventory_transfer"
    CARRIER_CHANGE = "carrier_change"
    SAP_EXECUTION = "sap_execution"


class ExecutionActionStatus(str, Enum):
    """Outcome of one operational action."""

    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ExecutionRunStatus(str, Enum):
    """Outcome of a whole execution run."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ExecutionAction(BaseModel):
    """One operational action, its deterministic payload and its outcome."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action_id: str = Field(description="Stable identifier within the run.")
    action_type: ExecutionActionType
    description: str
    idempotency_key: str = Field(
        description="Unique key for this action; a retry with the same key is not re-executed."
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict, description="JSON-safe arguments sent to the adapter."
    )
    status: ExecutionActionStatus = ExecutionActionStatus.SKIPPED
    adapter: str = ""
    is_mock: bool = Field(
        default=True, description="True when the adapter simulated the action."
    )
    external_reference: str = Field(
        default="", description="Reference returned by the target system, when any."
    )
    message: str = ""
    executed_at: Optional[datetime] = None


class ExecutionReport(BaseModel):
    """The complete, persisted record of one authorized execution run."""

    execution_id: str
    thread_id: str
    proposal_id: str
    proposal_version: str
    status: ExecutionRunStatus = ExecutionRunStatus.COMPLETED
    idempotent_replay: bool = Field(
        default=False,
        description="True when an identical execution already existed and was returned as-is.",
    )
    actions: List[ExecutionAction] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


__all__ = [
    "ExecutionAction",
    "ExecutionActionStatus",
    "ExecutionActionType",
    "ExecutionReport",
    "ExecutionRunStatus",
]
