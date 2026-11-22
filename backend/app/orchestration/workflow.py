"""LangGraph supervisor and orchestration for X FACTOR (Step 4).

This module is the central supervisor described in the roadmap: it connects the
five specialized agents through **actual LangGraph nodes, shared state and
conditional edges**, and it decides which agent runs next from the *validated
structured results* already in the state — never from a conversation transcript.

Graph shape
-----------
``START -> supervisor`` and then, from the supervisor and after every agent, a
conditional edge onto the next node. The supervisor's six dynamic decisions are
evaluated in :func:`_decide`:

1. *Is a logistics analysis required?* — a supply-chain disruption needs a
   lane-level analysis before anything can be proposed.
2. *Is an inventory analysis required?* — only when the caller supplied an
   inventory request on the scenario request.
3. *Are additional scenarios required?* — when severity is high or critical, or
   when more than one shipment is affected, a ranked comparison of alternatives
   is warranted; otherwise a single logistics recommendation is enough.
4. *Does a scenario need revision?* — when the recommended scenario is not
   unconditionally feasible (or fewer than three scenarios could be built) the
   supervisor asks for an independent logistics revision, once, before auditing.
5. *Is compliance validation required?* — every proposal that reaches a
   recommendation is validated by the Compliance & Audit Agent.
6. *Can the workflow proceed to approval?* — a rejected verdict stops the run, a
   verdict that needs a human sign-off is interrupted, and anything else is
   completed.

Honesty notes
-------------
* Nothing here fabricates work. Every node calls a real agent method
  (``assess`` / ``analyse`` / ``plan`` / ``audit``) and stores that method's
  validated Pydantic result in the state as a JSON dictionary, so the whole state
  round-trips through the PostgreSQL checkpointer without depending on
  msgpack-registered classes.
* The decision log is the supervisor's actual reasoning, recorded as
  :class:`~app.orchestration.state.SupervisorDecision` rows. There is no
  simulated dialogue between agents.

Assumption
----------
:class:`~app.agents.scenario_planning.ScenarioPlanningAgent` composites the
Rerouting and Inventory agents internally. The supervisor therefore does **not**
run those two nodes on the scenario path — it lets the scenario node request
them itself, exactly as the agent is designed. The standalone logistics and
inventory nodes are used on the direct path (when no scenario comparison is
warranted) and as the bounded scenario revision. This keeps every agent at
exactly one execution per pass instead of duplicating an analysis.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.agents.compliance_audit import ComplianceAuditAgent
from app.agents.disruption_sensing import DisruptionSensingAgent
from app.agents.inventory_rebalancing import InventoryRebalancingAgent
from app.agents.rerouting_logistics import ReroutingLogisticsAgent
from app.agents.scenario_planning import ScenarioPlanningAgent
from app.config.settings import Settings, get_settings
from app.integrations.base import IntegrationNotConfiguredError
from app.integrations.carriers import CarrierConnector, get_carrier_connector
from app.integrations.mapping import MappingConnector, get_mapping_connector
from app.integrations.sap import SAPConnector, get_sap_connector
from app.orchestration.approvals import (
    MAX_MODIFICATION_ROUNDS,
    build_modification_revision,
    build_proposal_snapshot,
    parse_approval_decision,
)
from app.orchestration.checkpointing import open_checkpointer
from app.orchestration.collaboration import (
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
    NODE_APPROVAL_GATE,
    NODE_ERROR,
    NODE_FINALIZE,
    NODE_SUPERVISOR,
    STATUS_APPROVAL_REJECTED,
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_ITERATION_LIMIT,
    STATUS_NO_ACTION,
    STATUS_NO_COMPLIANT_RECOVERY,
    STATUS_NO_FEASIBLE_RECOVERY,
    STATUS_RUNNING,
    RecoveryRecommendation,
    RecoveryRequest,
    SupervisorDecision,
    WorkflowState,
)
from app.schemas.audit_schemas import AuditReport, AuditRequest, AuditVerdict
from app.schemas.approval_schemas import ApprovalAction, ApprovalDecisionRecord
from app.schemas.collaboration_schemas import (
    AgentExecution,
    AgentTask,
    ExecutionStatus,
    ReplanningRecord,
    ScenarioHistoryEntry,
    ScenarioScreening,
    ToolInvocation,
)
from app.schemas.disruption_schemas import EvidenceItem
from app.schemas.rebalancing_schemas import RebalancingPlan, RebalancingRequest
from app.schemas.rerouting_schemas import ReroutingAnalysis, ReroutingRequest
from app.schemas.scenario_schemas import (
    ScenarioFeasibility,
    ScenarioPlan,
    ScenarioRevision,
)
from app.services.gemini_service import GeminiNotConfiguredError, GeminiService
from app.services.supply_chain_repository import (
    PostgresSupplyChainRepository,
    SupplyChainRepository,
)
from app.tools.base import ToolInputError
from app.tools.compliance import RecoveryProposal
from app.utils.tool_recording import ToolCallRecorder, wrap_connector

logger = logging.getLogger(__name__)

#: How many times one agent may be executed for a single disruption, including
#: the first attempt. A transient failure is therefore retried exactly once.
_MAX_AGENT_ATTEMPTS = 2

#: Failures that a retry cannot fix: a missing API key, an unconfigured
#: integration, malformed tool input or a request that fails validation. These
#: go straight to the terminal state instead of burning a retry.
_NON_RETRYABLE_ERRORS: Tuple[type, ...] = (
    GeminiNotConfiguredError,
    IntegrationNotConfiguredError,
    ToolInputError,
    ValidationError,
)

#: Severities that warrant a ranked comparison of recovery alternatives.
_SEVERITIES_NEEDING_SCENARIOS = {"high", "critical"}

#: Name given to the compiled graph, so a LangGraph checkpoint trace is readable.
GRAPH_NAME = "xfactor_supervisor"


# ---------------------------------------------------------------------------
# Agent bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupervisorAgents:
    """The five specialized agents the supervisor is allowed to delegate to."""

    sensing: DisruptionSensingAgent
    rerouting: ReroutingLogisticsAgent
    rebalancing: InventoryRebalancingAgent
    scenario: ScenarioPlanningAgent
    compliance: ComplianceAuditAgent


def build_agents(
    *,
    gemini: Optional[GeminiService] = None,
    repository: SupplyChainRepository,
    sap: SAPConnector,
    mapping: MappingConnector,
    carriers: CarrierConnector,
) -> SupervisorAgents:
    """Wire the five agents around one shared Gemini service and the connectors.

    The Rerouting and Inventory agents are also handed to the Scenario agent,
    which requests them itself. External connectors are wrapped in recording
    proxies so every call an agent actually makes is observable (Step 5); the
    proxies are transparent, so behaviour is unchanged.
    """
    service = gemini or GeminiService()
    mapping = wrap_connector("mapping", mapping)
    carriers = wrap_connector("carriers", carriers)
    sap = wrap_connector("sap", sap)
    rerouting = ReroutingLogisticsAgent(gemini=service, mapping=mapping, carriers=carriers)
    rebalancing = InventoryRebalancingAgent(gemini=service, sap=sap)
    return SupervisorAgents(
        sensing=DisruptionSensingAgent(gemini=service, repository=repository),
        rerouting=rerouting,
        rebalancing=rebalancing,
        scenario=ScenarioPlanningAgent(
            gemini=service, rerouting=rerouting, rebalancing=rebalancing
        ),
        compliance=ComplianceAuditAgent(gemini=service),
    )


def build_default_agents(
    settings: Optional[Settings] = None,
    *,
    session: Any,
    gemini: Optional[GeminiService] = None,
) -> SupervisorAgents:
    """Wire the agents against the configured connectors and a database session.

    Args:
        settings: Settings used to pick each connector; defaults to the process
            settings.
        session: An open SQLAlchemy session, used for the shipment/supplier
            master data the Sensing agent looks identifiers up in.
        gemini: Gemini service to share; defaults to a new one.
    """
    settings = settings or get_settings()
    return build_agents(
        gemini=gemini,
        repository=PostgresSupplyChainRepository(session),
        sap=get_sap_connector(settings),
        mapping=get_mapping_connector(settings),
        carriers=get_carrier_connector(settings),
    )


# ---------------------------------------------------------------------------
# Request translation
# ---------------------------------------------------------------------------


def _request(state: WorkflowState) -> RecoveryRequest:
    """Re-validate the workflow input held in the state."""
    return RecoveryRequest.model_validate(state["request"])


def _event_id(state: WorkflowState) -> str:
    """The event id of the disruption in flight, for log lines."""
    return str(((state.get("request") or {}).get("scenario_request") or {}).get("event_id") or "")


def _rerouting_request(request: RecoveryRequest) -> ReroutingRequest:
    """Translate the scenario request into Agent 3's input."""
    scenario = request.scenario_request
    return ReroutingRequest(
        disruption_id=scenario.event_id,
        origin=scenario.origin,
        destination=scenario.destination,
        cargo_value_usd=scenario.cargo_value_usd,
        container_count=scenario.container_count,
        current_carrier=scenario.current_carrier,
        current_mode=scenario.transport_mode,
        congestion_days=scenario.congestion_days,
        weather_delay_days=scenario.weather_delay_days,
        tariff_rate_percent=scenario.tariff_rate_percent,
        risk_factors=list(scenario.risk_factors),
    )


def _inventory_request(request: RecoveryRequest) -> RebalancingRequest:
    """Return Agent 4's input, which the caller may or may not have supplied."""
    inventory = request.scenario_request.inventory
    if inventory is None:
        raise ToolInputError(
            "The inventory rebalancing node ran without an inventory request on the "
            "scenario request."
        )
    return inventory


def _audit_request(request: RecoveryRequest, state: WorkflowState) -> AuditRequest:
    """Build the Compliance & Audit Agent's input from the recommendation in state."""
    scenario = request.scenario_request
    facts = _recommendation_facts(state)
    proposal = RecoveryProposal(
        proposal_id=(
            f"{scenario.event_id}:{facts.reference_id}"
            if facts is not None and facts.reference_id
            else scenario.event_id
        ),
        total_cost_usd=facts.total_cost_usd if facts else 0.0,
        origin_country=request.origin_country,
        destination_country=request.destination_country,
        transit_countries=tuple(request.transit_countries),
        supplier_id=request.supplier_id,
        carrier=facts.carrier if facts else "",
        carrier_reliability=facts.carrier_reliability if facts else 1.0,
        estimated_lead_time_days=facts.total_days if facts else 0.0,
        certifications=tuple(request.certifications),
    )
    transferred = (state.get("rebalancing") or {}).get("total_transferred_units")
    return AuditRequest(
        proposal=proposal,
        applicable_rules=list(request.applicable_rules),
        available_budget_usd=scenario.available_budget_usd,
        action_type="Recovery execution",
        shipment_value_usd=scenario.cargo_value_usd,
        inventory_transfer_units=float(request.inventory_transfer_units or transferred or 0.0),
        supplier_risk_tier=request.supplier_risk_tier,
        is_high_impact_reroute=request.is_high_impact_reroute,
        approval_policy=request.approval_policy,
    )


# ---------------------------------------------------------------------------
# The recommendation currently on the table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RecommendationFacts:
    """The deterministic numbers behind whichever recommendation exists."""

    source: str
    reference_id: str
    carrier: str
    transport_mode: str
    total_cost_usd: float
    total_days: float
    carrier_reliability: float
    scenario_id: Optional[str] = None
    route_id: Optional[str] = None


def _recommendation_facts(state: WorkflowState) -> Optional[_RecommendationFacts]:
    """Return the recommended scenario or route, or ``None`` when there is none."""
    plan = state.get("scenario_plan")
    scenarios = (plan or {}).get("scenarios") or []
    if plan and scenarios:
        chosen = next(
            (
                item
                for item in scenarios
                if item.get("scenario_id") == plan.get("recommended_scenario_id")
            ),
            scenarios[0],
        )
        return _RecommendationFacts(
            source="scenario",
            reference_id=str(chosen.get("scenario_id") or ""),
            carrier=str(chosen.get("carrier") or ""),
            transport_mode=str(chosen.get("transport_mode") or ""),
            total_cost_usd=float(chosen.get("total_cost_usd") or 0.0),
            total_days=float(chosen.get("total_days") or 0.0),
            carrier_reliability=float(chosen.get("carrier_reliability") or 0.0),
            scenario_id=str(chosen.get("scenario_id") or "") or None,
        )

    analysis = state.get("rerouting")
    routes = (analysis or {}).get("ranked_routes") or []
    if analysis and routes:
        chosen = next(
            (
                item
                for item in routes
                if item.get("route_id") == analysis.get("recommended_route_id")
            ),
            routes[0],
        )
        return _RecommendationFacts(
            source="route",
            reference_id=str(chosen.get("route_id") or ""),
            carrier=str(chosen.get("carrier") or ""),
            transport_mode=str(chosen.get("transport_mode") or ""),
            total_cost_usd=float(chosen.get("total_cost_usd") or 0.0),
            total_days=float(chosen.get("total_days") or 0.0),
            carrier_reliability=float(chosen.get("carrier_reliability") or 0.0),
            route_id=str(chosen.get("route_id") or "") or None,
        )
    return None


# ---------------------------------------------------------------------------
# Agent nodes
# ---------------------------------------------------------------------------


def _gaps(result: Any) -> List[str]:
    """The result's own missing-information list, as plain strings."""
    return [str(item) for item in (getattr(result, "missing_information", None) or [])]


def _extras(result: Any) -> Dict[str, Any]:
    """Bookkeeping contributed by a specific agent result."""
    if isinstance(result, ScenarioPlan):
        return {
            "attempted_scenarios": [
                scenario.scenario_id for scenario in result.scenarios if scenario.scenario_id
            ],
            "scenario_rounds": 1,
        }
    return {}


def _failure(agent_name: str, exc: Exception) -> Dict[str, Any]:
    """Turn an agent exception into state the error node can act on."""
    message = f"{agent_name}: {type(exc).__name__}: {exc}"
    retryable = not isinstance(exc, _NON_RETRYABLE_ERRORS)
    logger.warning("Agent %s failed (retryable=%s): %s", agent_name, retryable, exc)
    update: Dict[str, Any] = {
        "errors": [message],
        "failed_agent": agent_name,
        "next_action": NODE_ERROR if retryable else NODE_FINALIZE,
    }
    if not retryable:
        update["status"] = STATUS_FAILED
    return update


def _last_decision_reason(state: WorkflowState, agent_name: str) -> str:
    """The supervisor's recorded reason for the delegation now executing."""
    for entry in reversed(state.get("decisions") or []):
        if entry.get("action") == agent_name:
            return str(entry.get("reason") or "")
    return f"The supervisor selected {agent_name} from the validated workflow state."


def _state_revision(state: WorkflowState) -> Optional[ScenarioRevision]:
    """The pending scenario revision, re-validated from the state."""
    payload = state.get("scenario_revision")
    return ScenarioRevision.model_validate(payload) if payload else None


def _next_attempt(state: WorkflowState, agent_name: str) -> int:
    """The ordinal of the task about to be issued to ``agent_name``."""
    issued = sum(1 for task in (state.get("tasks") or []) if task.get("agent") == agent_name)
    return issued + 1


def _execution(
    *,
    task: AgentTask,
    status: ExecutionStatus,
    started_at: datetime,
    started: float,
    recorder: ToolCallRecorder,
    result_summary: str,
    findings: List[str],
    error: str = "",
) -> AgentExecution:
    """Build the execution record from what actually happened."""
    return AgentExecution(
        execution_id=f"exec-{task.task_id}",
        task_id=task.task_id,
        agent=task.agent,
        attempt=task.attempt,
        status=status,
        started_at=started_at,
        duration_ms=round(max(0.0, (perf_counter() - started) * 1000.0), 3),
        tool_calls=recorder.calls,
        result_summary=result_summary,
        findings=list(findings),
        error=error,
    )


def _skipped_update(
    *,
    task: AgentTask,
    started_at: datetime,
    started: float,
    recorder: ToolCallRecorder,
    exc: IntegrationNotConfiguredError,
) -> Dict[str, Any]:
    """Degrade gracefully when an agent's optional integration is unavailable."""
    execution = _execution(
        task=task,
        status=ExecutionStatus.SKIPPED,
        started_at=started_at,
        started=started,
        recorder=recorder,
        result_summary="Task skipped: the integration it needs is not configured.",
        findings=[],
        error=f"{type(exc).__name__}: {exc}",
    )
    logger.warning("Skipping %s task %s: %s", task.agent, task.task_id, exc)
    return {
        "tasks": [task.model_dump(mode="json")],
        "agent_executions": [execution.model_dump(mode="json")],
        "skipped_agents": [task.agent],
        "missing_information": [
            f"The {task.agent} task was skipped because its integration is unavailable: {exc}"
        ],
        "next_action": NODE_SUPERVISOR,
        "failed_agent": None,
    }


def _screening_update(
    state: WorkflowState,
    request: RecoveryRequest,
    plan: ScenarioPlan,
) -> Dict[str, Any]:
    """Evaluate the plan deterministically and open the feedback loop if needed."""
    transferred = float((state.get("rebalancing") or {}).get("total_transferred_units") or 0.0)
    screening = evaluate_scenario_plan(
        request=request, plan=plan, inventory_transfer_units=transferred
    )
    update: Dict[str, Any] = {
        "scenario_screening": screening.model_dump(mode="json"),
        "scenario_revision": None,
    }

    if plan.scenarios and not screening_requires_replan(screening):
        return update

    if not plan.scenarios:
        if state.get("scenario_revision"):
            update["status"] = STATUS_NO_COMPLIANT_RECOVERY
            update["next_action"] = NODE_FINALIZE
        return update

    used = int(state.get("replan_rounds") or 0)
    if used >= MAX_REPLAN_ROUNDS:
        update["status"] = STATUS_NO_COMPLIANT_RECOVERY
        update["next_action"] = NODE_FINALIZE
        return update

    previous = _state_revision(state)
    round_number = used + 1
    revision = build_scenario_revision(
        round_number=round_number,
        evaluations=screening.evaluations,
        previous_rejected=previous.rejected_scenario_ids if previous else (),
    )
    rejected_now = [
        item.scenario_id
        for item in screening.evaluations
        if item.verdict is AuditVerdict.REJECTED
    ]
    history = build_history_entry(
        round_number=round_number,
        plan=plan,
        evaluations=screening.evaluations,
        rejected_scenario_ids=rejected_now,
    )
    record = build_replanning_record(
        round_number=round_number,
        revision=revision,
        previous_scenario_ids=[item.scenario_id for item in plan.scenarios],
    )
    logger.info(
        "Screening rejected %s; requesting scenario revision round %s",
        rejected_now,
        round_number,
    )
    update.update(
        {
            "scenario_plan": None,
            "scenario_revision": revision.model_dump(mode="json"),
            "scenario_history": [history.model_dump(mode="json")],
            "replanning": [record.model_dump(mode="json")],
            "replan_rounds": round_number,
            "next_action": NODE_SUPERVISOR,
        }
    )
    return update


def _agent_node(
    agent_name: str,
    output_key: str,
    run: Callable[[WorkflowState], Any],
    summarise: Callable[[Any], str],
) -> Callable[[WorkflowState], Dict[str, Any]]:
    """Wrap one agent method as a LangGraph node.

    Before the agent runs, the node issues a real :class:`AgentTask` carrying the
    supervisor's recorded reason. While it runs, a tool recorder captures every
    tool invocation the agent actually makes. On success the validated result and
    the execution record are stored as JSON; on failure the node routes to the
    retry node, or straight to the terminal state when a retry cannot help.
    """

    def node(state: WorkflowState) -> Dict[str, Any]:
        request = _request(state)
        revision = _state_revision(state) if agent_name == AGENT_SCENARIO else None
        task = build_agent_task(
            agent=agent_name,
            request=request,
            reason=_last_decision_reason(state, agent_name),
            step=int(state.get("step") or 0),
            attempt=_next_attempt(state, agent_name),
            revision=revision,
        )
        recorder = ToolCallRecorder()
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        try:
            with recorder.activate():
                result = run(state)
        except IntegrationNotConfiguredError as exc:
            if agent_name == AGENT_REBALANCING:
                return _skipped_update(
                    task=task,
                    started_at=started_at,
                    started=started,
                    recorder=recorder,
                    exc=exc,
                )
            failure = _failure(agent_name, exc)
            execution = _execution(
                task=task,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                started=started,
                recorder=recorder,
                result_summary="Execution failed.",
                findings=[],
                error=f"{type(exc).__name__}: {exc}",
            )
            failure.update(
                {
                    "tasks": [task.model_dump(mode="json")],
                    "agent_executions": [execution.model_dump(mode="json")],
                }
            )
            return failure
        except Exception as exc:  # noqa: BLE001 - the error node owns the policy
            failure = _failure(agent_name, exc)
            execution = _execution(
                task=task,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                started=started,
                recorder=recorder,
                result_summary="Execution failed.",
                findings=[],
                error=f"{type(exc).__name__}: {exc}",
            )
            failure.update(
                {
                    "tasks": [task.model_dump(mode="json")],
                    "agent_executions": [execution.model_dump(mode="json")],
                }
            )
            return failure

        execution = _execution(
            task=task,
            status=ExecutionStatus.COMPLETED,
            started_at=started_at,
            started=started,
            recorder=recorder,
            result_summary=summarise(result),
            findings=_gaps(result),
        )
        update: Dict[str, Any] = {
            output_key: result.model_dump(mode="json"),
            "completed_agents": [agent_name],
            "missing_information": _gaps(result),
            "next_action": NODE_SUPERVISOR,
            "failed_agent": None,
            "tasks": [task.model_dump(mode="json")],
            "agent_executions": [execution.model_dump(mode="json")],
        }
        update.update(_extras(result))
        if isinstance(result, ScenarioPlan):
            update.update(_screening_update(state, request, result))
        logger.info("Agent %s completed for event %s", agent_name, _event_id(state))
        return update

    node.__name__ = f"{agent_name}_node"
    return node


def build_agent_nodes(
    agents: SupervisorAgents,
) -> Dict[str, Callable[[WorkflowState], Dict[str, Any]]]:
    """Wrap the five agents as the five graph nodes."""
    return {
        AGENT_SENSING: _agent_node(
            AGENT_SENSING,
            "assessment",
            lambda state: agents.sensing.assess(_request(state).disruption_report),
            lambda result: (
                f"{result.event_id}: severity {result.severity.value}, "
                f"{len(result.affected_shipments)} linked shipment(s)"
            ),
        ),
        AGENT_REROUTING: _agent_node(
            AGENT_REROUTING,
            "rerouting",
            lambda state: agents.rerouting.analyse(_rerouting_request(_request(state))),
            lambda result: (
                f"{len(result.ranked_routes)} route(s), recommended "
                f"{result.recommended_route_id or 'none'}"
            ),
        ),
        AGENT_REBALANCING: _agent_node(
            AGENT_REBALANCING,
            "rebalancing",
            lambda state: agents.rebalancing.plan(_inventory_request(_request(state))),
            lambda result: (
                f"shortage {result.shortage_before} -> {result.shortage_after} unit(s), "
                f"{len(result.transfer_recommendations)} transfer(s)"
            ),
        ),
        AGENT_SCENARIO: _agent_node(
            AGENT_SCENARIO,
            "scenario_plan",
            lambda state: agents.scenario.plan(
                _request(state).scenario_request, _state_revision(state)
            ),
            lambda result: (
                f"{len(result.scenarios)} scenario(s), recommended "
                f"{result.recommended_scenario_id or 'none'}"
                + (f", revision {result.revision_round}" if result.revision_round else "")
            ),
        ),
        AGENT_COMPLIANCE: _agent_node(
            AGENT_COMPLIANCE,
            "audit_report",
            lambda state: agents.compliance.audit(_audit_request(_request(state), state)),
            lambda result: (
                f"verdict {result.verdict.value}, {len(result.violations)} violation(s)"
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Supervisor node
# ---------------------------------------------------------------------------


def _scenarios_required(request: RecoveryRequest, assessment: Dict[str, Any]) -> bool:
    """Whether the decision warrants a ranked comparison of alternatives."""
    scenario = request.scenario_request
    severity = (scenario.severity or str(assessment.get("severity") or "")).strip().lower()
    if severity in _SEVERITIES_NEEDING_SCENARIOS:
        return True
    return len(assessment.get("affected_shipments") or []) > 1


def _scenario_needs_revision(plan: Dict[str, Any]) -> bool:
    """Whether the scenario plan left room for an independent logistics revision."""
    scenarios = plan.get("scenarios") or []
    if len(scenarios) < 3:
        return True
    recommended = next(
        (
            item
            for item in scenarios
            if item.get("scenario_id") == plan.get("recommended_scenario_id")
        ),
        scenarios[0],
    )
    return str(recommended.get("feasibility") or "") != ScenarioFeasibility.FEASIBLE.value


def _screening_passed(state: WorkflowState) -> bool:
    """Whether the last deterministic screening found a compliant recommendation."""
    verdict = (state.get("scenario_screening") or {}).get("recommended_verdict")
    return bool(verdict) and str(verdict) != AuditVerdict.REJECTED.value


def _decide(state: WorkflowState) -> Tuple[str, str, Optional[str]]:
    """The supervisor's routing decision, as (next node, reason, status).

    Only validated structured results are read. Every branch states *why* it
    chose the node it chose, so the decision log explains the run afterwards.
    """
    request = _request(state)
    scenario = request.scenario_request
    assessment = state.get("assessment")

    if assessment is None:
        return AGENT_SENSING, "No validated disruption assessment exists yet.", None

    if not assessment.get("is_supply_chain_disruption"):
        return (
            NODE_FINALIZE,
            "The report was assessed as not being a supply-chain disruption.",
            STATUS_NO_ACTION,
        )

    required = _scenarios_required(request, assessment)
    plan = state.get("scenario_plan")
    rerouting = state.get("rerouting")
    rebalancing = state.get("rebalancing")
    skipped = state.get("skipped_agents") or []

    # 3a. Did deterministic screening reject the last plan, or a human ask for changes?
    revision = _state_revision(state)
    if revision is not None and plan is None:
        if revision.feedback.startswith("Human review requested modifications"):
            reason = (
                f"Human review requested modifications, so the supervisor requests "
                f"scenario revision round {revision.round} with that feedback before "
                f"re-auditing."
            )
        else:
            reason = (
                f"Deterministic screening rejected "
                f"{', '.join(revision.rejected_scenario_ids) or 'the previous recommendation'}, "
                f"so the supervisor requests revision round {revision.round} excluding those "
                f"alternatives before auditing."
            )
        return AGENT_SCENARIO, reason, None

    # 3. Are additional scenarios required?
    if required and plan is None:
        return (
            AGENT_SCENARIO,
            "Severity and/or the number of affected shipments warrant a ranked "
            "comparison of recovery alternatives.",
            None,
        )

    # 1. Is a logistics analysis required?
    if not required and rerouting is None:
        return (
            AGENT_REROUTING,
            "A supply-chain disruption needs a lane-level logistics analysis before a "
            "recovery route can be proposed.",
            None,
        )

    # 2. Is an inventory analysis required?
    if (
        not required
        and scenario.inventory is not None
        and rebalancing is None
        and AGENT_REBALANCING not in skipped
    ):
        return (
            AGENT_REBALANCING,
            "The caller supplied an inventory request, so a rebalancing analysis is required.",
            None,
        )

    # 4. Does a scenario need an independent logistics revision?
    if plan is not None and _scenario_needs_revision(plan) and not _screening_passed(state):
        if rerouting is None and int(state.get("revision_rounds") or 0) < 1:
            return (
                AGENT_REROUTING,
                "The recommended scenario is not unconditionally feasible (or fewer than "
                "three alternatives exist), so the supervisor requests one independent "
                "logistics revision before auditing.",
                None,
            )

    # Is there anything left to recommend?
    if _recommendation_facts(state) is None:
        return (
            NODE_FINALIZE,
            "No recovery route or scenario could be recommended from the available data.",
            STATUS_NO_FEASIBLE_RECOVERY,
        )

    # 5. Is compliance validation required?
    audit = state.get("audit_report")
    if audit is None:
        return (
            AGENT_COMPLIANCE,
            "A recovery recommendation exists and must be validated before it can proceed.",
            None,
        )

    # 6. Can the workflow proceed to approval?
    if str(audit.get("verdict") or "") == AuditVerdict.REJECTED.value:
        return (
            NODE_FINALIZE,
            "Deterministic compliance validation rejected the proposal.",
            STATUS_APPROVAL_REJECTED,
        )
    if (audit.get("approval") or {}).get("requires_approval"):
        return (
            NODE_APPROVAL_GATE,
            "Compliance validation passed but requires a human sign-off before execution.",
            STATUS_AWAITING_APPROVAL,
        )
    return (
        NODE_FINALIZE,
        "The proposal is compliant and within budget and needs no human approval.",
        STATUS_COMPLETED,
    )


def build_supervisor_node(
    settings: Settings,
) -> Callable[[WorkflowState], Dict[str, Any]]:
    """Build the supervisor node, bounded by ``LANGGRAPH_MAX_ITERATIONS``."""
    max_steps = max(2, int(settings.LANGGRAPH_MAX_ITERATIONS)) * len(AGENT_NODES)

    def supervisor(state: WorkflowState) -> Dict[str, Any]:
        step = int(state.get("step") or 0) + 1
        action, reason, status = _decide(state)

        if step > max_steps:
            action = NODE_FINALIZE
            reason = (
                f"The supervisor reached its safety bound of {max_steps} pass(es) without "
                f"settling, so the workflow is stopped."
            )
            status = STATUS_ITERATION_LIMIT

        revision_rounds = int(state.get("revision_rounds") or 0)
        if state.get("scenario_plan") is not None and action == AGENT_REROUTING:
            revision_rounds += 1

        update: Dict[str, Any] = {
            "step": step,
            "iteration": len(state.get("completed_agents") or []),
            "revision_rounds": revision_rounds,
            "decisions": [
                SupervisorDecision(step=step, action=action, reason=reason).model_dump(mode="json")
            ],
            "next_action": action,
            "failed_agent": None,
        }
        if status is not None:
            update["status"] = status
        logger.info("Supervisor pass %s -> %s (%s)", step, action, reason)
        return update

    return supervisor


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


def build_approval_gate() -> Callable[[WorkflowState], Dict[str, Any]]:
    """Build the interrupt node that pauses the workflow for a human decision.

    The node publishes the proposal version so the approval API can bind a
    decision to the exact plan the reviewer saw. On resume it accepts the Step 6
    payload (action + authenticated approver identity) as well as the simpler
    Step 4 payload, and it supports a bounded "request modifications" loop that
    sends the plan back to the Scenario agent with the reviewer's feedback.
    """

    def approval_gate(state: WorkflowState) -> Dict[str, Any]:
        audit = AuditReport.model_validate(state["audit_report"])
        snapshot = build_proposal_snapshot("", state)
        proposal_version = snapshot.proposal_version if snapshot is not None else ""
        decision = interrupt(
            {
                "type": "approval_required",
                "proposal_id": audit.proposal_id,
                "proposal_version": proposal_version,
                "verdict": audit.verdict.value,
                "approval_level": audit.approval.approval_level,
                "reasons": list(audit.approval.reasons),
                "is_compliant": audit.is_compliant,
                "is_within_budget": audit.is_within_budget,
                "violations": [finding.detail for finding in audit.violations],
                "question": (
                    "Approve this recovery proposal, reject it, or request modifications. "
                    "Only an authenticated approver may decide, and the workflow resumes "
                    "from its saved checkpoint with that decision."
                ),
            }
        )
        record = parse_approval_decision(decision)
        update: Dict[str, Any] = {
            "approval": {
                "approved": record.approved,
                "action": record.action.value,
                "comment": record.comment,
                "approval_level": audit.approval.approval_level,
                "decided_by": record.approver_id or "human",
                "approver_role": record.approver_role,
                "proposal_version": record.proposal_version or proposal_version,
                "decided_at": record.decided_at.isoformat(),
            },
            "approval_history": [record.model_dump(mode="json")],
            "next_action": NODE_FINALIZE,
        }

        if record.action is ApprovalAction.APPROVE:
            update["status"] = STATUS_COMPLETED
            logger.info("Approval granted for %s", audit.proposal_id)
            return update

        if record.action is ApprovalAction.REJECT:
            update["status"] = STATUS_APPROVAL_REJECTED
            update["errors"] = [
                f"Approval rejected for {audit.proposal_id}: "
                f"{record.comment or 'no reason given'}"
            ]
            logger.info("Approval rejected for %s", audit.proposal_id)
            return update

        # Request modifications: reconsider, but only within the bounded budget.
        used = int(state.get("modification_rounds") or 0)
        if used >= MAX_MODIFICATION_ROUNDS:
            update["status"] = STATUS_APPROVAL_REJECTED
            update["errors"] = [
                f"Reviewer requested modifications for {audit.proposal_id}, but the "
                f"workflow already used its {MAX_MODIFICATION_ROUNDS} reconsideration "
                f"round(s); the workflow is closed."
            ]
            logger.info(
                "Modification limit reached for %s; closing the workflow", audit.proposal_id
            )
            return update

        round_number = used + 1
        revision = build_modification_revision(
            state, round_number=round_number, comment=record.comment
        )
        logger.info(
            "Reviewer requested modifications for %s; requesting scenario revision round %s",
            audit.proposal_id,
            round_number,
        )
        update.update(
            {
                "status": STATUS_RUNNING,
                "next_action": AGENT_SCENARIO,
                "modification_rounds": round_number,
                "scenario_revision": revision.model_dump(mode="json"),
                "scenario_plan": None,
                "scenario_screening": None,
                "audit_report": None,
                "rerouting": None,
                "rebalancing": None,
                "decisions": [
                    SupervisorDecision(
                        step=int(state.get("step") or 0),
                        action=AGENT_SCENARIO,
                        reason=(
                            f"Human review requested modifications for "
                            f"{audit.proposal_id}, so the supervisor requests scenario "
                            f"revision round {round_number} with the reviewer's feedback "
                            f"before re-auditing."
                        ),
                    ).model_dump(mode="json")
                ],
            }
        )
        return update

    return approval_gate


# ---------------------------------------------------------------------------
# Error handling node
# ---------------------------------------------------------------------------


def build_error_handler() -> Callable[[WorkflowState], Dict[str, Any]]:
    """Build the retry node for transient agent failures."""

    def error_handler(state: WorkflowState) -> Dict[str, Any]:
        agent = state.get("failed_agent")
        if agent not in AGENT_NODES:
            return {"next_action": NODE_FINALIZE, "status": STATUS_FAILED}

        used = int((state.get("attempts") or {}).get(agent, 0))
        if used + 1 < _MAX_AGENT_ATTEMPTS:
            logger.info("Retrying agent %s (attempt %s)", agent, used + 2)
            return {
                "attempts": {agent: used + 1},
                "next_action": agent,
                "failed_agent": None,
                "decisions": [
                    SupervisorDecision(
                        step=int(state.get("step") or 0),
                        action=agent,
                        reason=f"Retrying {agent} after a transient failure (attempt {used + 2}).",
                    ).model_dump(mode="json")
                ],
            }

        logger.warning("Agent %s exhausted its retries", agent)
        return {
            "next_action": NODE_FINALIZE,
            "status": STATUS_FAILED,
            "failed_agent": None,
        }

    return error_handler


# ---------------------------------------------------------------------------
# Finalize node
# ---------------------------------------------------------------------------


def _money(value: float) -> str:
    return f"{value:,.2f} USD"


def _days(value: float) -> str:
    return f"{value:g} day(s)"


def _outcome_text(
    status: str,
    request: RecoveryRequest,
    state: WorkflowState,
    facts: Optional[_RecommendationFacts],
) -> Tuple[str, str]:
    """Deterministic headline and summary for the finished workflow."""
    event_id = request.scenario_request.event_id
    assessment = state.get("assessment") or {}
    audit = state.get("audit_report") or {}
    approval = state.get("approval") or {}
    gaps = state.get("missing_information") or []
    errors = state.get("errors") or []

    if status == STATUS_NO_ACTION:
        return (
            f"{event_id}: no supply-chain action required",
            "The Disruption Sensing Agent assessed the report as unrelated to the supply "
            "chain, so the supervisor stopped without delegating further.",
        )

    if status == STATUS_NO_FEASIBLE_RECOVERY:
        detail = f" {len(gaps)} information gap(s) were recorded." if gaps else ""
        return (
            f"{event_id}: no feasible recovery could be recommended",
            "Neither the logistics analysis nor the scenario comparison produced a route "
            f"that could be recommended.{detail}",
        )

    if status == STATUS_NO_COMPLIANT_RECOVERY:
        rounds = int(state.get("replan_rounds") or 0)
        detail = (
            f" after {rounds} replanning round(s)" if rounds else ""
        )
        return (
            f"{event_id}: no compliant recovery available",
            "Every recovery alternative was rejected by deterministic compliance, budget or "
            f"approval validation{detail}.",
        )

    if status == STATUS_ITERATION_LIMIT:
        return (
            f"{event_id}: supervisor stopped at its iteration bound",
            "The workflow did not settle within the configured number of supervisor "
            "passes, so it was stopped rather than allowed to loop.",
        )

    if status == STATUS_FAILED:
        first = errors[0] if errors else "an unspecified error"
        return (
            f"{event_id}: supervisor workflow failed",
            f"The workflow stopped after an agent could not complete: {first}",
        )

    if facts is None:
        return (
            f"{event_id}: workflow finished without a recommendation",
            f"The workflow ended with status '{status}'.",
        )

    target = (
        f"scenario {facts.scenario_id}" if facts.scenario_id else f"route {facts.route_id}"
    )
    headline = (
        f"{event_id}: {target} recommended via {facts.carrier or 'the incumbent carrier'}"
    )
    body = (
        f"Recommended {target} — carrier {facts.carrier or 'unspecified'}, mode "
        f"{facts.transport_mode or 'unspecified'}, cost {_money(facts.total_cost_usd)}, "
        f"{_days(facts.total_days)} transit."
    )

    if status == STATUS_APPROVAL_REJECTED:
        comment = approval.get("comment") or ""
        return (
            f"{event_id}: recovery rejected",
            f"{body} The deterministic audit rejected the proposal or a human rejected it "
            f"at the approval gate.{f' Reason: {comment}' if comment else ''}",
        )
    if status == STATUS_AWAITING_APPROVAL:
        return (
            f"{event_id}: recovery awaiting human approval",
            f"{body} The audit verdict requires sign-off at "
            f"{audit.get('approval', {}).get('approval_level') or 'the approval gate'} level.",
        )
    if audit:
        return (
            f"{event_id}: recovery approved for execution",
            f"{body} Deterministic validation returned '{audit.get('verdict')}' and the "
            f"proposal needs no human approval.",
        )
    return headline, body


def finalize(state: WorkflowState) -> Dict[str, Any]:
    """Assemble the deterministic final answer from the state."""
    request = _request(state)
    status = state.get("status") or STATUS_FAILED
    facts = _recommendation_facts(state)
    audit = state.get("audit_report") or {}
    plan = state.get("scenario_plan") or {}
    approval = state.get("approval") or {}

    verdict: Optional[AuditVerdict] = None
    if audit:
        try:
            verdict = AuditVerdict(audit.get("verdict"))
        except ValueError:
            verdict = None

    headline, summary = _outcome_text(status, request, state, facts)
    delegated = list(state.get("completed_agents") or [])
    executions = [
        AgentExecution.model_validate(item) for item in (state.get("agent_executions") or [])
    ]
    screening_payload = state.get("scenario_screening")
    snapshot = build_proposal_snapshot("", state)
    recommendation = RecoveryRecommendation(
        event_id=request.disruption_report.derive_event_id(),
        status=status,
        headline=headline,
        summary=summary,
        recommended_scenario_id=facts.scenario_id if facts else plan.get("recommended_scenario_id"),
        recommended_carrier=facts.carrier if facts else None,
        recommended_route_id=facts.route_id if facts else None,
        audit_verdict=verdict,
        requires_approval=bool((audit.get("approval") or {}).get("requires_approval")),
        approval_level=(audit.get("approval") or {}).get("approval_level"),
        delegated_agents=delegated,
        decision_log=[
            SupervisorDecision.model_validate(item) for item in (state.get("decisions") or [])
        ],
        missing_information=_deduplicate(state.get("missing_information") or []),
        errors=list(state.get("errors") or []),
        evidence=_collect_evidence(state),
        iterations=len(delegated),
        tasks=[
            AgentTask.model_validate(item) for item in (state.get("tasks") or [])
        ],
        agent_executions=executions,
        tool_calls=[
            invocation
            for execution in executions
            for invocation in execution.tool_calls
        ],
        scenario_screening=(
            ScenarioScreening.model_validate(screening_payload)
            if screening_payload
            else None
        ),
        scenario_history=[
            ScenarioHistoryEntry.model_validate(item)
            for item in (state.get("scenario_history") or [])
        ],
        replanning=[
            ReplanningRecord.model_validate(item)
            for item in (state.get("replanning") or [])
        ],
        replanning_rounds=int(state.get("replan_rounds") or 0),
        skipped_agents=list(dict.fromkeys(state.get("skipped_agents") or [])),
        proposal_version=snapshot.proposal_version if snapshot is not None else None,
        approval_history=[
            ApprovalDecisionRecord.model_validate(item)
            for item in (state.get("approval_history") or [])
        ],
    )
    logger.info("Workflow finished for %s with status %s", recommendation.event_id, status)
    return {"recommendation": recommendation.model_dump(mode="json"), "status": status}


def _collect_evidence(state: WorkflowState) -> List[EvidenceItem]:
    """Gather every evidence row the agents produced, de-duplicated."""
    items: List[EvidenceItem] = []
    seen: set[Tuple[str, str]] = set()
    for key in ("assessment", "rerouting", "rebalancing", "scenario_plan"):
        payload = state.get(key) or {}
        for raw in payload.get("evidence") or []:
            try:
                item = EvidenceItem.model_validate(raw)
            except ValidationError:
                continue
            marker = (item.source, item.description)
            if marker in seen:
                continue
            seen.add(marker)
            items.append(item)
    return items


def _deduplicate(values: List[str]) -> List[str]:
    """Drop blanks and duplicates while preserving order."""
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _route_next(state: WorkflowState) -> str:
    """Conditional-edge selector: follow whatever the last node decided."""
    return state.get("next_action") or NODE_SUPERVISOR


def build_graph(
    *,
    agents: SupervisorAgents,
    settings: Optional[Settings] = None,
    checkpointer: Any = None,
) -> Any:
    """Compile the supervisor graph.

    Args:
        agents: The five agents every node delegates to.
        settings: Settings supplying ``LANGGRAPH_MAX_ITERATIONS``.
        checkpointer: A LangGraph checkpointer. Required for workflow
            interruption and resume; without one the graph runs to completion in
            a single pass and the approval gate cannot pause.
    """
    settings = settings or get_settings()
    builder: StateGraph = StateGraph(WorkflowState)

    builder.add_node(NODE_SUPERVISOR, build_supervisor_node(settings))
    for name, node in build_agent_nodes(agents).items():
        builder.add_node(name, node)
    builder.add_node(NODE_APPROVAL_GATE, build_approval_gate())
    builder.add_node(NODE_ERROR, build_error_handler())
    builder.add_node(NODE_FINALIZE, finalize)

    builder.add_edge(START, NODE_SUPERVISOR)
    builder.add_conditional_edges(
        NODE_SUPERVISOR, _route_next, [*AGENT_NODES, NODE_APPROVAL_GATE, NODE_FINALIZE]
    )
    for name in AGENT_NODES:
        builder.add_conditional_edges(name, _route_next, [NODE_SUPERVISOR, NODE_ERROR, NODE_FINALIZE])
    builder.add_conditional_edges(NODE_ERROR, _route_next, [*AGENT_NODES, NODE_FINALIZE])
    # An approval may close the workflow or send the plan back for modification.
    builder.add_conditional_edges(
        NODE_APPROVAL_GATE, _route_next, [AGENT_SCENARIO, NODE_FINALIZE]
    )
    builder.add_edge(NODE_FINALIZE, END)

    logger.info("Compiled the X FACTOR supervisor graph (%s node(s)).", len(builder.nodes))
    return builder.compile(checkpointer=checkpointer, name=GRAPH_NAME)


def mermaid_diagram(graph: Any) -> str:
    """Return the Mermaid source LangGraph derives from a compiled graph."""
    return graph.get_graph().draw_mermaid()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def thread_config(thread_id: str) -> Dict[str, Any]:
    """LangGraph config for one conversation thread."""
    return {"configurable": {"thread_id": thread_id}}


class SupervisorWorkflow:
    """Thin wrapper around a compiled supervisor graph.

    It only translates Pydantic requests into graph input and back out again; all
    orchestration lives in the graph itself.
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    @property
    def graph(self) -> Any:
        """The compiled LangGraph graph."""
        return self._graph

    def invoke(self, request: RecoveryRequest, *, thread_id: str) -> Dict[str, Any]:
        """Start a workflow. Returns the state, or an ``__interrupt__`` payload."""
        logger.info(
            "Invoking the supervisor for thread %s (event %s)",
            thread_id,
            request.scenario_request.event_id,
        )
        return self._graph.invoke(
            {"request": request.model_dump(mode="json")}, thread_config(thread_id)
        )

    def resume(self, decision: Any, *, thread_id: str) -> Dict[str, Any]:
        """Resume an interrupted workflow from its saved checkpoint."""
        logger.info("Resuming the supervisor for thread %s", thread_id)
        return self._graph.invoke(Command(resume=decision), thread_config(thread_id))

    def snapshot(self, *, thread_id: str) -> Any:
        """The saved state snapshot for a thread."""
        return self._graph.get_state(thread_config(thread_id))

    def mermaid(self) -> str:
        """The Mermaid source for the compiled graph."""
        return mermaid_diagram(self._graph)


def pending_interrupt(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The interrupt payload in a paused run, or ``None`` when the run finished."""
    interrupts = (result or {}).get("__interrupt__") or ()
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", None)
    return value if isinstance(value, dict) else {"value": value}


@contextlib.contextmanager
def supervisor_runtime(
    *,
    settings: Optional[Settings] = None,
    agents: Optional[SupervisorAgents] = None,
    session: Any = None,
    gemini: Optional[GeminiService] = None,
    checkpointer: Any = None,
    backend: Optional[str] = None,
) -> Iterator[SupervisorWorkflow]:
    """Yield a ready :class:`SupervisorWorkflow`.

    When ``checkpointer`` is supplied it is used as-is (tests pass an
    ``InMemorySaver``). Otherwise the checkpointer named by
    ``LANGGRAPH_CHECKPOINT_BACKEND`` is opened, which is how the application gets
    PostgreSQL-backed persistent checkpoints.
    """
    settings = settings or get_settings()
    if agents is None:
        if session is None:
            raise ValueError(
                "supervisor_runtime needs either an agents bundle or a database session to "
                "build the default agents around."
            )
        agents = build_default_agents(settings, session=session, gemini=gemini)

    if checkpointer is not None:
        yield SupervisorWorkflow(
            build_graph(agents=agents, settings=settings, checkpointer=checkpointer)
        )
        return

    with open_checkpointer(settings, backend=backend) as saver:
        yield SupervisorWorkflow(build_graph(agents=agents, settings=settings, checkpointer=saver))


__all__ = [
    "GRAPH_NAME",
    "SupervisorAgents",
    "SupervisorWorkflow",
    "build_agent_nodes",
    "build_agents",
    "build_approval_gate",
    "build_default_agents",
    "build_error_handler",
    "build_graph",
    "build_supervisor_node",
    "finalize",
    "mermaid_diagram",
    "pending_interrupt",
    "supervisor_runtime",
    "thread_config",
]
