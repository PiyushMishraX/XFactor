"""Shared workflow state for the LangGraph supervisor (Step 4).

This module holds the *data* of the orchestration layer, not the orchestration
itself:

* :class:`RecoveryRequest` — everything the supervisor needs to run one
  disruption through the five agents. It is validated before the workflow
  starts, so a malformed request fails loudly instead of half-way through.
* :class:`WorkflowState` — the LangGraph state schema. It is a ``TypedDict``
  whose accumulating fields carry a reducer, so agent nodes can append to the
  decision log, the execution history, the error list and the merged
  missing-information list without clobbering each other.
* :class:`SupervisorDecision` — the supervisor's *recorded* reasoning for every
  delegation. The workflow therefore explains itself from structured data, not
  from a conversation transcript.
* :class:`RecoveryRecommendation` — the deterministic final answer.

State values are stored as JSON-safe dictionaries (``model_dump(mode="json")``)
rather than as live Pydantic objects. That keeps the whole state serializable,
which is what the PostgreSQL checkpoint backend requires, and every node
re-validates the fields it reads back into their Pydantic models.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.audit_schemas import AuditVerdict
from app.schemas.approval_schemas import ApprovalDecisionRecord
from app.schemas.collaboration_schemas import (
    AgentExecution,
    AgentTask,
    ReplanningRecord,
    ScenarioHistoryEntry,
    ScenarioScreening,
    ToolInvocation,
)
from app.schemas.disruption_schemas import DisruptionReport, EvidenceItem
from app.schemas.scenario_schemas import ScenarioRequest
from app.tools.approval import ApprovalPolicy
from app.tools.compliance import ComplianceRule, RuleType

# ---------------------------------------------------------------------------
# Node / agent identifiers
# ---------------------------------------------------------------------------

#: LangGraph node names. The five agent nodes use the agent identifiers so that
#: a decision recorded as "route to rerouting_logistics" names the same node.
AGENT_SENSING = "disruption_sensing"
AGENT_REROUTING = "rerouting_logistics"
AGENT_REBALANCING = "inventory_rebalancing"
AGENT_SCENARIO = "scenario_planning"
AGENT_COMPLIANCE = "compliance_audit"

NODE_SUPERVISOR = "supervisor"
NODE_APPROVAL_GATE = "approval_gate"
NODE_FINALIZE = "finalize"
NODE_ERROR = "error_handler"

#: The five specialized agents the supervisor may delegate to.
AGENT_NODES: tuple[str, ...] = (
    AGENT_SENSING,
    AGENT_REROUTING,
    AGENT_REBALANCING,
    AGENT_SCENARIO,
    AGENT_COMPLIANCE,
)

# ---------------------------------------------------------------------------
# Workflow statuses
# ---------------------------------------------------------------------------

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_NO_ACTION = "no_action_required"
STATUS_NO_FEASIBLE_RECOVERY = "no_feasible_recovery"
STATUS_NO_COMPLIANT_RECOVERY = "no_compliant_recovery"
STATUS_APPROVAL_REJECTED = "approval_rejected"
STATUS_ITERATION_LIMIT = "iteration_limit_reached"
STATUS_FAILED = "failed"

# ---------------------------------------------------------------------------
# Default compliance policy
# ---------------------------------------------------------------------------

#: Indicative planning policy used when the caller does not supply rules.
#:
#: The compliance engine deliberately has no policy of its own and refuses to
#: run on an empty rule set, so the supervisor needs *some* explicit rule set to
#: audit against. These are configuration values for the hackathon dataset, not
#: business data: any caller can override them on :class:`RecoveryRequest`.
DEFAULT_COMPLIANCE_RULES: tuple[ComplianceRule, ...] = (
    ComplianceRule(
        rule_id="POL-MAX-SPEND",
        description="A single recovery action may not exceed the delegated spend limit.",
        rule_type=RuleType.MAX_SPEND,
        max_value=5_000_000.0,
    ),
    ComplianceRule(
        rule_id="POL-BUDGET-APPROVAL",
        description="Spend above the approval threshold needs a human sign-off.",
        rule_type=RuleType.BUDGET_APPROVAL_REQUIRED,
        max_value=250_000.0,
    ),
    ComplianceRule(
        rule_id="POL-CARRIER-RELIABILITY",
        description="Recovery must not use a carrier below the reliability floor.",
        rule_type=RuleType.MIN_CARRIER_RELIABILITY,
        max_value=0.60,
    ),
    ComplianceRule(
        rule_id="POL-RESTRICTED-COUNTRIES",
        description="A recovery route may not touch a restricted country.",
        rule_type=RuleType.RESTRICTED_COUNTRY,
        blocked_values=("Russia", "Belarus", "North Korea", "Iran", "Syria"),
    ),
)

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class RecoveryRequest(BaseModel):
    """One disruption submitted to the supervisor for a recovery recommendation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    disruption_report: DisruptionReport = Field(
        description="The unstructured event the Disruption Sensing Agent reads."
    )
    scenario_request: ScenarioRequest = Field(
        description=(
            "The affected lane, cargo and budget. Its optional ``inventory`` field is "
            "what tells the supervisor whether an inventory analysis is required."
        )
    )
    applicable_rules: List[ComplianceRule] = Field(
        default_factory=lambda: list(DEFAULT_COMPLIANCE_RULES),
        description="Deterministic rules the Compliance & Audit Agent validates against.",
    )
    approval_policy: Optional[ApprovalPolicy] = Field(
        default=None, description="Thresholds for the approval decision; None uses the default."
    )
    supplier_risk_tier: str = ""
    is_high_impact_reroute: bool = False
    inventory_transfer_units: float = Field(
        default=0.0, ge=0, description="Units moved, used by the approval policy."
    )

    # --- Compliance facts the caller may know and the platform cannot infer ---
    supplier_id: str = ""
    origin_country: str = ""
    destination_country: str = ""
    transit_countries: tuple[str, ...] = ()
    certifications: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Supervisor decision log
# ---------------------------------------------------------------------------


class SupervisorDecision(BaseModel):
    """Why the supervisor routed where it routed.

    Recorded for every pass so the workflow is auditable after the fact and never
    has to be reconstructed from a conversation.
    """

    step: int = Field(description="1-based supervisor pass number.")
    action: str = Field(description="The node the supervisor selected next.")
    reason: str = Field(description="The structured evidence behind that selection.")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class RecoveryRecommendation(BaseModel):
    """The supervisor's deterministic final answer for one disruption."""

    event_id: str
    status: str = Field(description="One of the ``STATUS_*`` constants.")
    headline: str
    summary: str

    recommended_scenario_id: Optional[str] = None
    recommended_carrier: Optional[str] = None
    recommended_route_id: Optional[str] = None
    audit_verdict: Optional[AuditVerdict] = None
    requires_approval: bool = False
    approval_level: Optional[str] = None

    delegated_agents: List[str] = Field(
        default_factory=list, description="Every agent execution, in order, including retries."
    )
    decision_log: List[SupervisorDecision] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    iterations: int = Field(default=0, description="Agent executions performed.")

    # --- Collaboration record (Step 5) ----------------------------------
    tasks: List[AgentTask] = Field(
        default_factory=list, description="Every task the supervisor issued, in order."
    )
    agent_executions: List[AgentExecution] = Field(
        default_factory=list, description="Every execution attempt, with its tool calls."
    )
    tool_calls: List[ToolInvocation] = Field(
        default_factory=list, description="Flat, ordered list of every recorded tool call."
    )
    scenario_screening: Optional[ScenarioScreening] = Field(
        default=None, description="Deterministic evaluation of the final scenario set."
    )
    scenario_history: List[ScenarioHistoryEntry] = Field(
        default_factory=list, description="Scenario plans preserved through replanning."
    )
    replanning: List[ReplanningRecord] = Field(
        default_factory=list, description="Every replanning round and what triggered it."
    )
    replanning_rounds: int = Field(default=0, description="Revision rounds actually performed.")
    skipped_agents: List[str] = Field(
        default_factory=list,
        description="Agents whose task could not run because an integration was unavailable.",
    )

    # --- Human approval record (Step 6) ---------------------------------
    proposal_version: Optional[str] = Field(
        default=None, description="Deterministic version of the proposal that was decided."
    )
    approval_history: List[ApprovalDecisionRecord] = Field(
        default_factory=list,
        description="Every authenticated human decision, in order, across reconsideration rounds.",
    )


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------


def _merge_attempts(current: Dict[str, int], update: Dict[str, int]) -> Dict[str, int]:
    """Reducer that merges per-agent attempt counters instead of replacing them."""
    merged = dict(current or {})
    for agent, count in (update or {}).items():
        merged[agent] = max(merged.get(agent, 0), count)
    return merged


class WorkflowState(TypedDict, total=False):
    """The shared state every node in the supervisor graph reads and updates.

    Output fields hold JSON dictionaries of the agents' validated results. The
    supervisor decides from those structured results — never from conversational
    memory.
    """

    # --- Input ---------------------------------------------------------
    request: Dict[str, Any]

    # --- Agent outputs (JSON dumps of the validated Pydantic models) ----
    assessment: Optional[Dict[str, Any]]
    rerouting: Optional[Dict[str, Any]]
    rebalancing: Optional[Dict[str, Any]]
    scenario_plan: Optional[Dict[str, Any]]
    audit_report: Optional[Dict[str, Any]]
    approval: Optional[Dict[str, Any]]

    # --- Accumulating bookkeeping --------------------------------------
    decisions: Annotated[List[Dict[str, Any]], operator.add]
    completed_agents: Annotated[List[str], operator.add]
    errors: Annotated[List[str], operator.add]
    missing_information: Annotated[List[str], operator.add]
    attempted_scenarios: Annotated[List[str], operator.add]
    attempts: Annotated[Dict[str, int], _merge_attempts]

    # --- Collaboration bookkeeping (Step 5) -----------------------------
    tasks: Annotated[List[Dict[str, Any]], operator.add]
    agent_executions: Annotated[List[Dict[str, Any]], operator.add]
    scenario_history: Annotated[List[Dict[str, Any]], operator.add]
    replanning: Annotated[List[Dict[str, Any]], operator.add]
    skipped_agents: Annotated[List[str], operator.add]

    # --- Control -------------------------------------------------------
    step: int
    iteration: int
    scenario_rounds: int
    revision_rounds: int
    next_action: str
    failed_agent: Optional[str]
    status: str
    recommendation: Optional[Dict[str, Any]]

    # --- Collaboration control (Step 5) ---------------------------------
    scenario_screening: Optional[Dict[str, Any]]
    scenario_revision: Optional[Dict[str, Any]]
    replan_rounds: int

    # --- Human approval control (Step 6) --------------------------------
    approval_history: Annotated[List[Dict[str, Any]], operator.add]
    modification_rounds: int
