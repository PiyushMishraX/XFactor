"""Structured collaboration protocol for the LangGraph supervisor (Step 5).

Step 4 connected the five agents through shared state. Step 5 makes the *work*
visible and auditable:

* :class:`AgentTask` — the explicit task object the supervisor issues to an
  agent. It names the objective, the reason (which decision selected the agent),
  the tools the agent is expected to use and the inputs it will receive.
* :class:`ToolInvocation` — one *actual* tool call, recorded by the tool
  recording layer while the agent executes. Arguments and outcomes are short,
  JSON-safe summaries; secrets are never recorded.
* :class:`AgentExecution` — one attempt at one task: status, duration, the tool
  calls it made, a deterministic result summary and the gaps it reported.
* :class:`ScenarioEvaluation` / :class:`ScenarioScreening` — the supervisor's
  deterministic evaluation of every recovery alternative, produced by reusing
  the same compliance, budget and approval engines Agent 5 uses.
* :class:`ReplanningRecord` / :class:`ScenarioHistoryEntry` — the feedback loop:
  which alternatives were rejected, why, and the scenario plan that was
  preserved while the revised plan was built.

Nothing here fabricates an interaction. A task exists only when the supervisor
actually selected that node, an execution exists only when the node actually
ran, and a tool invocation is written by the tool itself.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.audit_schemas import AuditVerdict
from app.schemas.scenario_schemas import ScenarioPlan, ScenarioRevision


class ToolCallStatus(str, Enum):
    """Outcome of one tool invocation."""

    OK = "ok"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class ExecutionStatus(str, Enum):
    """Outcome of one agent execution attempt."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolInvocation(BaseModel):
    """One tool call that actually happened during an agent execution."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tool: str = Field(description="Dotted tool name, e.g. 'mapping.get_route'.")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Small, JSON-safe argument summary."
    )
    outcome: str = Field(default="", description="Short description of the result or failure.")
    status: ToolCallStatus = ToolCallStatus.OK
    duration_ms: float = Field(default=0.0, ge=0)
    is_mock: bool = Field(
        default=False, description="True when the tool returned labelled simulated data."
    )


class AgentTask(BaseModel):
    """The structured task object the supervisor issues to one agent."""

    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str
    agent: str = Field(description="One of the AGENT_* identifiers.")
    objective: str = Field(description="What the agent is being asked to produce.")
    reason: str = Field(description="The structured evidence behind the delegation.")
    requested_by: str = Field(default="supervisor")
    step: int = Field(default=0, ge=0, description="Supervisor pass that issued the task.")
    attempt: int = Field(default=1, ge=1, description="1 for the first attempt of this agent.")
    tools: List[str] = Field(
        default_factory=list, description="The tools this agent is expected to use."
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict, description="Small, JSON-safe summary of the task inputs."
    )
    revision: Optional[ScenarioRevision] = Field(
        default=None,
        description="Revision instructions when the task is a scenario re-plan.",
    )


class AgentExecution(BaseModel):
    """The record of one agent execution attempt, including its tool calls."""

    execution_id: str
    task_id: str
    agent: str
    attempt: int = Field(ge=1)
    status: ExecutionStatus
    started_at: datetime
    duration_ms: float = Field(ge=0)
    tool_calls: List[ToolInvocation] = Field(default_factory=list)
    result_summary: str = ""
    findings: List[str] = Field(
        default_factory=list, description="Missing information the execution reported."
    )
    error: str = ""


class ScenarioEvaluation(BaseModel):
    """The supervisor's deterministic evaluation of one recovery alternative."""

    scenario_id: str
    rank: int
    carrier: str
    transport_mode: str
    total_cost_usd: float
    total_days: float
    risk_score: int
    verdict: AuditVerdict = Field(
        description="Derived from compliance, budget and approval validation only."
    )
    is_compliant: bool
    is_within_budget: bool
    requires_approval: bool = False
    approval_level: Optional[str] = None
    violations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommended: bool = False
    reason: str = ""


class ScenarioScreening(BaseModel):
    """Every alternative evaluated for the plan currently on the table."""

    recommended_scenario_id: Optional[str] = None
    recommended_verdict: Optional[AuditVerdict] = None
    scenario_count: int = 0
    evaluations: List[ScenarioEvaluation] = Field(default_factory=list)
    all_rejected: bool = False
    inventory_impact: str = ""
    inventory_can_cover_disruption: Optional[bool] = None
    inventory_shortage_after: Optional[float] = None


class ScenarioHistoryEntry(BaseModel):
    """A previous scenario plan, preserved when the supervisor asks for a revision."""

    round: int = Field(ge=1)
    scenario_ids: List[str] = Field(default_factory=list)
    recommended_scenario_id: Optional[str] = None
    rejected_scenario_ids: List[str] = Field(default_factory=list)
    plan: ScenarioPlan
    evaluations: List[ScenarioEvaluation] = Field(default_factory=list)


class ReplanningRecord(BaseModel):
    """One feedback-loop iteration: what was rejected and what was requested."""

    round: int = Field(ge=1)
    trigger: str = Field(description="'deterministic screening' or 'compliance audit'.")
    rejected_scenario_ids: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    revision: ScenarioRevision
    previous_scenario_ids: List[str] = Field(default_factory=list)


__all__ = [
    "AgentExecution",
    "AgentTask",
    "ExecutionStatus",
    "ReplanningRecord",
    "ScenarioEvaluation",
    "ScenarioHistoryEntry",
    "ScenarioScreening",
    "ToolCallStatus",
    "ToolInvocation",
]
