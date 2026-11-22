"""LangGraph orchestration package.

Three modules make up the Step 4 orchestration layer:

* :mod:`app.orchestration.state` — the shared workflow state, the supervisor's
  decision log and the deterministic final recommendation.
* :mod:`app.orchestration.checkpointing` — the in-memory and PostgreSQL-backed
  checkpointers, plus the libpq URL derivation the Postgres adapter needs.
* :mod:`app.orchestration.workflow` — the compiled supervisor graph: one
  supervisor node, five agent nodes, an approval gate, an error-handling node
  and the terminal node, connected by conditional edges.

Step 5 adds :mod:`app.orchestration.collaboration`, the deterministic
collaboration mechanics behind the graph: task objects, deterministic screening
of a scenario plan, bounded replanning and preserved scenario history.

Step 6 adds :mod:`app.orchestration.approvals`, the deterministic side of the
human-in-the-loop gate: the versioned proposal snapshot a human reviews, the
auditable decision record and the bounded modification loop.
"""

from app.orchestration.approvals import (
    MAX_MODIFICATION_ROUNDS,
    build_modification_revision,
    build_proposal_snapshot,
    build_resume_payload,
    parse_approval_decision,
    proposal_version_of,
)
from app.orchestration.checkpointing import (
    checkpointer_dsn,
    in_memory_checkpointer,
    open_checkpointer,
    postgres_checkpointer,
)
from app.orchestration.collaboration import (
    AGENT_OBJECTIVES,
    AGENT_TOOLS,
    MAX_REPLAN_ROUNDS,
    build_agent_task,
    build_history_entry,
    build_replanning_record,
    build_scenario_revision,
    evaluate_scenario_plan,
    screening_requires_replan,
)
from app.orchestration.state import (
    AGENT_COMPLIANCE,
    AGENT_NODES,
    AGENT_REBALANCING,
    AGENT_REROUTING,
    AGENT_SCENARIO,
    AGENT_SENSING,
    DEFAULT_COMPLIANCE_RULES,
    NODE_APPROVAL_GATE,
    NODE_ERROR,
    NODE_FINALIZE,
    NODE_SUPERVISOR,
    STATUS_NO_COMPLIANT_RECOVERY,
    RecoveryRecommendation,
    RecoveryRequest,
    SupervisorDecision,
    WorkflowState,
)
from app.orchestration.workflow import (
    SupervisorAgents,
    SupervisorWorkflow,
    build_agents,
    build_default_agents,
    build_graph,
    mermaid_diagram,
    pending_interrupt,
    supervisor_runtime,
    thread_config,
)

__all__ = [
    "AGENT_COMPLIANCE",
    "AGENT_NODES",
    "AGENT_OBJECTIVES",
    "AGENT_REBALANCING",
    "AGENT_REROUTING",
    "AGENT_SCENARIO",
    "AGENT_SENSING",
    "AGENT_TOOLS",
    "DEFAULT_COMPLIANCE_RULES",
    "MAX_MODIFICATION_ROUNDS",
    "MAX_REPLAN_ROUNDS",
    "NODE_APPROVAL_GATE",
    "NODE_ERROR",
    "NODE_FINALIZE",
    "NODE_SUPERVISOR",
    "STATUS_NO_COMPLIANT_RECOVERY",
    "RecoveryRecommendation",
    "RecoveryRequest",
    "SupervisorAgents",
    "SupervisorDecision",
    "SupervisorWorkflow",
    "WorkflowState",
    "build_agent_task",
    "build_agents",
    "build_default_agents",
    "build_graph",
    "build_history_entry",
    "build_modification_revision",
    "build_proposal_snapshot",
    "build_replanning_record",
    "build_resume_payload",
    "build_scenario_revision",
    "checkpointer_dsn",
    "evaluate_scenario_plan",
    "in_memory_checkpointer",
    "mermaid_diagram",
    "open_checkpointer",
    "parse_approval_decision",
    "pending_interrupt",
    "postgres_checkpointer",
    "proposal_version_of",
    "screening_requires_replan",
    "supervisor_runtime",
    "thread_config",
]
