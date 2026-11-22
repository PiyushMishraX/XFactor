# X FACTOR — PROJECT PROGRESS (Recovery File)

> Update this file immediately after **every** meaningful implementation milestone.
> Never rely on conversation history to remember completed work.

_Last updated: 2026-11-22 (Step 4 complete)_

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
| Current phase | **Step 4 — LangGraph Supervisor and Orchestration** |
| Status | ✅ **Complete and verified** |
| Overall completion (estimate) | **~55%** (Steps 0–4 of 11 roadmap steps) |
| Next step | **Step 5 — Multi-Agent Collaboration and Autonomous Replanning** |

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
| 5 | Multi-agent collaboration + autonomous replanning | Not started |
| 6 | Human-in-the-loop and authorised execution | Not started |
| 7 | SAP integration | Not started |
| 8 | Agent Activity and Decision dashboard | Not started |
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
oxlint 1.90.0 (24 packages installed, 0 vulnerabilities).

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
| Backend unit tests (full suite) | `..\.venv\Scripts\python.exe -m pytest` (in `backend/`) | ✅ **257 tests collected; 251 passed, 6 skipped** (the 5 opt-in `RUN_LIVE_GEMINI=1` agent tests + 1 live supervisor test skip by default; repository tests skip when PostgreSQL is down) |
| Step 4 orchestration tests | `pytest tests/test_orchestration.py` | ✅ **19 passed, 1 skipped** (six roadmap scenarios, interrupt/resume, JSON state contract, iteration bound, Mermaid export, opt-in live) |
| Orchestration API route check | `app.openapi()["paths"]` | ✅ `/api/orchestration/workflows`, `…/{thread_id}/resume`, `…/{thread_id}/state` mounted |
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
| Frontend production build | `npm run build` | ✅ 21 modules, built OK |
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
3. **SAP credentials not configured** — `SAP_USE_MOCK=true` by default. The Step 2
   `SAPConnector` is **read-only** and returns clearly labelled simulated data
   while mock mode is on; real SAP read/write integration is Step 7 (writes are
   additionally gated by Step 6 approval).
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
9. **Steps 5–10 not started** — intentional, per the roadmap rule not to proceed
   automatically. Step 4 is complete: the supervisor graph is built, tested and
   reachable over HTTP, and a run can be paused at the approval gate and resumed
   from its checkpoint. Step 5 (multi-agent collaboration and autonomous
   replanning) builds on this graph rather than replacing it.
10. **Postgres checkpoint tables are created on first use.** `postgres_checkpointer()`
    calls `saver.setup()` (idempotent) when the workflow is built with the default
    `LANGGRAPH_CHECKPOINT_BACKEND=postgres`; a database must be reachable for that
    path. Tests use the in-memory checkpointer and need no database.

---

## 12. Exact next action

**Start Step 5 — Multi-Agent Collaboration and Autonomous Replanning.**

Step 4 is complete and verified (see §3 and §10). The five specialised agents are
now wired into one compiled LangGraph graph with a dynamic supervisor, an approval
gate, error handling and PostgreSQL-backed checkpointing, and the graph is
reachable over HTTP (`/api/orchestration/...`). Step 5 extends that graph — it does
not replace it:

1. **Dynamic task delegation** and structured inter-agent communication.
2. **Feedback loops and conditional replanning** when an agent result is
   unsatisfactory.
3. **Tool selection** and handling of unavailable tools.
4. **Failure recovery** beyond the current single bounded retry.
5. **Scenario comparison** and preserving previous scenario results while
   replanning.
6. **Bounded autonomous iteration** — no infinite loops.
7. **Track agent execution history** and why the supervisor selected each agent.
8. **No fabricated agent messages** — interactions must reflect executed
   functions.

The Step 4 supervisor already records a per-pass `SupervisorDecision(step, action,
reason)` and an execution history, so Step 5 builds on real, auditable data.

**Credentials available (recorded 2026-11-22) — do not re-ask:**

1. **Gemini API key:** configured and verified live (`GEMINI_MODEL=gemini-3.5-flash`).
2. **PostgreSQL:** the live managed (Aiven) `DATABASE_URL` is configured and
   seeded with demo reference data; the supervisor's Postgres checkpointer uses it.
3. **External-data API credentials:** none. This is expected — every Step 2
   connector falls back to clearly labelled simulated data, which is the
   deliberate design. No action is required from the developer.

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
