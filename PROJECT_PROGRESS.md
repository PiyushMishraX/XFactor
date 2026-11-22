# X FACTOR — PROJECT PROGRESS (Recovery File)

> Update this file immediately after **every** meaningful implementation milestone.
> Never rely on conversation history to remember completed work.

_Last updated: 2026-11-22 (Step 8 complete)_

---

## 1. Project overview

**X FACTOR** — Agentic AI-Powered Supply Chain Resilience Platform, developed for
the SAP Resilient Supply Chains Hackathon.

One coordinated agentic system (not a collection of chatbots) that performs:

**Detect → Reason → Simulate → Approve → Execute**

Core stack: LangGraph supervisor + 5 specialised agents + Google Gemini reasoning
+ deterministic Python tools + FastAPI backend + PostgreSQL + SAP connectors +
React (Vite) frontend.

---

## 2. Current status

| Field | Value |
| --- | --- |
| Current phase | **Step 8 — Agent Activity and Decision Dashboard** |
| Status | ✅ **Complete and verified** (see the live-Gemini limitation in §11 item 17) |
| Overall completion (estimate) | **~91%** (Steps 0–8 of 11 roadmap steps) |
| Next step | **Step 9 — Testing and End-to-End Validation** |

---

## 3. Completed steps

### Step 0 — Project Initialization and Architecture ✅

- Modular FastAPI backend created with the full roadmap directory layout.
- React + Vite frontend created with the full roadmap directory layout.
- PostgreSQL connection configured (lazy engine, non-fatal health reporting).
- Pydantic settings + environment variables configured (`.env` support).
- Health-check endpoints added (`/api/health`, `/api/health/live`).
- CORS configured from settings.
- Logging configured (human-readable dev + JSON production modes).
- Global error handling added.
- Configuration placeholders prepared for Gemini, LangGraph and SAP.
- `.gitignore` and `.env.example` created for both services.
- Backend test-suite added and passing.

### Step 1 — Gemini Integration and Disruption Sensing Agent ✅

- **Gemini integration** (`app/services/gemini_service.py`): REST `generateContent`
  with `responseMimeType: application/json` + `responseSchema`; retry/back-off on
  `429/500/502/503/504`; fails loudly (no mock-reasoning fallback) when
  `GEMINI_API_KEY` is missing or the reply is unusable. Verified **live** against
  `gemini-3.5-flash` (1.5 and 2.5 models are retired for this key — see §11).
- **Disruption schemas** (`app/schemas/disruption_schemas.py`): three strictly
  separated layers — `DisruptionReport` (unstructured input), `LLMAssessment`
  (the only fields the LLM decides; **no** risk score/severity), and
  `DisruptionAssessment` (validated output). Covers all **8 disruption
  categories** + `Unrelated`, 5 severity bands and 12 observable `RiskFactor`s.
- **Deterministic risk engine** (`app/services/risk_scoring.py`): weighted-factor
  table (12 factors, 8–22 points each) plus capped exposure points for validated
  shipments/suppliers; severity bands 0/10/35/60/85 → Negligible…Critical;
  score capped at 100. No arithmetic in any prompt.
- **Supply-chain repository** (`app/services/supply_chain_repository.py`):
  `Protocol` interface + PostgreSQL implementation that resolves LLM-claimed
  shipment/supplier ids and affected locations against real master data, and
  reports ids that do **not** exist as `unvalidated_*_references`.
- **ORM models** (`app/models/supply_chain.py`): `Supplier` and `Shipment`.
- **Disruption Sensing Agent** (`app/agents/disruption_sensing.py`): LLM call
  with a strict system instruction and response schema, then deterministic
  post-processing — scoring, reference validation, provenance (the source report
  is always prepended to evidence), missing-information detection and
  contradiction detection. Analysis only; it never executes an operational action.
- **Reference-data seed** (`scripts/seed_reference_data.py`,
  `app/services/reference_data.py`): 5 demo suppliers and 10 demo shipments
  (explicitly labelled as demo seed data, not live SAP master data) seeded into
  the live PostgreSQL instance.
- **Tests**: 4 new modules — `test_gemini_service.py` (MockTransport),
  `test_risk_scoring.py`, `test_supply_chain_repository.py` (skips if PostgreSQL
  is unreachable), `test_disruption_sensing.py` (the five required scenarios + an
  opt-in `RUN_LIVE_GEMINI=1` live test). **59 passed, 1 skipped; live test passed.**

### Step 2 — External Tools and Deterministic Business Logic ✅

**Shared contract (both layers).** `app/integrations/base.py` gives every external
record a frozen `Provenance` (`source`, `is_mock`, `retrieved_at`, `endpoint`) with
a `label` that renders `"<source> [SIMULATED]"`; `app/tools/base.py` gives every
engine a frozen `EngineResult` carrying an `assumptions` tuple and a `ToolInputError`
for rejected input.

**A. External connectors (`app/integrations/`, 10 modules).** Each mirrors the
`weather.py` reference shape — domain enum → record model with
`provenance: Provenance` → `Protocol` → `Simulated*Connector(MockConnector)` →
`Live*Connector(HttpConnector)` → `get_*_connector()` factory:

| Module | Interface | Sample data source |
| --- | --- | --- |
| `weather.py` | `get_alerts(*, location)` | demo chokepoints + seeded |
| `news.py` | `get_headlines(*, query, limit=10)` | demo chokepoints + seeded |
| `maritime_alerts.py` | `get_alerts(*, region)` | demo regions + seeded |
| `port_congestion.py` | `get_congestion(*, port)` (exactly one record) | 12 demo ports + seeded |
| `tariffs.py` | `get_rate(*, origin_country, destination_country, hs_code)` | 8 demo lanes + seeded |
| `suppliers.py` | `get_profile(*, supplier_id)` / `list_profiles()` | matches `reference_data` (SUP001–SUP005) |
| `carriers.py` | `list_services(*, transport_mode=None)` | demo carriers (Maersk…Evergreen, DB Cargo, DHL, Lufthansa) |
| `shipment_tracking.py` | `get_events(*, shipment_id)` | matches demo shipments (SH001–SH010) + seeded |
| `mapping.py` | `get_route(*, origin, destination)` | 10 demo lanes + derived (reverse / seeded) |
| `sap.py` | **read-only**: shipments, suppliers, inventory, purchase orders | reuses `reference_data` + sample inventory/POs |

The factories return the **simulated** adapter whenever a base URL is not
configured; the live adapters raise `IntegrationNotConfiguredError` rather than
silently returning sample data. `get_sap_connector()` honours `SAP_USE_MOCK`
(true by default) and raises `IntegrationNotConfiguredError` when mock mode is off
and no SAP credentials exist.

**B. Deterministic engines (`app/tools/`, 10 engines).** Pure arithmetic — no
network, database or LLM call inside any engine:

| Engine | Function |
| --- | --- |
| `risk.py` | `calculate_risk` — documented delegate to the Step 1 `risk_scoring` engine |
| `costing.py` | `calculate_route_cost` — freight + handling + insurance + tariff |
| `route_optimization.py` | `rank_routes` — compares only the options supplied |
| `lead_time.py` | `calculate_delivery_time` — transit + handling + delays |
| `inventory.py` | `calculate_inventory_shortage` — shortage / surplus |
| `safety_stock.py` | `calculate_safety_stock` — safety stock + reorder point |
| `supplier_ranking.py` | `rank_suppliers` — configurable weighted scorecard |
| `compliance.py` | `validate_compliance` — returns specific rule violations |
| `budget.py` | `validate_budget` — within-budget / overage / utilisation |
| `approval.py` | `evaluate_approval` — decides *whether* and *at what level*; never executes |

**Tests.** `tests/test_integrations.py` (62 tests: the labelled-simulated contract,
determinism, congestion-band thresholds, and live adapters via `httpx.MockTransport`)
plus one test module per engine. `app/integrations/__init__.py` and
`app/tools/__init__.py` docstrings rewritten to index the modules.

### Step 3 — Build the Remaining Four AI Agents ✅

Four new specialised agents were built on top of the Step 1/2 layers. They are
independent modules — the central supervisor is **deliberately not** implemented
(that is Step 4). Every agent keeps the same boundary as Step 1: **the LLM
explains, deterministic code decides**, the model response schema never carries a
number-producing field, and simulated records stay unmistakably labelled.

| Agent | Module | Schemas | Deterministic core it drives |
| --- | --- | --- | --- |
| 2 — Scenario Planning | `app/agents/scenario_planning.py` | `app/schemas/scenario_schemas.py` | `route_optimization.rank_routes`; composes Agents 3 & 4 |
| 3 — Rerouting & Logistics | `app/agents/rerouting_logistics.py` | `app/schemas/rerouting_schemas.py` | `costing` + `lead_time` + `risk_scoring` via `rank_routes` |
| 4 — Inventory Rebalancing | `app/agents/inventory_rebalancing.py` | `app/schemas/rebalancing_schemas.py` | `inventory` + `safety_stock` |
| 5 — Compliance & Audit | `app/agents/compliance_audit.py` | `app/schemas/audit_schemas.py` | `compliance` + `budget` + `approval` |

- **Agent 3 (Rerouting & Logistics).** Scores every carrier service the
  `mapping`/`carriers` connectors return for the lane, marks the incumbent option
  and its rank, filters candidates by mode case-insensitively, and **never invents
  a route** — when no service matches it returns an empty ranking plus a gap. Cost
  and transit are computed by `app.tools.costing` / `app.tools.lead_time`; risk by
  the Step 1 engine. Deterministic gap detection covers derived lanes, unknown
  incumbents and missing risk factors.
- **Agent 4 (Inventory Rebalancing).** Reads the read-only SAP inventory across
  plants, computes the target plant's shortage, and allocates transfers drawn
  **only from stock above a source plant's safety stock** (committed stock is
  excluded from the available balance). Calculates safety stock from demand
  history with `app.tools.safety_stock` when supplied, else falls back to the
  SAP-recorded value. Refused sources are returned as `RejectedTransfer`s with a
  reason, never silently used.
- **Agent 5 (Compliance & Audit).** Derives the verdict **only** from
  `validate_compliance` / `validate_budget` / `evaluate_approval`; a failed
  mandatory rule yields `Rejected` no matter what the model writes. Emits a
  structured `audit_evidence` trail (one row per deterministic finding) and
  refuses to run without a rule set (`ToolInputError`). `LLM_AUDIT_SCHEMA` has no
  verdict field at all, so the model structurally cannot override validation.
- **Agent 2 (Scenario Planning).** Composes Agent 3 and, when an inventory request
  is supplied, Agent 4; builds the recovery approaches the data supports — continue
  on the existing route, change transport mode, change carrier — and scores each
  with the same `rank_routes` engine. Feasibility tiering
  (`Feasible` / `Feasible subject to finance approval` / `Affordability unknown`)
  is deterministic against the caller's budget; the model's per-scenario
  assessments are folded into the matching `ScenarioComparison.notes`; the ranking
  and the recommendation can never be changed by the narrative.

**Composition wiring.** `app/agents/__init__.py` already indexed all five agent
modules with their Step numbers; the four new ones were added to that index.

**Tests.** Four new modules (one per agent): `tests/test_rerouting_logistics.py`,
`tests/test_inventory_rebalancing.py`, `tests/test_compliance_audit.py`,
`tests/test_scenario_planning.py`. Every test drives the agent through injectable
`StubGeminiService` + Step 3 connector doubles added to `tests/fakes.py`
(`FakeMappingConnector`, `FakeCarrierConnector`, `FakeSAPConnector` plus
`make_provenance` / `make_carrier_service` / `make_inventory_item`), asserts the
hand-checkable engine numbers, asserts that number-producing fields are **absent**
from the LLM schema, asserts "the model cannot change the decision", and covers
malformed output and missing-key failures. Each module also has an opt-in
`RUN_LIVE_GEMINI=1` test against the real API over simulated connectors.

**One Step 2 sample-data change.** `app/integrations/sap.py` `_SAMPLE_INVENTORY`
gained two extra plant rows (MAT-PHARMA-001 @ Hamburg DC, MAT-ELEC-003 @ Singapore
DC) so Agent 4 can demonstrate a real cross-plant transfer; previously each
material existed at exactly one plant, so the agent always reported the
"only plant holding this material" gap. No pinned test asserted the row count, and
`get_inventory_item()` still returns the first match, so the change is
non-breaking.

### Step 4 — LangGraph Supervisor and Orchestration ✅

The five specialised agents are now wired into one compiled LangGraph graph. The
supervisor **dynamically delegates** from validated structured results — it never
runs a fixed sequence — and records why it chose each node.

| Module | Purpose |
| --- | --- |
| `app/orchestration/state.py` | Shared `WorkflowState` (TypedDict + reducers), `RecoveryRequest`, `SupervisorDecision`, `RecoveryRecommendation`, node/agent ids, `STATUS_*` constants, default compliance policy |
| `app/orchestration/checkpointing.py` | `in_memory_checkpointer()` (InMemorySaver) and `postgres_checkpointer()` (PostgresSaver); `checkpointer_dsn()` derives the libpq URL; `open_checkpointer()` selects by `LANGGRAPH_CHECKPOINT_BACKEND` |
| `app/orchestration/workflow.py` | The compiled supervisor graph: supervisor node + 5 agent nodes + approval gate + error handler + `finalize`, joined by conditional edges |
| `app/api/orchestration.py` | HTTP surface: start a run, resume an interrupted run, read a saved state |
| `backend/docs/workflow.md` | The required graph visualisation (verbatim `mermaid_diagram(graph)` output) plus the node table, decisions and bounds |

- **The six dynamic decisions.** On each pass the supervisor returns exactly one
  of: logistics analysis required; inventory analysis required; additional
  scenarios required; scenario revision needed; compliance validation required;
  proceed to approval. Each is written to the decision log as
  `SupervisorDecision(step, action, reason)`.
- **Structured, never conversational.** Every branch reads validated state
  (assessment shipment count, scenario feasibility, audit verdict); the workflow
  explains itself from the decision log, not from a transcript.
- **Bounded execution.** `_MAX_AGENT_ATTEMPTS = 2` retries per agent and an
  overall bound of `LANGGRAPH_MAX_ITERATIONS × 5`; hard failures
  (`GeminiNotConfiguredError`, `IntegrationNotConfiguredError`, `ToolInputError`,
  base `ValidationError`) are never retried. A later failure never discards the
  earlier assessment or scenario plan.
- **No double-invocation.** `ScenarioPlanningAgent.plan()` already composes the
  rerouting and inventory agents, so the supervisor runs the standalone nodes only
  on the direct path or as the single bounded scenario revision.
- **Interrupt / resume.** The approval gate calls LangGraph `interrupt(...)`; the
  run resumes from its saved checkpoint with `{"approved": bool, "comment": str}`
  (an approval is `completed`, a rejection `approval_rejected`).
- **Persistent checkpoints.** `PostgresSaver` writes every checkpoint to the
  application's PostgreSQL database so a paused run can be resumed in another
  process; `checkpointer_dsn()` strips the `+psycopg2` suffix because the adapter
  speaks psycopg 3 / libpq while the app's engine speaks psycopg2.
- **Tests.** `tests/test_orchestration.py` — 20 tests covering the six roadmap
  scenarios (normal disruption; multiple shipments; missing route information; no
  feasible recovery; agent failure; invalid agent output) plus approval
  interrupt/resume, the JSON-only state contract, the iteration bound, the Mermaid
  export and an opt-in `RUN_LIVE_GEMINI=1` check. **19 passed, 1 skipped.**

### Step 5 — Multi-Agent Collaboration and Autonomous Replanning ✅

Step 5 extends the Step 4 graph so the collaboration is explicit, auditable and
bounded. Every delegation is a structured task, every tool call is recorded from
the real invocation, every attempt is an execution record, and a rejected plan
opens at most two bounded revisions that preserve the plan they replaced.

| Module | Purpose |
| --- | --- |
| `app/schemas/collaboration_schemas.py` | The structured protocol: `AgentTask`, `ToolInvocation`, `AgentExecution`, `ScenarioEvaluation`, `ScenarioScreening`, `ScenarioHistoryEntry`, `ReplanningRecord` |
| `app/utils/tool_recording.py` | Context-local `ToolCallRecorder`, `call_recorded`, transparent `RecordingConnector`, `wrap_connector`; no-op outside a recorder |
| `app/orchestration/collaboration.py` | Deterministic decisions: `build_agent_task`, `evaluate_scenario_plan`, `screening_requires_replan`, `build_scenario_revision`, `build_history_entry`, `build_replanning_record`; `MAX_REPLAN_ROUNDS = 2`, `AGENT_TOOLS`, `AGENT_OBJECTIVES` |
| `app/orchestration/workflow.py` | Wires tasks, recording, screening and replanning into the graph |
| `backend/docs/collaboration.md` | The collaboration record, screening, feedback loop, bounds and new status |

- **Dynamic task delegation.** Before each agent node runs, `_agent_node` issues an
  `AgentTask` whose `task_id` is `"{step:02d}-{agent}-{attempt}"`, whose `reason`
  is copied from the decision log, and whose `tools`/`inputs` are the declared
  tools and a JSON-safe input summary. `attempt` is the ordinal delegation, so a
  retry and a replan both read `1, 2`.
- **Real tool recording.** Agent nodes activate a `ToolCallRecorder`; connector
  calls are observed by transparent `RecordingConnector` proxies (`mapping`,
  `carriers`, `sap`), deterministic engines and Gemini are wrapped with
  `call_recorded`, and the repository snapshot is recorded explicitly. Statuses
  are `ok` / `error` / `unavailable`; simulated results carry `is_mock`.
- **Deterministic result evaluation.** `evaluate_scenario_plan` builds a
  `RecoveryProposal` per scenario and runs the same `validate_compliance` /
  `validate_budget` / `evaluate_approval` engines Agent 5 uses, so screening and
  audit cannot disagree. Ratings are `Rejected` / `Approved with approval` /
  `Approved`.
- **Feedback loop and conditional replanning.** When the recommended scenario is
  rejected, `_screening_update` builds a cumulative `ScenarioRevision` (rejected
  ids, excluded carriers, deterministic reasons, feedback), preserves the replaced
  plan as a `ScenarioHistoryEntry`, records a `ReplanningRecord`, clears the plan
  and routes back to the supervisor. `ScenarioPlanningAgent.plan(request, revision)`
  filters excluded options without inventing replacements.
- **Bounded autonomy.** `MAX_REPLAN_ROUNDS = 2`; an empty revised plan or exhausted
  rounds ends the run with the new `STATUS_NO_COMPLIANT_RECOVERY` instead of
  looping. The Step 4 iteration bound remains as a second guard.
- **Unavailable tools.** The optional inventory node records a `SKIPPED` execution,
  adds the agent to `skipped_agents` and records a gap; inside scenario planning the
  Scenario agent continues without inventory data and still records
  `sap.list_inventory` as `unavailable`.
- **Final record.** `RecoveryRecommendation` gained `tasks`, `agent_executions`,
  flat `tool_calls`, `scenario_screening`, `scenario_history`, `replanning`,
  `replanning_rounds` and `skipped_agents`; the HTTP layer surfaces the same
  fields.
- **Tests.** `tests/test_collaboration.py` — 14 tests: task↔decision matching, tool
  calls equal flattened executions and stay within `AGENT_TOOLS`, labelled mocks
  and durations, all-approved screening with no replanning, one revision that
  preserves history and excludes the rejected alternatives, an impossible
  reliability floor ending in `no_compliant_recovery`, unavailable SAP skipped or
  degraded gracefully, retries with attempts `[1, 2]`, JSON round-trip, and only
  selected agents receiving tasks. **14 passed.** Full suite: **265 passed, 6
  skipped**.

### Step 6 — Human-in-the-Loop and Authorized Execution ✅

Step 6 turns the Step 4 interrupt into an authenticated, version-bound decision
and an idempotent execution. Nothing trusts a status supplied by the caller: the
request body carries only an action, a comment and a proposal version; the
approver identity is derived from a bearer credential.

| Module | Purpose |
| --- | --- |
| `app/schemas/approval_schemas.py` | `ProposalSnapshot` + deterministic version, `ApproverIdentity` / `ApproverRole`, decision request/record/outcome, queue view |
| `app/schemas/execution_schemas.py` | `ExecutionAction`, `ExecutionReport` and the action/run statuses |
| `app/models/approvals.py` | `ApprovalRequestRow` (`approval_requests`, one row per thread) |
| `app/services/approval_auth.py` | Constant-time token authentication (`secrets.compare_digest`) and Manager/Director/Admin hierarchy |
| `app/services/approval_repository.py` | Queue persistence (`PostgresApprovalRepository`, `InMemoryApprovalRepository`, `ensure_approval_schema`) |
| `app/services/approval_service.py` | The ordered security model: authenticate → paused? → version match → authorize → resume → record → execute → record new pending version |
| `app/services/execution.py` | Deterministic plan, simulated/live adapters, idempotent `ExecutionService` |
| `app/orchestration/approvals.py` | Proposal snapshot/version, resume payload, legacy parsing, bounded modification revisions |
| `app/api/approvals.py` | Authenticated approval API |
| `backend/docs/approval-and-execution.md` | Approval, versioning, execution and API reference |
| `frontend/src/pages/ApprovalCenter.jsx` | Approval interface (token, queue, proposal, history, decisions, execution report) |

- **Proposal version.** `ProposalSnapshot.proposal_version` is the first 16 hex
  characters of a SHA-256 digest over canonical JSON, excluding `thread_id`,
  `proposal_version` and `created_at`. The graph (no thread id) and the API (with
  a thread id) therefore agree on the same version; any operational change
  produces a different version.
- **Authentication.** `APPROVER_CREDENTIALS` is a comma-separated list of
  `token:approver_id:Role` entries. Tokens are compared against every entry with
  `secrets.compare_digest`; the hierarchy is Manager < Director < Admin. An empty
  or malformed configuration fails closed: every approval endpoint returns `503`.
- **Queue persistence.** One row per thread holds the current proposal, version,
  level, status, decision-history JSON and execution report. A new version starts
  a new pending review, preserves history and clears the old execution report;
  re-recording an already-decided version never reopens it.
- **Decisions.** `ApprovalService.decide` authenticates, confirms the workflow is
  paused at the gate, records the queue item if missing, rejects non-pending or
  stale versions (both stored and current workflow versions), enforces the role,
  resumes the checkpoint and appends an `ApprovalDecisionRecord` with approver id,
  role, comment, proposal version and timestamp.
- **Modifications and rejection.** A modification request builds a
  `ScenarioRevision` excluding the recommended scenario and carrying the reviewer's
  comment, sends the plan back to the Scenario agent, and pauses again on the new
  proposal version with history preserved. `MAX_MODIFICATION_ROUNDS = 2`; one
  request beyond the bound closes the workflow as `approval_rejected`. A rejection
  closes the workflow immediately and produces no execution.
- **Step 4 compatibility.** The gate still accepts the legacy
  `{"approved": true}` payload (and booleans/words), attributed to `"human"`, so
  the Step 4 tests and behaviour are unchanged.
- **Authorized execution.** `build_execution_plan` emits `shipment_plan_update`
  always, plus `inventory_transfer`, `carrier_change` and `sap_execution` when the
  proposal requires them. Every action is keyed
  `thread:proposal_version:action_type`; `ExecutionService` replays an existing
  report instead of executing again, refuses unapproved/unversioned proposals, and
  reports `completed` / `partial` / `failed`. The default adapter is clearly
  labelled `[SIMULATED]`; the live adapter posts with an `Idempotency-Key` and
  `x-client-id`.
- **Secured API.** `GET /api/approvals/pending`, `GET …/{thread_id}`,
  `POST …/{thread_id}/decision` and `GET …/{thread_id}/execution`. Errors map to
  401 (missing/unknown token), 403 (insufficient role), 404 (no item/report),
  409 (not paused, already decided, stale version) and 503 (credentials or
  execution gateway unconfigured). The unauthenticated Step 4
  `POST …/resume` endpoint was removed.
- **Frontend.** The Approval Center tab keeps a pasted bearer token in
  `sessionStorage` only, lists pending proposals, shows the version, reasons,
  violations and full decision history, requires a comment for reject/modify,
  submits decisions, and renders the execution report with its `[SIMULATED]`
  marker. `npm run build` passes.
- **Tests.** `tests/test_approvals.py` — 50 tests (version stability/exclusions,
  credential parsing, authentication, hierarchy, bearer parsing, legacy and Step 6
  payloads, approval/rejection identity+timestamp+history, the bounded
  modification loop, execution plan/keys/labelling/replay/refusal/partial+failed
  reports, live adapter via `httpx.MockTransport`, adapter factory, repository
  semantics in memory and SQLite, and the API's 401/403/409/503 paths including
  approve → execute → duplicate prevention and the modification round-trip).
  **50 passed.** Full suite at Step 6 completion: **315 passed, 6 skipped**
  (now 352 after Step 7).

### Step 7 — SAP Integration ✅

Step 7 adds the enterprise-system boundary. The Step 2 read connector stays
**read-only**; writes live in a separate module with a separate permission and
mandatory human-approval evidence. No live SAP tenant is connected —
`SAP_USE_MOCK=true` remains the default and every record is labelled simulated.

| Module | Purpose |
| --- | --- |
| `app/integrations/sap_profiles.py` | Prepared profiles for S/4HANA, Business Accelerator Hub, BTP and Integration Suite, with relative read/write paths |
| `app/integrations/sap_auth.py` | OAuth2 client-credentials provider, cached tokens, separate read/write scopes, `SAPHttpClient`, header redaction |
| `app/integrations/sap_write.py` | Validated write requests, mandatory `SAPApprovalEvidence`, simulated + live adapters, idempotency keys, write-permission factory |
| `app/integrations/sap.py` | Added material master reads and profile-aware live read paths with optional OAuth |
| `app/integrations/base.py` | `Retry-After` support and `status_code` on `IntegrationRequestError` |
| `backend/docs/sap-integration.md` | Profiles, authentication, permissions, write contract, failure handling, limitations |
| `backend/tests/test_sap_integration.py` | 37 tests |

- **Four prepared profiles.** `SAP_API_FAMILY` selects `s4hana` (default),
  `business_accelerator_hub`, `btp` or `integration_suite`. Each declares every
  read capability (shipments, purchase orders, suppliers, inventory, materials)
  and every write capability. The paths are prepared gateway defaults that must be
  confirmed against the tenant; no entitlement is claimed.
- **Environment-based authentication.** When `SAP_AUTH_URL` is set the connector
  requests an OAuth2 client-credentials token and caches it until shortly before
  expiry; without it the Step 2 gateway `x-api-key` convention is used. The read
  path requests `SAP_READ_SCOPE`, the write path `SAP_WRITE_SCOPE`, so a read
  token can never write. Tokens and secrets are never logged, and a token-endpoint
  rejection reports only the status code.
- **Read interface.** Shipment, purchase-order, supplier, inventory and material
  reads via `list_*` / `get_*`. `SimulatedSAPConnector` returns five suppliers, ten
  shipments, five materials, seven inventory rows and four purchase orders. The
  connector still exposes no write methods (regression-tested).
- **Authorized writes.** Three validated request types — shipment plan update,
  inventory transfer (`units > 0`, source ≠ target) and operational change. Every
  method requires keyword-only `SAPApprovalEvidence`, which
  `approval_evidence_from_decision` builds only from an approved decision and
  refuses reject / request-modifications. Evidence carries approver identity, the
  workflow thread, the reviewed `proposal_version` and the decision timestamp.
- **Idempotency and results.** Keys are
  `sap:{thread}:{version}:{type}:{request_id}`, sent as `Idempotency-Key` and in
  the body; the mock reference is derived deterministically. Results are
  `accepted` / `simulated` / `rejected` (400/409/422) / `failed` with provenance.
- **Separate read and write permissions.** `SAP_WRITE_ENABLED=false` by default;
  read credentials never imply write access; the factory fails closed.
- **Rate limits and failures.** Shared transport retries 429/5xx, honours a
  numeric `Retry-After` (clamped to 30s), and raises status-aware request errors.
- **Tests.** 37 new tests: profiles, token caching/shape/redaction, material
  reads, profile-aware live paths, request validation, approval evidence,
  keyword-only approval, deterministic mock writes, disabled-by-default writes,
  read≠write, live payload/header/idempotency assertions, rejection/failure
  classification, `Retry-After`, and approved-vs-rejected end-to-end.
  **37 passed.** Full suite: **352 passed, 6 skipped**.

### Step 8 — Agent Activity and Decision Dashboard ✅

Step 8 adds an enterprise control-tower UI over the state Steps 4–7 already
produced. The dashboard is a **read-only projection**: it recomputes no verdict,
contains no sample agent activity and adds no write endpoint. Every page is
wired to a real FastAPI endpoint and renders explicit loading, error and empty
states.

| Module | Purpose |
| --- | --- |
| `app/models/workflow_runs.py` | `WorkflowRunRow` (`workflow_runs`): queryable run summary + full JSON-safe state |
| `app/services/workflow_history.py` | `record_workflow_run`, `list_workflow_runs`, `get_workflow_run`, `list_disruptions`, `run_status_counts`, `json_safe`, `ensure_workflow_run_schema` |
| `app/services/dashboard_service.py` | `platform_overview` (KPI counts + latest runs + declared data sources) and `list_shipments` |
| `app/api/dashboard.py` | Read-only `/api/dashboard/*` router |
| `frontend/src/pages/*.jsx` | Eight pages: Overview, Disruption Monitoring, Agent Activity, Scenario Comparison, Approval Center, Shipment Management, Inventory Management, Audit History |
| `frontend/src/components/AgentWorkflowGraph.jsx` | React Flow (`@xyflow/react`) graph built from recorded executions |
| `backend/docs/dashboard.md` | Endpoint/page map, schema, provenance and verification notes |

- **Run registry.** `POST /api/orchestration/workflows` records every run —
  including failed runs — and an authenticated decision refreshes the same row
  (one row per thread). Recording is best-effort: it is logged and rolled back
  on failure, so history can never lose a completed workflow or fail a decision.
  The LangGraph `__interrupt__` object and private keys are stripped by
  `json_safe()`.
- **Dashboard API.** `/dashboard/overview`, `/runs`, `/runs/{thread_id}`,
  `/disruptions`, `/shipments` and `/inventory`; database or SAP configuration
  failures map to `503`, an unknown thread to `404`, and an empty history to an
  empty list. Shipments are the seeded demo rows joined with suppliers;
  inventory is the SAP connector with its real `is_mock`/`source` provenance.
- **Agent Activity (highest priority).** Workflow id, active disruption,
  supervisor decision trail, execution progress, the five agent cards with
  status/current task/tools, structured results, tool invocations, handoffs,
  replanning rounds, errors/retries, a React Flow graph, a timeline and a
  decision log — all from the recorded run, never fabricated.
- **Scenario Comparison.** Per-scenario route, delivery days, cost, risk,
  inventory impact, feasibility, compliance/budget validation and the
  deterministic recommendation, plus screening and replanning history.
- **Approval Center (rewritten).** Token form (fail-closed `503` message),
  pending queue, proposed action and reasons, cost/budget delta, transit and
  inventory impact, per-agent validations from the recorded executions, audit
  verdict, decision history, approve/request-modifications/reject controls, and
  the execution report. The approval API and behaviour are unchanged.
- **Other pages.** Overview KPIs/charts/latest runs; disruption detail with the
  assessment and supervisor decision; shipment table with filters; inventory
  positions with a `[SIMULATED]` banner; audit history driven by the run list.
- **Design.** Rewritten dark-navy control-tower theme with a numbered sidebar,
  sticky topbar, KPI tiles, panels, tables, accessible status badges, and
  responsive breakpoints at 1180/1024/760/480 px (sidebar becomes a drawer).
- **Tests.** `tests/test_dashboard.py` — 12 tests. Full suite: **364 passed,
  6 skipped**. `npm run build` passes (57 modules); `npm run lint` reports
  0 errors (2 pre-existing hooks warnings).
- **Verification caveat.** Two live verification runs failed on Gemini
  (`503 UNAVAILABLE`, then `429` free-tier quota), so populated *successful*
  Scenario Comparison and Approval Center views were not exercised in a browser
  that day; the failure-path UI and every other page were browser-verified. The
  two `EV-UI-VERIFY-*` failed runs are genuine recordings and remain in the
  shared database.

---

## 4. Partially completed steps

None.

---

## 5. Pending steps

| Step | Name | Status |
| --- | --- | --- |
| 1 | Gemini integration + Disruption Sensing Agent | ✅ Complete (verified live) |
| 2 | External tools + deterministic business logic | ✅ Complete (verified) |
| 3 | Remaining four AI agents | ✅ Complete (verified) |
| 4 | LangGraph supervisor and orchestration | ✅ Complete (verified) |
| 5 | Multi-agent collaboration + autonomous replanning | ✅ Complete (verified) |
| 6 | Human-in-the-loop and authorized execution | ✅ Complete (verified) |
| 7 | SAP integration | ✅ Complete (verified; simulated adapters, no live tenant) |
| 8 | Agent Activity and Decision dashboard | ✅ Complete (verified; see §11 item 17) |
| 9 | Testing and end-to-end validation | Not started |
| 10 | Deployment and hackathon demonstration | Not started |

---

## 6. Files created / modified / deleted

### Created — backend

| File | Purpose |
| --- | --- |
| `backend/requirements.txt` | Pinned-compatible dependency list |
| `backend/.env.example` | Backend environment template (names only) |
| `backend/pytest.ini` | pytest config (`pythonpath = .`) |
| `backend/app/__init__.py` | Package + version |
| `backend/app/main.py` | FastAPI app: CORS, logging, routers, error handler, lifespan |
| `backend/app/api/__init__.py` | API package |
| `backend/app/api/health.py` | Health + liveness endpoints |
| `backend/app/api/router.py` | Aggregated API router |
| `backend/app/config/__init__.py` | Config package |
| `backend/app/config/settings.py` | Pydantic `Settings` + `get_settings()` |
| `backend/app/config/logging_config.py` | `configure_logging()` (plain / JSON) |
| `backend/app/database/__init__.py` | Database package |
| `backend/app/database/base.py` | SQLAlchemy `Base` |
| `backend/app/database/session.py` | Lazy engine, session factory, `get_db`, `check_database_connection` |
| `backend/app/models/__init__.py` | Placeholder (ORM models) |
| `backend/app/schemas/__init__.py` | Placeholder (Pydantic schemas) |
| `backend/app/services/__init__.py` | Placeholder (services) |
| `backend/app/agents/__init__.py` | Placeholder (agents) |
| `backend/app/orchestration/__init__.py` | Placeholder (LangGraph) |
| `backend/app/tools/__init__.py` | Placeholder (deterministic tools) |
| `backend/app/integrations/__init__.py` | Placeholder (external APIs / SAP) |
| `backend/app/utils/__init__.py` | Placeholder (helpers) |
| `backend/tests/__init__.py` | Test package |
| `backend/tests/test_health.py` | 4 tests for root + health endpoints |

### Created — backend (Step 1)

| File | Purpose |
| --- | --- |
| `backend/app/services/gemini_service.py` | Gemini REST client: structured JSON, retries, loud failure, no mock fallback |
| `backend/app/schemas/disruption_schemas.py` | `DisruptionReport` / `LLMAssessment` / `DisruptionAssessment` + enums |
| `backend/app/services/risk_scoring.py` | Deterministic weighted risk scoring + severity bands |
| `backend/app/services/supply_chain_repository.py` | `Protocol` + PostgreSQL reference validation (shipments/suppliers/locations) |
| `backend/app/services/reference_data.py` | Demo master-data definitions + idempotent seed/clear helpers |
| `backend/app/models/supply_chain.py` | `Supplier` and `Shipment` ORM models |
| `backend/app/agents/disruption_sensing.py` | Disruption Sensing Agent (LLM analysis + deterministic post-processing) |
| `backend/scripts/seed_reference_data.py` | Runnable seeder for the live PostgreSQL instance |
| `backend/tests/fakes.py` | `StubGeminiService` + `InMemorySupplyChainRepository` |
| `backend/tests/test_gemini_service.py` | Gemini client tests (httpx `MockTransport`) |
| `backend/tests/test_risk_scoring.py` | Scoring table / band / cap tests |
| `backend/tests/test_supply_chain_repository.py` | Repository validation tests (skips without PostgreSQL) |
| `backend/tests/test_disruption_sensing.py` | Five required scenarios + opt-in live test |

### Modified — backend (Step 1)

| File | Change |
| --- | --- |
| `backend/app/config/settings.py` | Added `DATABASE_URL` (+ URI normalisation) and the verified Gemini block |
| `backend/app/models/__init__.py` | Imports `Shipment`/`Supplier` so `Base.metadata` is populated |
| `backend/.env.example`, `.env.example` | Document `DATABASE_URL` and the Gemini model/limits; note retired models |

### Created — backend (Step 2 — external tools)

| File | Purpose |
| --- | --- |
| `backend/app/integrations/base.py` | Connector contract: `Provenance`, `HttpJsonClient`, `Connector`/`BaseConnector`/`MockConnector`/`HttpConnector`, `stable_seed`, error hierarchy |
| `backend/app/integrations/weather.py` | Weather alerts connector (reference implementation) |
| `backend/app/integrations/news.py` | News headlines connector |
| `backend/app/integrations/maritime_alerts.py` | Maritime security / navigation alerts connector |
| `backend/app/integrations/port_congestion.py` | Port congestion connector (`congestion_level_for`) |
| `backend/app/integrations/tariffs.py` | Tariff / duty connector |
| `backend/app/integrations/suppliers.py` | Supplier master-data connector |
| `backend/app/integrations/carriers.py` | Carrier service catalogue connector |
| `backend/app/integrations/shipment_tracking.py` | Shipment tracking connector |
| `backend/app/integrations/mapping.py` | Route distance / reference transit connector |
| `backend/app/integrations/sap.py` | **Read-only** SAP connector (simulated + live adapters) |

### Created — backend (Step 2 — deterministic engines)

| File | Purpose |
| --- | --- |
| `backend/app/tools/base.py` | Engine contract: `EngineResult`, `ToolInputError`, `require_*` guards, scoring/rounding helpers |
| `backend/app/tools/risk.py` | Risk-scoring tools entry point (delegates to the Step 1 engine) |
| `backend/app/tools/costing.py` | Cost Calculation Engine |
| `backend/app/tools/route_optimization.py` | Route Optimization Engine |
| `backend/app/tools/lead_time.py` | Lead-Time Estimation Engine |
| `backend/app/tools/inventory.py` | Inventory Calculation Engine |
| `backend/app/tools/safety_stock.py` | Safety Stock Calculation Engine |
| `backend/app/tools/supplier_ranking.py` | Supplier Ranking Engine (configurable weights) |
| `backend/app/tools/compliance.py` | Compliance Rules Engine (specific violations) |
| `backend/app/tools/budget.py` | Budget Validation Engine |
| `backend/app/tools/approval.py` | Approval Management Engine (decides, never executes) |

### Created — backend tests (Step 2)

| File | Purpose |
| --- | --- |
| `backend/tests/test_integrations.py` | 62 tests: labelled-simulated contract, determinism, congestion bands, live adapters (MockTransport) |
| `backend/tests/test_risk_tool.py` | Risk tools entry point delegates exactly |
| `backend/tests/test_route_optimization.py` | Route ranking tests |
| `backend/tests/test_lead_time.py` | Lead-time tests |
| `backend/tests/test_inventory.py` | Inventory tests |
| `backend/tests/test_supplier_ranking.py` | Supplier ranking tests |
| `backend/tests/test_budget.py` | Budget validation tests |
| `backend/tests/test_approval.py` | Approval management tests |

### Modified — backend (Step 2)

| File | Change |
| --- | --- |
| `backend/app/config/settings.py` | Added the Step 2 integration block (`INTEGRATION_*` + weather/news/maritime/congestion/tariff/supplier/carrier/tracking/mapping base-URL + key pairs) |
| `backend/app/integrations/__init__.py` | Docstring rewritten to index the 10 connector modules + shared contract |
| `backend/app/tools/__init__.py` | Docstring rewritten to index the 10 engines + shared contract |

### Created — backend (Step 3 — remaining four AI agents)

| File | Purpose |
| --- | --- |
| `backend/app/agents/scenario_planning.py` | Agent 2 — Scenario Planning (composes Agents 3 & 4; ranks with `rank_routes`) |
| `backend/app/agents/rerouting_logistics.py` | Agent 3 — Rerouting & Logistics (ranked carrier options) |
| `backend/app/agents/inventory_rebalancing.py` | Agent 4 — Inventory Rebalancing (safety-stock-preserving transfers) |
| `backend/app/agents/compliance_audit.py` | Agent 5 — Compliance & Audit (deterministic verdict + evidence trail) |
| `backend/app/schemas/scenario_schemas.py` | `ScenarioRequest` / `ScenarioComparison` / `ScenarioPlan` + `ScenarioFeasibility` |
| `backend/app/schemas/rerouting_schemas.py` | `ReroutingRequest` / `ReroutingOption` / `ReroutingAnalysis` |
| `backend/app/schemas/rebalancing_schemas.py` | `RebalancingRequest` / `RebalancingPlan` / transfer + warehouse models |
| `backend/app/schemas/audit_schemas.py` | `AuditRequest` / `AuditReport` / `AuditEvidence` + `AuditVerdict` |

### Created — backend tests (Step 3)

| File | Purpose |
| --- | --- |
| `backend/tests/test_rerouting_logistics.py` | Agent 3: deterministic ranking, incumbent rank, mode filter, no route invented, gaps, provenance, model-cannot-change, failure paths (11 + 1 live) |
| `backend/tests/test_inventory_rebalancing.py` | Agent 4: surplus-only transfers, committed exclusion, calculated safety stock, no-shortage, single-plant, provenance, failure paths (14 + 1 live) |
| `backend/tests/test_compliance_audit.py` | Agent 5: verdict derivation, no verdict field in schema, three verdict values, empty rule set, evidence rows, gaps, failure paths (16 + 1 live) |
| `backend/tests/test_scenario_planning.py` | Agent 2: SC1/SC2/SC3 construction, deterministic re-ranking, feasibility tiering, assessment folding, Agent 3/4 composition, failure paths (16 + 1 live) |

### Modified — backend (Step 3)

| File | Change |
| --- | --- |
| `backend/tests/fakes.py` | Added the Step 3 connector doubles (`FakeMappingConnector`, `FakeCarrierConnector`, `FakeSAPConnector`) + `make_provenance` / `make_carrier_service` / `make_inventory_item`; docstring rewritten |
| `backend/app/agents/scenario_planning.py` | Fixed a dead-code defect: `_attach_assessments` was defined but never called, so the model's per-scenario assessments were discarded. Now called after `_narrate`. |
| `backend/app/integrations/sap.py` | Added two multi-plant rows to `_SAMPLE_INVENTORY` so Agent 4 can demonstrate a real cross-plant transfer |

### Created — backend (Step 4 — LangGraph supervisor and orchestration)

| File | Purpose |
| --- | --- |
| `backend/app/orchestration/state.py` | Shared `WorkflowState` + `RecoveryRequest` / `SupervisorDecision` / `RecoveryRecommendation` + node ids, `STATUS_*`, default rules |
| `backend/app/orchestration/checkpointing.py` | In-memory + PostgreSQL checkpointers and the libpq DSN derivation |
| `backend/app/orchestration/workflow.py` | Compiled supervisor graph (supervisor + 5 agents + approval gate + error handler + finalize) |
| `backend/app/api/orchestration.py` | Orchestration HTTP router (invoke / resume / state) |
| `backend/docs/workflow.md` | Mermaid workflow visualisation + node table + decisions and bounds |
| `backend/tests/test_orchestration.py` | 20 tests: the six roadmap scenarios, interrupt/resume, JSON state, iteration bound, Mermaid, opt-in live |

### Modified — backend (Step 4)

| File | Change |
| --- | --- |
| `backend/requirements.txt` | Added `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary]` |
| `backend/app/orchestration/__init__.py` | Re-exports the orchestration API (was a Step 0 placeholder) |
| `backend/app/api/router.py` | Registered the orchestration router |

### Created — backend (Step 5 — collaboration and replanning)

| File | Purpose |
| --- | --- |
| `backend/app/schemas/collaboration_schemas.py` | `AgentTask`, `ToolInvocation`, `AgentExecution`, `ScenarioEvaluation`, `ScenarioScreening`, `ScenarioHistoryEntry`, `ReplanningRecord`, `ToolCallStatus`, `ExecutionStatus` |
| `backend/app/utils/tool_recording.py` | `ToolCallRecorder`, `call_recorded`, `RecordingConnector` / `wrap_connector`, `record_tool_call`, result mocks/summaries |
| `backend/app/orchestration/collaboration.py` | Deterministic collaboration helpers + `MAX_REPLAN_ROUNDS`, `AGENT_TOOLS`, `AGENT_OBJECTIVES` |
| `backend/docs/collaboration.md` | Collaboration record, screening, feedback loop, bounds, new status |
| `backend/tests/test_collaboration.py` | 14 tests: tasks ↔ decisions, tool recording, screening, one bounded revision with history, no-compliant recovery, unavailable tools, retries, JSON round-trip |

### Modified — backend (Step 5)

| File | Change |
| --- | --- |
| `backend/app/orchestration/state.py` | Added `STATUS_NO_COMPLIANT_RECOVERY`; `RecoveryRecommendation` gained the collaboration record fields; `WorkflowState` gained `tasks`, `agent_executions`, `scenario_history`, `replanning`, `skipped_agents` (accumulating) and `scenario_screening`, `scenario_revision`, `replan_rounds` (control) |
| `backend/app/orchestration/workflow.py` | Issues `AgentTask`s, wraps executions in a `ToolCallRecorder`, records `AgentExecution`s (completed/failed/skipped), screens `ScenarioPlan`s, opens the bounded replanning loop, records skipped agents, populates the final collaboration record |
| `backend/app/orchestration/__init__.py` | Re-exports the collaboration helpers, `MAX_REPLAN_ROUNDS`, `AGENT_TOOLS`, `AGENT_OBJECTIVES`, `STATUS_NO_COMPLIANT_RECOVERY` |
| `backend/app/api/orchestration.py` | Response now also returns `agent_executions`, `scenario_screening`, `replanning`, `replanning_rounds`, `skipped_agents` |
| `backend/app/schemas/scenario_schemas.py` | `ScenarioRevision` added; `ScenarioPlan` gained `revision_round` and `rejected_scenario_ids` |
| `backend/app/agents/scenario_planning.py` | `plan(request, revision=None)` applies revisions deterministically, records tool calls and reports an unavailable inventory integration as a gap instead of raising |
| `backend/app/agents/disruption_sensing.py` | Wraps the repository snapshot, risk engine and Gemini call with `call_recorded` |
| `backend/app/agents/rerouting_logistics.py` | Wraps `rank_routes` and the Gemini call with `call_recorded` |
| `backend/app/agents/inventory_rebalancing.py` | Wraps the inventory/safety-stock engines and the Gemini call with `call_recorded` |
| `backend/app/agents/compliance_audit.py` | Wraps the compliance, budget and approval engines and the Gemini call with `call_recorded` |

### Created — backend (Step 6 — human approval and authorized execution)

| File | Purpose |
| --- | --- |
| `backend/app/schemas/approval_schemas.py` | `ProposalSnapshot` + version, `ApproverIdentity` / `ApproverRole`, decision request/record/outcome, `ApprovalRequestView` |
| `backend/app/schemas/execution_schemas.py` | `ExecutionAction`, `ExecutionReport`, `ExecutionActionType` / `Status`, `ExecutionRunStatus` |
| `backend/app/models/approvals.py` | `ApprovalRequestRow` (`approval_requests`) |
| `backend/app/services/approval_auth.py` | Credential parsing, constant-time authentication, role hierarchy, bearer parsing |
| `backend/app/services/approval_repository.py` | Queue protocol, Postgres + in-memory repositories, `ensure_approval_schema` |
| `backend/app/services/approval_service.py` | Authenticate → validate version → authorize → resume → record → execute coordinator |
| `backend/app/services/execution.py` | Execution plan, simulated/live adapters, idempotent `ExecutionService` |
| `backend/app/orchestration/approvals.py` | Proposal snapshot/version, resume payload, decision parsing, bounded modification revisions |
| `backend/app/api/approvals.py` | Authenticated approval API and error mapping |
| `backend/docs/approval-and-execution.md` | Approval, versioning, execution and API reference |
| `backend/tests/test_approvals.py` | 50 Step 6 tests |

### Modified — backend (Step 6)

| File | Change |
| --- | --- |
| `backend/app/orchestration/state.py` | `RecoveryRecommendation` gained `proposal_version` and `approval_history`; `WorkflowState` gained accumulating `approval_history` and `modification_rounds` |
| `backend/app/orchestration/workflow.py` | Gate publishes the proposal version, accepts authenticated/legacy payloads, records identity/timestamp/history, supports the bounded modification loop; `finalize` adds `proposal_version` and `approval_history` |
| `backend/app/orchestration/__init__.py` | Re-exports the approval helpers and `MAX_MODIFICATION_ROUNDS` |
| `backend/app/config/settings.py` | Added `APPROVER_CREDENTIALS`, `EXECUTION_USE_MOCK`, `EXECUTION_BASE_URL` / `CLIENT_ID` / `CLIENT_SECRET`, timeout/attempts and derived properties |
| `backend/app/integrations/base.py` | Added `post_json` with `Idempotency-Key`; the retry transport now handles GET and POST |
| `backend/app/api/orchestration.py` | Removed the unauthenticated resume endpoint, records the pending approval on interrupt, serialises `proposal_version` / `approval` / `approval_history` / `modification_rounds` |
| `backend/app/api/router.py` | Registered the approvals router |
| `backend/app/main.py` | Ensures the approval schema exists at startup when the database is reachable |
| `backend/app/models/__init__.py`, `backend/app/schemas/__init__.py` | Export/register the new modules |
| `backend/.env.example`, `.env.example` (root) | Documented `APPROVER_CREDENTIALS` and `EXECUTION_*` (names only) |

### Created — backend (Step 7 — SAP integration)

| File | Purpose |
| --- | --- |
| `backend/app/integrations/sap_profiles.py` | Prepared profiles (S/4HANA, Business Accelerator Hub, BTP, Integration Suite), capability paths and `resolve_sap_profile` |
| `backend/app/integrations/sap_auth.py` | `SAPOAuthTokenProvider`, `SAPHttpClient`, `sap_token_provider`, `redact_headers` |
| `backend/app/integrations/sap_write.py` | Approval evidence, validated write requests, simulated + live write connectors, idempotency, `get_sap_write_connector` |
| `backend/docs/sap-integration.md` | Step 7 reference and limitations |
| `backend/tests/test_sap_integration.py` | 37 Step 7 tests |

### Modified — backend (Step 7)

| File | Change |
| --- | --- |
| `backend/app/integrations/sap.py` | Added `SAPMaterial`, sample material master, `list_materials`/`get_material`; live adapter now uses the selected profile's read paths and optional OAuth |
| `backend/app/integrations/base.py` | `IntegrationRequestError.status_code`; honours numeric `Retry-After` (max 30s) on retryable responses |
| `backend/app/integrations/__init__.py` | Docstring indexes the Step 7 modules |
| `backend/app/config/settings.py` | Added `SAP_API_FAMILY`, `SAP_AUTH_URL`, `SAP_READ_SCOPE`, `SAP_WRITE_SCOPE`, `SAP_WRITE_ENABLED` and `sap_oauth_configured` |
| `backend/.env.example`, `.env.example` (root) | Documented the new SAP variables (names and safe defaults only) |

### Created — backend (Step 8 — dashboard)

| File | Purpose |
| --- | --- |
| `backend/app/models/workflow_runs.py` | `WorkflowRunRow` — one row per thread with summary columns and full `state_json` |
| `backend/app/services/workflow_history.py` | Run recording, listing, detail, disruption view, status counts, `json_safe`, schema ensure |
| `backend/app/services/dashboard_service.py` | Overview KPIs/latest runs/data sources and shipment listing |
| `backend/app/api/dashboard.py` | Read-only dashboard router (six GET endpoints) |
| `backend/docs/dashboard.md` | Step 8 reference and verification limitations |
| `backend/tests/test_dashboard.py` | 12 Step 8 tests |

### Modified — backend (Step 8)

| File | Change |
| --- | --- |
| `backend/app/api/router.py` | Registered the dashboard router |
| `backend/app/api/orchestration.py` | Records the workflow run after every invocation (including failures) |
| `backend/app/api/approvals.py` | Refreshes the recorded run after an authenticated decision |
| `backend/app/main.py` | Ensures the `workflow_runs` schema exists at startup alongside the approval schema |

### Created / modified — frontend (Step 8)

| File | Change |
| --- | --- |
| `frontend/src/pages/Overview.jsx` | Rewritten: KPI tiles, status chart, pipeline, latest runs, data-source notes |
| `frontend/src/pages/AgentActivity.jsx` | Rewritten: run selector, supervisor trail, five agent cards, React Flow graph, timeline, tools, handoffs, replanning, errors; accepts `onOpenThread` for cross-page navigation |
| `frontend/src/pages/ScenarioComparison.jsx` | Rewritten: scenario table, comparison detail, screening/replanning history |
| `frontend/src/pages/ApprovalCenter.jsx` | Rewritten: token gate, queue, impact tiles, agent validations, controls, history, execution report |
| `frontend/src/pages/DisruptionMonitoring.jsx` | Rewritten: disruption list and assessment/decision detail |
| `frontend/src/pages/ShipmentManagement.jsx` | Rewritten: shipment table with search/status filters |
| `frontend/src/pages/InventoryManagement.jsx` | Rewritten: inventory positions, materials, `[SIMULATED]` provenance banner |
| `frontend/src/pages/AuditHistory.jsx` | Rewritten: recorded run history with decision and approval detail |
| `frontend/src/components/AgentWorkflowGraph.jsx` | React Flow graph from recorded executions |
| `frontend/src/components/BarChart.jsx`, `KpiCard.jsx`, `PageHeader.jsx`, `RunSelector.jsx`, `StatePanel.jsx` | Shared dashboard components |
| `frontend/src/hooks/useAsyncData.js` | Loading/error/reload hook for read-only endpoints |
| `frontend/src/constants/domain.js` | Agent ids/labels, status tones, navigation metadata |
| `frontend/src/utils/format.js` | Money/percent/date/title formatting |
| `frontend/src/layouts/AppLayout.jsx` | Numbered sidebar (01–08), sticky topbar, mobile drawer |
| `frontend/src/App.jsx` | Eight-page shell with shared run selection and cross-page navigation |
| `frontend/src/services/api.js` | Dashboard reads and workflow endpoint |
| `frontend/src/index.css` | Full control-tower theme rewrite (~1,300 lines) and responsive breakpoints |
| `frontend/package.json` | Added `@xyflow/react` 13.0.2 |

### Created / modified — frontend (Step 6)

| File | Change |
| --- | --- |
| `frontend/src/pages/ApprovalCenter.jsx` | Approval interface: token, pending queue, proposal/version/reasons/violations, decision history, decisions and execution report |
| `frontend/src/App.jsx` | Overview / Approval Center tabs |
| `frontend/src/services/api.js` | Bearer-token helper, approval endpoints and a header-merge fix so caller headers cannot drop auth |
| `frontend/src/index.css` | Tabs, token form, fields, detail grids, decision/outcome and table styles |

### Created — frontend

| File | Purpose |
| --- | --- |
| `frontend/` (scaffold) | Vite + React 19 project |
| `frontend/.env.example` | Frontend environment template |
| `frontend/vite.config.js` | Dev server port 5173 + `/api` proxy to backend |
| `frontend/index.html` | Title / metadata |
| `frontend/src/App.jsx` | Renders `AppLayout` + `Overview` |
| `frontend/src/layouts/AppLayout.jsx` | Header / content / footer shell |
| `frontend/src/pages/Overview.jsx` | Backend connectivity overview page |
| `frontend/src/components/StatusBadge.jsx` | Status pill component |
| `frontend/src/hooks/useHealthCheck.js` | Health-check hook |
| `frontend/src/services/api.js` | Backend API client (`/api` base URL) |
| `frontend/src/index.css` | Enterprise dark control-tower theme |
| `frontend/src/assets/.gitkeep` | Keeps the assets directory tracked |

### Created / updated — repository root

| File | Purpose |
| --- | --- |
| `README.md` | Full setup / run / test documentation |
| `.gitignore` | Python + Node + env + OS ignores |
| `.env.example` | Repository-level environment template |
| `PROJECT_PROGRESS.md` | This recovery file |
| `DEVELOPMENT_LOG.md` | Chronological development log |
| `TASK_CHECKLIST.md` | Roadmap task checklist |

### Deleted

| File | Reason |
| --- | --- |
| `frontend/src/App.css` | Replaced by the shared `src/index.css` theme |
| `frontend/src/assets/hero.png`, `react.svg`, `vite.svg` | Unused Vite scaffold assets |
| `frontend/public/icons.svg` | Only referenced by the removed scaffold `App.jsx` |

---

## 7. Packages installed

Virtual environment: `d:\X Factor\.venv` (Python 3.14.10).

Verified installed versions:

| Package | Version |
| --- | --- |
| fastapi | 0.165.0 |
| uvicorn | 0.54.0 |
| pydantic | 2.14.4 |
| pydantic-settings | 2.16.3 |
| sqlalchemy | 2.1.9 |
| psycopg2-binary | 2.9.13 |
| httpx | 0.28.1 |
| python-json-logger | 4.2.0 |
| python-dotenv | 1.2.4 |
| pytest | 9.2.0 |
| starlette | 1.10.0 |
| langgraph | 1.2.24 |
| langgraph-checkpoint-postgres | 3.2.1 |
| langgraph-checkpoint | 4.3.2 |
| langgraph-prebuilt | 1.1.3 |
| langchain-core | 1.8.4 |
| psycopg | 3.3.9 (+ `psycopg-binary`) |
| psycopg-pool | (installed with the above) |

Frontend: React 19.3.1, react-dom 19.3.1, Vite 8.3.8, `@vitejs/plugin-react` 6.1.2,
`@xyflow/react` 13.0.2 (Step 8), oxlint 1.90.0.

Step 5 added **no new packages** — it reuses LangGraph, Pydantic and the existing
Step 1/2 layers.

Step 6 added **no new packages** — approval persistence uses the existing
SQLAlchemy/PostgreSQL layer, authentication uses the standard-library `secrets`
module, execution reuses `httpx` through the Step 2 `HttpConnector`, and the API
reuses FastAPI/Starlette security primitives.

Step 7 added **no new packages** — the OAuth token client uses the installed
`httpx`, and profiles, validation and redaction use Pydantic and the standard
library.

Step 8 added **no backend packages**. The frontend added **`@xyflow/react`
13.0.2** for the agent workflow graph; everything else reuses React, the existing
Vite setup and plain CSS.

---

## 8. Environment variables configured

Only **names** are recorded here — no secret values are ever stored.

`APP_NAME`, `APP_VERSION`, `APP_ENV`, `DEBUG`, `LOG_LEVEL`, `LOG_JSON`,
`API_PREFIX`, `CORS_ORIGINS`, `DATABASE_URL`, `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_CONNECT_TIMEOUT`,
`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS`,
`GEMINI_MAX_OUTPUT_TOKENS`, `GEMINI_API_BASE`, `LANGGRAPH_MAX_ITERATIONS`,
`LANGGRAPH_CHECKPOINT_BACKEND`, `SAP_BASE_URL`, `SAP_CLIENT_ID`,
`SAP_CLIENT_SECRET`, `SAP_USE_MOCK`, `VITE_API_BASE_URL` (frontend).

Added in Step 2: `INTEGRATION_TIMEOUT_SECONDS`, `INTEGRATION_MAX_ATTEMPTS`, and one
`*_API_BASE_URL` / `*_API_KEY` pair each for `WEATHER_*`, `NEWS_*`,
`MARITIME_ALERTS_*`, `PORT_CONGESTION_*`, `TARIFF_*`, `SUPPLIER_*`, `CARRIER_*`,
`SHIPMENT_TRACKING_*` and `MAPPING_*`. All of these default to empty, which is what
makes the connector factories fall back to the clearly labelled simulated adapters.
No paid external-data credentials are configured, so every external connector
currently returns simulated data.

Added in Step 6: `APPROVER_CREDENTIALS` (comma-separated `token:approver_id:Role`
entries, names only — never committed), `EXECUTION_USE_MOCK`, `EXECUTION_BASE_URL`,
`EXECUTION_CLIENT_ID`, `EXECUTION_CLIENT_SECRET`, `EXECUTION_TIMEOUT_SECONDS` and
`EXECUTION_MAX_ATTEMPTS`. `APPROVER_CREDENTIALS` has no default, so every approval
endpoint fails closed with `503` until an operator configures it; execution is
simulated by default (`EXECUTION_USE_MOCK=true`) and the live executor raises
`IntegrationNotConfiguredError` (mapped to `503`) if mock mode is off without a
base URL.

Added in Step 7: `SAP_API_FAMILY` (default `s4hana`), `SAP_AUTH_URL`,
`SAP_READ_SCOPE` (default `sap.read`), `SAP_WRITE_SCOPE` (default `sap.write`) and
`SAP_WRITE_ENABLED` (default `false`). `SAP_BASE_URL`, `SAP_CLIENT_ID`,
`SAP_CLIENT_SECRET` and `SAP_USE_MOCK` remain from Step 2. `SAP_WRITE_ENABLED`
being false means writes fail closed even when read access is configured; no SAP
tenant is contacted while `SAP_USE_MOCK=true`.

Real credentials **are** now configured in `backend/.env` (git-ignored and not
committed): an Aiven PostgreSQL `DATABASE_URL` (`sslmode=require`) and a live
`GEMINI_API_KEY`. Only `.env.example` templates (names + safe defaults) are
tracked. `DATABASE_URL`, when set, takes precedence over the discrete
`POSTGRES_*` parts and is normalised from `postgres://` / `postgresql://` to
`postgresql+psycopg2://` for the driver.

---

## 9. Commands required to run the project

```powershell
# Backend
cd "d:\X Factor\backend"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Seed demo reference data (suppliers + shipments) — run once per database
cd "d:\X Factor\backend"
..\.venv\Scripts\python.exe -m scripts.seed_reference_data

# Backend test-suite
cd "d:\X Factor\backend"
..\.venv\Scripts\python.exe -m pytest -q

# Frontend
cd "d:\X Factor\frontend"
npm run dev
```

- Frontend: http://localhost:5173
- Backend: http://127.0.0.1:8000 (docs at `/docs`)

---

## 10. Tests performed and results

| Test | Command | Result |
| --- | --- | --- |
| Backend unit tests (full suite) | `..\.venv\Scripts\python.exe -m pytest` (in `backend/`) | ✅ **370 tests collected; 364 passed, 6 skipped in 9.74s** (the 5 opt-in `RUN_LIVE_GEMINI=1` agent tests + 1 live supervisor test skip by default; repository tests skip when PostgreSQL is down) |
| Step 8 dashboard tests | `pytest tests/test_dashboard.py` | ✅ **12 passed** (summary derivation, one-row upsert, ordering/status filter, disruption detail, JSON-safe interrupt stripping, overview counts, run/detail endpoints incl. 404, shipment and inventory payloads, run recorded on workflow start, dashboard routes mounted) |
| Step 7 SAP integration tests | `pytest tests/test_sap_integration.py` | ✅ **37 passed** (four API profiles and env selection, undeclared-capability refusal, OAuth2 client-credentials form + token caching, secret never echoed in an error body, no token/secret in logs, header redaction, bearer replaces `x-api-key`, material master reads, profile-aware read paths, 404 → `None`, read connector has no write methods, request validation, approval evidence from approve/reject, keyword-only evidence, deterministic simulated writes for all three write types, literal idempotency key, fail-closed write permission, live writer requires credentials, read/write scope and permission separation, rejected vs failed classification, `Retry-After` honoured, approved-vs-rejected end to end) |
| Step 6 approval + execution tests | `pytest tests/test_approvals.py` | ✅ **50 passed** (proposal versioning, credential parsing, authentication and role hierarchy, bearer parsing, legacy and Step 6 payloads, approve/reject identity + timestamp + history, bounded modification loop, execution plan/keys/labelling/replay/refusal, partial + failed reports, live adapter via `httpx.MockTransport`, repository semantics in memory and SQLite, API 401/403/409/503 including approve → execute → duplicate prevention and the modification round-trip) |
| Step 5 collaboration tests | `pytest tests/test_collaboration.py` | ✅ **14 passed** (tasks ↔ decisions, tool-call recording, deterministic screening, one bounded revision preserving history, no-compliant recovery, unavailable tools, retries, JSON round-trip) |
| **Live Gemini through the supervisor (Step 5)** | `$env:RUN_LIVE_GEMINI="1"; pytest tests/test_orchestration.py -k live` | ✅ **1 passed** — real Gemini reasoning through the new tool-recording wrappers |
| Step 4 orchestration tests | `pytest tests/test_orchestration.py` | ✅ **19 passed, 1 skipped** (six roadmap scenarios, interrupt/resume, JSON state contract, iteration bound, Mermaid export, opt-in live) |
| Orchestration + approval API route check | `app.openapi()["paths"]` | ✅ `/api/orchestration/workflows`, `…/{thread_id}/state` and `/api/approvals/pending`, `…/{thread_id}`, `…/{thread_id}/decision`, `…/{thread_id}/execution` mounted; the unauthenticated `…/{thread_id}/resume` route is gone |
| Step 4 smoke run | `python xf_step4_smoke.py` | ✅ exit 0 — direct path, no-carrier path, High-severity path, full Mermaid source |
| **Live PostgreSQL checkpoint** | `open_checkpointer(backend="postgres")` smoke | ✅ opened against the live Aiven database, `setup()` ran, a checkpoint was written and read back (`{'n': 21, 'doubled': 42}`) |
| Step 3 agent tests (Agents 2–5) | `pytest tests/test_rerouting_logistics.py tests/test_inventory_rebalancing.py tests/test_compliance_audit.py tests/test_scenario_planning.py` | ✅ **57 passed, 4 skipped** (deterministic numbers, schema cannot carry a verdict/number, model cannot change the decision, failure paths) |
| External connector tests | `pytest tests/test_integrations.py` | ✅ **62 passed** (labelled-simulated contract, determinism, congestion bands, live adapters via `httpx.MockTransport`) |
| Deterministic engine tests | `pytest tests/test_costing.py tests/test_safety_stock.py tests/test_compliance.py tests/test_risk_tool.py tests/test_route_optimization.py tests/test_lead_time.py tests/test_inventory.py tests/test_supplier_ranking.py tests/test_budget.py tests/test_approval.py` | ✅ passed |
| Gemini client tests | `pytest tests/test_gemini_service.py` | ✅ passed (MockTransport; retry + failure paths) |
| Deterministic scoring tests | `pytest tests/test_risk_scoring.py` | ✅ passed |
| Repository validation tests | `pytest tests/test_supply_chain_repository.py` | ✅ passed (live PostgreSQL) |
| Disruption agent scenarios | `pytest tests/test_disruption_sensing.py` | ✅ passed (5 scenarios + validation) |
| **Live Gemini + PostgreSQL** | `$env:RUN_LIVE_GEMINI="1"; pytest tests/test_disruption_sensing.py -k live` | ✅ **1 passed** |
| Reference-data seed | `python -m scripts.seed_reference_data` (in `backend/`) | ✅ 5 suppliers, 10 shipments |
| Backend live health | `GET http://127.0.0.1:8000/api/health` | ✅ `200` `{"status":"ok", …, "database":"connected"}` |
| JSON logging mode | `configure_logging('INFO', True)` smoke test | ✅ Emitted valid JSON |
| Backend service index | `GET http://127.0.0.1:8000/` | ✅ `200` with docs/health links |
| Liveness probe | `GET http://127.0.0.1:8000/api/health/live` | ✅ `{"status":"ok"}` |
| Frontend production build | `npm run build` | ✅ **57 modules transformed; 555.19 kB JS, 40.68 kB CSS; built in 330 ms** (includes the eight dashboard pages and the React Flow graph) |
| Frontend lint | `npm run lint` | ✅ **0 errors, 2 pre-existing warnings** (`useAsyncData` non-literal deps, `useHealthCheck` setState-in-effect) |
| Frontend serves | `GET http://localhost:5173/` | ✅ `200`, title `X FACTOR — Supply Chain Resilience` |
| **Frontend → backend proxy** | `GET http://localhost:5173/api/health` | ✅ `200` proxied backend JSON |

---

## 11. Known bugs, limitations and unresolved issues

1. **PostgreSQL is connected.** Step 1 was completed against a live managed
   (Aiven) PostgreSQL instance over TLS (`sslmode=require`, host
   `pg-1a479fbd-…aivencloud.com:14157`, database `defaultdb`). Verified via
   `check_database_connection()` → `True` and a live health check reporting
   `"database": "connected"`. The earlier local-`localhost:5432` plan was
   superseded by the supplied remote URI.
2. **Gemini is configured and live.** `GEMINI_API_KEY` is set in `backend/.env`
   and verified with a live `generateContent` call.
   **Important model fact:** `gemini-1.5-*` and `gemini-2.5-*` now return
   **404 "no longer available to new users"** for this key. The working default is
   **`gemini-3.5-flash`** (verified `200` with a valid `responseSchema` reply).
   `gemini-3.8-flash` / `gemini-flash-latest` returned transient `503 high demand`
   and are not used as defaults. If the model is retired again, update
   `GEMINI_MODEL` in `backend/.env`.
3. **SAP credentials not configured** — `SAP_USE_MOCK=true` by default. Step 7
   delivered the modular read connector and the separate, permission-gated write
   connector, but both are validated against the labelled simulated adapters
   only: no SAP sandbox or tenant has been contacted. The Step 2 `SAPConnector`
   remains **read-only**; writes live in `sap_write.py` and require approval
   evidence, `SAP_WRITE_ENABLED=true` and configured credentials. Supplying
   `SAP_BASE_URL`, `SAP_CLIENT_ID`/`SAP_CLIENT_SECRET` (or `SAP_AUTH_URL` for
   OAuth2) and `SAP_USE_MOCK=false` switches a profile to live with no code
   change.
4. **No external-data API credentials are configured.** Every Step 2 external
   connector (weather, news, maritime, congestion, tariff, supplier, carrier,
   tracking, mapping) therefore returns **simulated** data, marked `is_mock=True`
   with a `[SIMULATED]` provenance label. The live adapters are implemented and
   unit-tested via `httpx.MockTransport`; supplying a `*_API_BASE_URL` / key in
   `backend/.env` switches a connector to live with no code change. No paid
   credentials were purchased, so the platform never presents simulated data as
   live.
5. **Vite binds to `localhost` (IPv6 `::1`)** — reach the dev server via
   `http://localhost:5173`, not `http://127.0.0.1:5173`.
6. **Deprecation warning in tests:** Starlette 1.10 warns that using `httpx` with
   `starlette.testclient` is deprecated (suggests `httpx2`). Non-blocking; will be
   revisited during Step 9 if it becomes a failure.
7. **Reference data is explicit demo seed data**, not live SAP master data
   (5 suppliers / 10 shipments). This is labelled as such in
   `app/services/reference_data.py`; the Step 2 SAP connector reuses the same
   masters so the connector and the seeded rows always agree.
8. **LangGraph is now installed (Step 4).** The supervisor layer uses LangGraph
   1.2.24 with `langgraph-checkpoint-postgres` and `psycopg[binary]`. The earlier
   Step 1 note ("LangGraph deliberately not installed yet") is superseded: it was
   deferred until the step that needs it, to honour "do not add unnecessary
   packages".
9. **Steps 9–10 not started** — intentional, per the roadmap rule not to proceed
   automatically. Step 8 is complete: the `workflow_runs` registry records every
   supervisor run (failures included), a read-only dashboard API serves it, and
   all eight control-tower pages are wired to real endpoints with loading, error
   and empty states. Steps 0–7 are unchanged and re-verified by their own tests
   (364 passed across the full suite).
10. **Postgres checkpoint tables are created on first use.** `postgres_checkpointer()`
    calls `saver.setup()` (idempotent) when the workflow is built with the default
    `LANGGRAPH_CHECKPOINT_BACKEND=postgres`; a database must be reachable for that
    path. Tests use the in-memory checkpointer and need no database.
11. **Approver credentials are not configured by default.** `APPROVER_CREDENTIALS`
    is deliberately unset in the templates, so every `/api/approvals/*` endpoint
    returns `503` until an operator supplies token entries. This is the intended
    fail-closed behaviour, not a defect; the test suite injects a test authorizer
    through FastAPI dependency overrides and never needs a real credential.
12. **Execution is simulated by default and no execution gateway is configured.**
    `EXECUTION_USE_MOCK=true` routes every action to `SimulatedExecutionAdapter`,
    which returns `SIM-…` references and `[SIMULATED]` messages. The live
    `HttpExecutionAdapter` is implemented and unit-tested via `httpx.MockTransport`
    but has never been pointed at a real endpoint. The Step 7 SAP write connector
    exists but is not yet wired into this execution path (see §11 item 15).
13. **The Approval Center's populated path has not been exercised in a browser.**
    The Step 8 browser walkthrough covered the missing-token, invalid-token
    (`503`) and empty-queue states. Approving a real proposal requires a paused
    successful run and `APPROVER_CREDENTIALS`; the live Gemini quota blocked the
    former on 2026-11-22 (see item 17). The API paths remain covered by the
    Step 6 tests and the UI state machine is the same code that renders the
    fail-closed states.
14. **SAP write paths are prepared defaults, not tenant-verified.** The paths in
    `app/integrations/sap_profiles.py` (e.g.
    `/sap/opu/odata/sap/API_SHIPMENT_SRV/…`) are the conventional shapes for each
    API family, but no SAP system has validated them. The real OData service
    names, transport (v2/v4/REST) and write entitlements must be confirmed against
    an actual sandbox before `SAP_USE_MOCK=false` is used for writes.
15. **SAP writes are not yet invoked from the approval/execution path.** The
    write connector and its approval bridge (`approval_evidence_from_decision`)
    are implemented and tested, but Step 6's `ProposalSnapshot` carries no
    shipment or plant identifiers, so linking an approved proposal to a concrete
    SAP write request belongs to a later step. No operational identifier was
    invented just to force the connection.
16. **SAP OAuth scopes are declared, not granted.** `SAP_READ_SCOPE` /
    `SAP_WRITE_SCOPE` are sent as requested scopes (`sap.read`, `sap.write` by
    default), but whether a tenant's client credentials are entitled to them is
    unknown until a live token exchange is attempted. A scope rejection surfaces
    as an `IntegrationNotConfiguredError`/`IntegrationRequestError`, never as
    silent fallback to mock data.
17. **Live Gemini quota blocked a successful Step 8 browser verification.**
    On 2026-11-22 the verification workflow returned `GeminiRequestError:
    HTTP 503 UNAVAILABLE`, and an immediate retry returned `429` —
    `generate_content_free_tier_requests, limit: 5`. Both runs were recorded as
    genuine failures (`EV-UI-VERIFY-001`, `EV-UI-VERIFY-002`). Consequently the
    **populated successful** Scenario Comparison and Approval Center views have
    not been seen in a browser; everything else (Overview, shipments, inventory,
    disruptions, Agent Activity with a failed run, audit list, fail-closed
    approval states) was browser-verified. The backend request/response paths are
    covered by tests. No success was simulated to mask the gap.
18. **Two verification runs remain in the shared Aiven database.** They are real
    failed runs (`EV-UI-VERIFY-*`) and the dashboard displays them honestly. They
    were not deleted because removing rows from the shared database is a
    destructive action that was not authorised. They can be removed later with
    an explicit data-cleanup decision.
19. **Desktop-width visual checking is limited.** The in-app browser viewport was
    roughly 498×570 and screenshots occasionally reported
    `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`; verification therefore relied on
    accessibility snapshots plus a few successful screenshots. The CSS defines
    breakpoints at 1180/1024/760/480 px, but a full desktop-width visual pass
    belongs to Step 9.

---

## 12. Exact next action

**Start Step 9 — Testing and End-to-End Validation.**

Step 8 is complete and verified (see §3, §10 and `backend/docs/dashboard.md`):
the `workflow_runs` registry records every run, a read-only `/api/dashboard/*`
API serves the recorded state, and eight control-tower pages render it with
loading, error and empty states. No new decision logic was introduced. Step 9
should now verify the whole product end to end rather than add features:

1. **Golden path** — Mumbai → Rotterdam pharmaceutical maritime disruption
   through ingest → sensing → risk → supervisor → scenario planning → rerouting
   → inventory → compliance → approval → authorised simulated execution.
2. **Failure tests** — Gemini unavailable/quota (already observed: `503`/`429`),
   external API timeout, invalid agent output, missing route, no feasible
   recovery — each ending in an honest status, never a fabricated success.
3. **Browser completion** — the populated successful Scenario Comparison and
   Approval Center views that Gemini quota blocked on 2026-11-22, plus a
   desktop-width visual pass.
4. **Data cleanup decision** — whether to remove the `EV-UI-VERIFY-*` failed
   runs from the shared database (destructive; needs explicit approval).

Deferred to a later step (recorded in §11): invoking SAP writes from the
approval/execution path once proposals carry shipment and plant identifiers.

**Credentials available (recorded 2026-11-22) — do not re-ask:**

1. **Gemini API key:** configured and verified live (`GEMINI_MODEL=gemini-3.5-flash`).
2. **PostgreSQL:** the live managed (Aiven) `DATABASE_URL` is configured and
   seeded with demo reference data; the supervisor's Postgres checkpointer uses it
   and the `approval_requests` table is created on startup.
3. **Approver credentials:** not configured. `APPROVER_CREDENTIALS` must be set
   before any approval endpoint will accept a request (otherwise `503`); this is
   the intended fail-closed behaviour and needs nothing from the developer unless
   a manual demo is requested.
4. **External-data API credentials:** none. This is expected — every Step 2
   connector falls back to clearly labelled simulated data, which is the
   deliberate design. No action is required from the developer.
5. **SAP credentials:** none. `SAP_USE_MOCK=true` and `SAP_WRITE_ENABLED=false`
   stay in effect, so both SAP reads and writes use the labelled simulated
   adapters; no action is required unless live sandbox credentials are supplied
   (then set `SAP_BASE_URL`, `SAP_CLIENT_ID`/`SAP_CLIENT_SECRET`, optionally
   `SAP_AUTH_URL`, and `SAP_USE_MOCK=false`, and confirm the paths in
   `sap_profiles.py`).

---

## 13. Important architectural decisions

1. **Lazy database engine.** `create_engine` runs only on first use, so importing
   the app never requires PostgreSQL. A missing/unreachable database degrades the
   health endpoint instead of crashing the process.
2. **`APP_*` prefixed settings** kept short (`APP_NAME`, `APP_ENV`, …) while
   third-party vars match their service names (`POSTGRES_*`, `GEMINI_*`, `SAP_*`)
   for readability.
3. **CORS origins as a comma-separated string** (`CORS_ORIGINS`) rather than a
   JSON list, to avoid brittle `.env` parsing; exposed to code via the
   `cors_origins` property.
4. **Vite dev proxy for `/api`** instead of hard-coding the backend host in the
   frontend; keeps CORS out of the dev loop and avoids exposing config to the
   browser.
5. **Single shared stylesheet** (`src/index.css`) with CSS custom properties for
   the theme, to keep Step 0 lean; component-level styling can be added in Step 8.
6. **All secrets via environment variables only** — never in frontend code, never
   committed. Only `.env.example` (names + safe defaults) is tracked.
7. **`LOG_JSON` toggle** — human-readable logs in development, structured JSON for
   container/production deployments.
8. **LLM/deterministic boundary (Step 1).** `LLMAssessment` intentionally has no
   `risk_score`/`severity` field, so the model *cannot* return them; scoring and
   reference validation are pure Python. The LLM reports only observable
   `RiskFactor`s and geography.
9. **Repository `Protocol` over a concrete class.** The agent depends on a
   `SupplyChainRepository` protocol, so it is fully testable against an in-memory
   fake while production uses `PostgresSupplyChainRepository`.
10. **Fail loudly, never fake reasoning.** `GeminiService` raises
    `GeminiNotConfiguredError` when the key is missing and `GeminiRequestError`
    on unreachable/invalid responses — there is no silent mock-LLM fallback
    (rule 12 is honoured by the explicitly labelled demo *data* seed, not by
    faking *reasoning*).
11. **Provenance is part of every external record (Step 2).** Each connector
    returns models carrying a frozen `Provenance` whose `is_mock` flag and
    `[SIMULATED]` label make simulated data impossible to mistake for live data.
    The factories return a simulated adapter only when no base URL is configured;
    the live adapters raise `IntegrationNotConfiguredError` instead of degrading
    into sample data.
12. **Deterministic by construction (Step 2).** Every engine does plain
    arithmetic — no network, database or LLM call — validates its inputs with
    `ToolInputError`, and returns a frozen `EngineResult` that documents its
    `assumptions: tuple[str, ...]`. Simulated sample data is derived from
    `stable_seed()` (SHA-1), never randomly, so demos and tests are repeatable.
13. **One source of truth for the risk model (Step 2).** `app.tools.risk` is a
    thin, documented delegate to `app.services.risk_scoring`; the weight table,
    severity bands and 100-point cap stay in one file. `route_optimization.py`
    reuses the costing, lead-time and risk engines rather than re-deriving
    anything, and maps raw factor strings to `RiskFactor` members before scoring.
14. **Compliance cannot be overridden (Step 2).** `validate_compliance` returns
    specific rule violations and raises `ToolInputError` when given no applicable
    rules — it refuses to declare a proposal compliant without deterministic
    validation, so no LLM can talk its way past it later.
15. **SAP access is read-only in Step 2.** `SAPConnector` defines read methods
    only (shipments, suppliers, inventory, purchase orders). Operational writes
    are deferred to Step 6 (approved execution) and Step 7.
16. **`Protocol`-based interfaces throughout (Step 2).** Connectors and engines
    depend on protocols (`SupplyChainRepository`, `WeatherConnector`,
    `MappingConnector`, …), so production uses a concrete adapter while tests
    inject fakes/`httpx.MockTransport` without any network or database.
17. **The schema is the enforcement (Step 3).** Each agent hands Gemini an
    OpenAPI-subset `*_SCHEMA` that simply **omits** every decision-bearing and
    number-bearing field (`verdict`, `rank`, `weighted_score`, `total_cost_usd`,
    `transfer_recommendations`, …). The model therefore *structurally cannot*
    return them; a malformed reply is wrapped in a per-agent
    `RuntimeError` subclass (e.g. `ComplianceAuditError`) rather than silently
    dropped.
18. **Deterministic post-processing after the LLM call (Step 3).** After the
    narrative is validated, each agent adds the facts only code can see — the
    incumbent route rank, feasibility tiers, deterministic gaps — before the
    result model is built. The narrative is never the source of a decision.
19. **Agents compose through their public entry points (Step 3).** Agent 2 holds
    injected `ReroutingLogisticsAgent` / `InventoryRebalancingAgent` instances and
    calls `analyse()` / `plan()`, so composition is testable by substituting the
    sub-agents — the agents do not reach into each other's internals, and the
    supervisor (Step 4) can reuse the same entry points.
20. **Safety stock is preserved by arithmetic (Step 3).** Agent 4 only ever
    releases stock **above** a source plant's safety stock and excludes committed
    stock from the available balance — the roadmap rule is enforced by the
    allocation maths, and refused sources are reported as `RejectedTransfer`s
    rather than dropped.
21. **The supervisor decides from structured state, not a transcript (Step 4).**
    Every branch reads validated results (assessment shipment count, scenario
    feasibility, audit verdict) and records a `SupervisorDecision(step, action,
    reason)`, so the workflow is auditable after the fact and needs no
    conversational memory. This is the roadmap's "never blindly execute a fixed
    sequence" rule.
22. **State is JSON, not live objects (Step 4).** Agent outputs are stored with
    `model_dump(mode="json")` and re-validated on read. That keeps the whole state
    serializable, which is exactly what the PostgreSQL checkpointer persists, and
    avoids LangGraph's "deserializing unregistered type" warning path.
23. **No double-invocation (Step 4).** Because `ScenarioPlanningAgent` already
    composes the rerouting and inventory agents, the supervisor runs the standalone
    nodes only where no scenario comparison is warranted (or as the single bounded
    scenario revision) — asserted by a test on the Gemini call count.
24. **Bounded, non-retryable-aware retries (Step 4).** Each agent is attempted at
    most twice and the whole loop is bounded by `LANGGRAPH_MAX_ITERATIONS × 5`;
    hard failures (`GeminiNotConfiguredError`, `IntegrationNotConfiguredError`,
    `ToolInputError`, base `ValidationError`) are never retried. A later failure
    never discards earlier agent work.
25. **Checkpointing is typed by adapter (Step 4).** The app's SQLAlchemy engine and
    the LangGraph checkpoint adapter use different Postgres drivers (psycopg2 vs
    psycopg 3), so `checkpointer_dsn()` normalises the URL rather than sharing one
    engine — keeping the live ORM layer and the checkpoint layer independent.
26. **Collaboration is recorded, never narrated (Step 5).** An `AgentTask` exists
    only when the supervisor actually selected that node, an `AgentExecution` only
    when the node ran, and a `ToolInvocation` is written by the tool itself. There
    is no simulated inter-agent dialogue; the audit trail is the executed call
    graph.
27. **Tool recording is transparent and inert by default (Step 5).** Connectors are
    observed through a proxy that forwards every call unchanged and records only
    the observation; engines and Gemini use `call_recorded`, which re-raises
    unchanged. With no recorder active the helpers are no-ops, so unit tests that
    call an agent directly behave exactly as before.
28. **Screening reuses the audit engines (Step 5).** The supervisor evaluates a
    scenario plan with the same `validate_compliance` / `validate_budget` /
    `evaluate_approval` calls and the same verdict derivation as Agent 5, so a plan
    that passes screening cannot later fail the audit; replanning triggers only on
    a genuine deterministic rejection.
29. **Replanning is bounded and always preserves history (Step 5).**
    `MAX_REPLAN_ROUNDS = 2` caps the loop, revisions exclude rejected alternatives
    without inventing replacements, and every replaced plan is stored as a
    `ScenarioHistoryEntry` plus a `ReplanningRecord`. An empty revised plan ends in
    `STATUS_NO_COMPLIANT_RECOVERY` instead of spinning; the Step 4 iteration bound
    remains a second guard.
30. **Unavailable tools degrade honestly (Step 5).** `IntegrationNotConfiguredError`
    is recorded as an `unavailable` tool call; the optional inventory node becomes a
    `SKIPPED` execution (agent added to `skipped_agents`, gap recorded) and scenario
    planning continues without inventory data. An absent integration never becomes
    simulated data and never fails the whole run.
31. **The decision is bound to a proposal version (Step 6).** `proposal_version` is
    a SHA-256 digest of canonical JSON excluding only `thread_id`, the version
    itself and `created_at`, so the graph and the API independently derive the same
    value and any operational change yields a different one. A decision whose
    submitted version no longer matches both the stored item and the workflow's
    current snapshot is rejected with `409`, which prevents an approval of an
    outdated plan being executed.
32. **Authentication fails closed (Step 6).** The request body carries no approver
    identity and no approval flag; identity comes only from a bearer token matched
    with `secrets.compare_digest` against `APPROVER_CREDENTIALS`. Missing or
    malformed configuration makes every approval endpoint return `503` rather than
    defaulting to allow, and an unknown approval level is treated as Admin-only,
    not as Manager.
33. **Execution is idempotent by key (Step 6).** Every action is keyed
    `thread_id:proposal_version:action_type`. `ExecutionService` replays a stored
    report instead of re-executing, and refuses any proposal that is unapproved,
    unversioned or untraceable to a workflow thread — so a retried frontend click
    or a duplicate resume cannot double-apply a shipment or inventory change.
34. **Modifications are bounded and reopen only on a new version (Step 6).**
    `MAX_MODIFICATION_ROUNDS = 2` caps the human feedback loop; each revision
    excludes the rejected recommendation, preserves history, and pauses again on a
    new proposal version. Exceeding the bound closes the workflow as
    `approval_rejected` instead of looping, mirroring the Step 5 replanning bound.
35. **The approval queue is persisted, not in-memory (Step 6).** One row per thread
    (`approval_requests`) holds the current proposal, version, level, status,
    decision-history JSON and execution report, so a decision can be taken in a
    different process from the one that interrupted the run. A new version starts a
    new pending review and clears the old execution report; re-recording an
    already-decided version never reopens it.
36. **Execution defaults to a labelled simulator (Step 6).** `EXECUTION_USE_MOCK`
    defaults to true, so the platform never claims a real shipment or SAP change;
    the live adapter is the same `httpx` transport as the Step 2 connectors and
    raises `IntegrationNotConfiguredError` (mapped to `503`) when it is enabled
    without a base URL.
37. **SAP API families are configuration, not subclasses (Step 7).** One frozen
    `SAPApiProfile` record holds each family's transport, authentication style,
    read paths and write paths; `SAP_API_FAMILY` selects it at runtime. Adding or
    correcting a family is a data change in `sap_profiles.py`, not a new connector
    class, and an undeclared capability fails loudly instead of guessing a path.
38. **The read connector stays read-only (Step 7).** `SAPConnector` still defines
    no write method — the Step 2 regression test that forbids them passes
    unchanged. Writes live in `sap_write.py` behind their own protocol, so a read
    credential cannot be used to mutate anything even by mistake.
39. **Read and write are separately permissioned and configured (Step 7).**
    Reads use `SAP_READ_SCOPE`/`SAP_CLIENT_SECRET`; writes need
    `SAP_WRITE_ENABLED=true`, a profile that declares the capability, the
    `SAP_WRITE_SCOPE` token and approval evidence. `SAP_WRITE_ENABLED` defaults to
    false, so the write surface is fail-closed and must be deliberately opened.
40. **Approval evidence is mandatory and typed (Step 7).** Every write takes a
    keyword-only `SAPApprovalEvidence` whose validator accepts only
    `ApprovalAction.APPROVE`; `approval_evidence_from_decision` refuses a
    rejected or modification decision. There is no code path that reaches an SAP
    write without a recorded human approval, its role, thread and proposal
    version.
41. **Writes are idempotent per proposal version (Step 7).** The key
    `sap:{thread_id}:{proposal_version}:{request_type}:{request_id}` is sent as
    `Idempotency-Key` and embedded in the payload, so a retried submission cannot
    create a duplicate transfer or plan update. Results are typed
    (`accepted`/`simulated`/`rejected`/`failed`); a 400/409/422 is `rejected`, a
    timeout/5xx is `failed`, and neither is reported as applied.
42. **No live SAP is claimed (Step 7).** `SAP_USE_MOCK=true` is the default; every
    simulated read record and write result carries `is_mock=True` and a
    `[SIMULATED]` message/provenance. The live paths are plausible defaults, but
    the docs state plainly that they, the scopes and the write entitlements are
    unverified because no tenant has been contacted.
43. **`workflow_runs` is a projection, not a second source of truth (Step 8).**
    One row per thread stores queryable summaries plus the full JSON-safe state so
    the dashboard never has to replay checkpoints. The LangGraph checkpoint remains
    authoritative for resuming; if the projection and checkpoint ever diverge, the
    checkpoint wins and the row is rewritten on the next invocation or decision.
44. **History recording is best-effort and never load-bearing (Step 8).** A
    dashboard write failure is logged, rolled back and swallowed; it cannot lose a
    completed workflow result or fail an approval decision. This mirrors the
    platform rule that observability must not break the operation it observes.
45. **The dashboard is strictly read-only (Step 8).** `/api/dashboard/*` exposes
    GET endpoints only and recomputes no verdict, score or recommendation. It
    renders the stored `SupervisorDecision`, `AgentExecution`, `ToolInvocation`,
    screening, replanning and approval records verbatim, so the UI can never
    disagree with the deterministic engines.
46. **The agent graph is drawn from recorded executions (Step 8).** The React Flow
    view is generated from the run's actual `agent_executions`, not from a static
    diagram with animated "active" agents. An agent that was skipped or never
    delegated is drawn in that state, and a failed node shows its recorded error.
47. **Dashboard data provenance is carried through, not flattened (Step 8).**
    Shipments state that they are seeded PostgreSQL demo rows; inventory returns
    the SAP connector's `is_mock`, `source` and `endpoint` and the UI shows a
    `[SIMULATED]` banner when mock mode is on. The dashboard adds no independent
    claim that data is live.
48. **Empty and failed are first-class UI states (Step 8).** The API returns empty
    lists rather than placeholder rows, and every page renders loading, error and
    empty states explicitly. A failed run is displayed with its recorded error and
    status — never replaced by a sample success for demonstration purposes.
