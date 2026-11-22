"""LangGraph orchestration package.

Three modules make up the Step 4 orchestration layer:

* :mod:`app.orchestration.state` — the shared workflow state, the supervisor's
  decision log and the deterministic final recommendation.
* :mod:`app.orchestration.checkpointing` — the in-memory and PostgreSQL-backed
  checkpointers, plus the libpq URL derivation the Postgres adapter needs.
* :mod:`app.orchestration.workflow` — the compiled supervisor graph: one
  supervisor node, five agent nodes, an approval gate, an error-handling node
  and the terminal node, connected by conditional edges.

Step 5 (multi-agent collaboration and replanning) builds on this graph rather
than replacing it.
"""

from app.orchestration.checkpointing import (
    checkpointer_dsn,
    in_memory_checkpointer,
    open_checkpointer,
    postgres_checkpointer,
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
    "AGENT_REBALANCING",
    "AGENT_REROUTING",
    "AGENT_SCENARIO",
    "AGENT_SENSING",
    "DEFAULT_COMPLIANCE_RULES",
    "NODE_APPROVAL_GATE",
    "NODE_ERROR",
    "NODE_FINALIZE",
    "NODE_SUPERVISOR",
    "RecoveryRecommendation",
    "RecoveryRequest",
    "SupervisorAgents",
    "SupervisorDecision",
    "SupervisorWorkflow",
    "WorkflowState",
    "build_agents",
    "build_default_agents",
    "build_graph",
    "checkpointer_dsn",
    "in_memory_checkpointer",
    "mermaid_diagram",
    "open_checkpointer",
    "pending_interrupt",
    "postgres_checkpointer",
    "supervisor_runtime",
    "thread_config",
]
