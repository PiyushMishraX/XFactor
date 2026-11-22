# X FACTOR Multi-Agent Collaboration and Replanning (Step 5)

Step 4 connected the five agents through a compiled LangGraph supervisor. Step 5
makes the collaboration **explicit, auditable and bounded**:

* every delegation becomes a real `AgentTask`;
* every tool call an agent actually makes is recorded as a `ToolInvocation`;
* every attempt is stored as an `AgentExecution` (status, duration, tools, gaps);
* the supervisor evaluates the Scenario agent's plan with the **same**
  deterministic engines Agent 5 audits with, and
* a rejected recommendation opens **one bounded feedback loop** that preserves the
  plan it replaced.

Nothing here is a transcript. A task exists only when the supervisor actually
selected that node, an execution exists only when the node actually ran, and a
tool invocation is written by the tool itself.

The mechanics live in three modules:

| Module | Responsibility |
| --- | --- |
| `app/utils/tool_recording.py` | Context-local tool recorder, `call_recorded`, and the transparent `RecordingConnector` proxy. |
| `app/schemas/collaboration_schemas.py` | The structured protocol: `AgentTask`, `ToolInvocation`, `AgentExecution`, `ScenarioEvaluation`, `ScenarioScreening`, `ScenarioHistoryEntry`, `ReplanningRecord`. |
| `app/orchestration/collaboration.py` | The deterministic decisions: build tasks, screen the plan, build the revision, preserve history. |

`app/orchestration/workflow.py` wires them into the graph.

## 1. Dynamic task delegation

Before an agent node runs, `_agent_node` calls
`build_agent_task(...)` and issues an `AgentTask`:

| Field | Meaning |
| --- | --- |
| `task_id` | `"{step:02d}-{agent}-{attempt}"`, e.g. `03-scenario_planning-2`. |
| `agent` | One of the `AGENT_*` identifiers. |
| `objective` | What the agent is asked to produce (`AGENT_OBJECTIVES`). |
| `reason` | The supervisor's recorded reason that selected the agent (`_last_decision_reason`). |
| `step`, `attempt` | The supervisor pass and the 1-based attempt for that agent. |
| `tools` | The tools the agent is expected to use (`AGENT_TOOLS`). |
| `inputs` | A small, JSON-safe summary of the inputs the agent will receive. |
| `revision` | The `ScenarioRevision` when the task is a scenario re-plan. |

`attempt` is the ordinal of the delegation, not the retry counter: a retry of the
Sensing agent and a replan of the Scenario agent both yield attempts `1, 2`, so
the history reads as "the second time this agent was asked to do this".

The `reason` is copied verbatim from the decision log, so the task and the
decision that caused it can never drift apart.

## 2. Recording tool calls (no fabrication)

Each agent node wraps its execution in `ToolCallRecorder.activate()`. While the
recorder is active:

* **External connectors** (`mapping`, `carriers`, `sap`) are wrapped by
  `wrap_connector` in `build_agents`. `RecordingConnector` is a transparent proxy:
  the call still goes to the real adapter, and only the observation is added.
  It records `"<connector>.<method>"`, the arguments, the duration, whether the
  result is labelled simulated (`is_mock`), and — for an
  `IntegrationNotConfiguredError` — the status `unavailable`.
* **Deterministic engines and the Gemini call** are wrapped with
  `call_recorded("engine.function", arguments, fn, summarise=...)`, which records
  the outcome and re-raises any exception unchanged.
* **The supply-chain repository** is recorded explicitly
  (`supply_chain_repository.snapshot`) because it is not an external connector.

Recording is a **no-op when no recorder is active**, so calling an agent directly
in a unit test behaves exactly as before. Arguments and outcomes are stored as
short JSON-safe summaries; credentials never reach the recorder.

`ToolInvocation.status` is one of:

| Status | When |
| --- | --- |
| `ok` | The call returned. |
| `error` | The call raised anything other than an unavailable integration. |
| `unavailable` | The call raised `IntegrationNotConfiguredError`. |

## 3. Agent result evaluation (deterministic screening)

When the Scenario agent returns a `ScenarioPlan`, the node calls
`evaluate_scenario_plan(...)`, which builds one `RecoveryProposal` per scenario and
runs the **same three engines** Agent 5 uses:

* `compliance.validate_compliance`
* `budget.validate_budget`
* `approval.evaluate_approval`

The verdict is derived the same way:

1. not compliant **or** over budget → `AuditVerdict.REJECTED`;
2. compliant and within budget but approval required →
   `APPROVED_WITH_APPROVAL`;
3. otherwise → `APPROVED`.

Because the screening is identical to the audit, a plan that passes screening will
pass the audit; replanning therefore only triggers on a genuine, deterministic
rejection. The result is stored as `ScenarioScreening` with one
`ScenarioEvaluation` per alternative (cost, days, risk, verdict, violations,
warnings, `recommended`, `reason`).

## 4. Feedback loop and conditional replanning

`screening_requires_replan(screening)` is the single condition that opens the
loop: it is true when there is no recommended scenario, or the recommended one
was `REJECTED`.

When it is true and rounds remain, `_screening_update`:

1. builds a `ScenarioRevision` (`build_scenario_revision`) listing the rejected
   scenario ids (cumulative across rounds), the carriers they used, the
   deterministic violation reasons and a one-line feedback sentence;
2. **preserves the replaced plan** as a `ScenarioHistoryEntry`
   (`build_history_entry`) — the full `ScenarioPlan` plus its evaluations;
3. records a `ReplanningRecord` (`build_replanning_record`) stating the trigger
   (`"deterministic screening"`), what was rejected and what was requested;
4. clears `scenario_plan`, stores the revision and routes back to the supervisor,
   which delegates to the Scenario agent again with the revision.

The Scenario agent's `plan(request, revision)` applies the revision
deterministically (`_apply_revision`): it drops the rejected scenario ids and any
option from an excluded carrier, and **never invents a replacement**. The revision
is passed to the Gemini narrative as context only; the model cannot re-admit an
excluded option.

### Bounded autonomy

`MAX_REPLAN_ROUNDS = 2` caps how many revisions the supervisor may request. If
the revised plan is empty (every alternative was excluded) or the rounds are
exhausted, the run ends with `STATUS_NO_COMPLIANT_RECOVERY` rather than looping.
The Step 4 iteration bound (`LANGGRAPH_MAX_ITERATIONS × 5`) remains as a second
guard.

## 5. Scenario comparison and history preservation

Every alternative is compared on the numbers the agents already produced
(`rank`, `total_cost_usd`, `total_days`, `risk_score`) and the supervisor's own
verdict. Preserved plans live in `RecoveryRecommendation.scenario_history`, and
every round in `replanning`, so a replanned run still shows **all** the options
that were considered and why each earlier plan was abandoned.

## 6. Failure recovery and unavailable tools

* **Transient failure** — the error handler allows `_MAX_AGENT_ATTEMPTS` (2)
  attempts and records a `FAILED` `AgentExecution` for each. Hard failures
  (`GeminiNotConfiguredError`, `IntegrationNotConfiguredError`, `ToolInputError`,
  base `ValidationError`) are never retried.
* **Unavailable inventory integration on the optional node** — the standalone
  rebalancing node returns a `SKIPPED` execution, adds the agent to
  `skipped_agents` and a gap to `missing_information`, and hands control back to
  the supervisor instead of failing the run.
* **Unavailable inventory inside scenario planning** — the Scenario agent catches
  `IntegrationNotConfiguredError`, continues without inventory data and records
  the gap; `sap.list_inventory` is still recorded as `unavailable`.

## 7. The final record

`RecoveryRecommendation` (Step 4) now also carries:

| Field | Contents |
| --- | --- |
| `tasks` | Every `AgentTask` the supervisor issued, in order. |
| `agent_executions` | Every `AgentExecution`, including retries and skips. |
| `tool_calls` | Flat, ordered list of every recorded `ToolInvocation`. |
| `scenario_screening` | The deterministic evaluation of the final scenario set. |
| `scenario_history` | Plans preserved through replanning. |
| `replanning` | Every replanning round and its trigger. |
| `replanning_rounds` | Revision rounds actually performed. |
| `skipped_agents` | Agents whose task could not run (integration unavailable). |

The HTTP layer (`app/api/orchestration.py`) surfaces the same fields, so the
future Agent Activity dashboard can render real executions and tool calls rather
than inventing them.

## 8. New status

| Status | Meaning |
| --- | --- |
| `no_compliant_recovery` | Every alternative was rejected by deterministic validation, and replanning is exhausted or produced no new option. |

This is distinct from the Step 4 `no_feasible_recovery` (no route/scenario could
be recommended at all) and `approval_rejected` (a valid proposal was rejected by
the audit or a human).

## 9. Tests

`backend/tests/test_collaboration.py` — 14 tests:

* a task exists for every supervisor decision, and only for executed decisions;
* flattened tool calls equal the executions' calls and stay within
  `AGENT_TOOLS`;
* simulated tool data is labelled and durations are present;
* screening evaluates all three default scenarios as `Approved` without
  replanning;
* a lead-time rule triggers exactly one revision, preserves history, and the
  second attempt excludes the rejected alternatives;
* an impossible reliability floor ends in `no_compliant_recovery` without an
  audit;
* an unavailable SAP integration is skipped (direct path) or degrades gracefully
  (scenario path);
* a transient failure yields two failed executions with attempts `[1, 2]`;
* the collaboration state round-trips through JSON;
* every recorded tool belongs to its agent's declared tool set.

Full suite: **265 passed, 6 skipped** (the 6 skips are the opt-in
`RUN_LIVE_GEMINI=1` tests). The opt-in live supervisor check
(`RUN_LIVE_GEMINI=1 pytest tests/test_orchestration.py -k live`) passes against the
real Gemini API through the new tool-recording wrappers.
