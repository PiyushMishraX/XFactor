# X FACTOR — DEVELOPMENT LOG

Chronological record of development. Newest entries at the bottom.

---

## 2026-11-22 — Session 1: Repository audit and Step 0

### Repository audit (session recovery protocol)

**Findings before any code was written:**

- The project root contained **only documentation**: `MASTER_INSTRUCTIONS.txt`,
  `DEVELOPMENT_ROADMAP.txt` (identical to `xFactor.md`), and five **empty** files:
  `PROJECT_PROGRESS.md`, `DEVELOPMENT_LOG.md`, `TASK_CHECKLIST.md`, `README.md`,
  `.env.example`, `.gitignore`.
- **No `backend/` or `frontend/` directory existed. No source code existed.**
- **No git repository** (`git log` → `fatal: not a git repository`).
- **No prior session memory** for this project.
- **Toolchain:** Python 3.14.10, Node v24.14.1, npm 11.11.0.

**Conclusion:** Nothing had been implemented. The first incomplete task is
**Step 0 — Project Initialization and Architecture**. No completed work needed
re-verifying because no work existed.

---

### Step 0 — Project Initialization and Architecture

**Work completed**

1. Created the backend directory layout exactly as specified in the roadmap.
2. Created a Vite + React 19 frontend (`npx create-vite@latest frontend --template react`).
3. **FastAPI** application with a lifespan startup/shutdown hook.
4. **PostgreSQL** configuration using a *lazily created* SQLAlchemy engine so a
   missing database never prevents application start.
5. **Pydantic settings** (`app/config/settings.py`) reading from environment
   variables and an optional `.env` file, with derived `database_url`,
   `cors_origins`, `gemini_configured` and `sap_configured` helpers.
6. **Health-check endpoints**: `/api/health` (service + database status) and
   `/api/health/live` (dependency-free liveness probe).
7. **CORS** middleware driven by the `CORS_ORIGINS` setting.
8. **Logging**: a single `configure_logging()` entry point supporting
   human-readable output (development) and structured JSON (production).
9. **Error handling**: a catch-all exception handler that logs the failure and
   returns a generic `500` payload.
10. **Configuration placeholders** for Gemini, LangGraph and SAP integration.
11. **`.env.example`** templates for backend, frontend and repository root.
12. **`.gitignore`** covering Python, Node, virtual environments, env files, logs
    and OS/editor artefacts.
13. **README.md** written from scratch with architecture, structure, setup, run
    and test instructions.
14. Frontend restructured into the required `components/ pages/ services/ hooks/
    layouts/ assets/` layout, wired to the backend through a Vite `/api` proxy.

**Important implementation decisions**

- **No AI agents, tools or orchestration were implemented** — Step 0 explicitly
  forbids them, and the roadmap requires one step at a time.
- Added only packages needed for Step 0 plus the testing framework. Gemini /
  LangGraph packages are deliberately **not** installed yet; they are added in
  the step that uses them, to honour "do not add unnecessary packages".
- The database health check catches all exceptions so an unreachable database
  degrades a status field rather than crashing the app or failing tests.
- `CORS_ORIGINS` is a comma-separated string (not a JSON list) to keep `.env`
  parsing predictable.
- The frontend talks to the backend through the Vite dev proxy instead of a
  hard-coded host, avoiding CORS friction during development.
- Unused Vite scaffold files were deleted rather than left in the tree.

**Files created / modified / deleted**

- See `PROJECT_PROGRESS.md` §6 for the full file manifest.
- Nothing was modified destructively; three unused scaffold files and one
  scaffold stylesheet were deleted.

**Dependencies installed**

- Python (in `.venv`): fastapi 0.165.0, uvicorn 0.54.0, pydantic 2.14.4,
  pydantic-settings 2.16.3, sqlalchemy 2.1.9, psycopg2-binary 2.9.13,
  httpx 0.28.1, python-json-logger 4.2.0, python-dotenv 1.2.4, pytest 9.2.0.
- Node: React 19.3.1, react-dom 19.3.1, Vite 8.3.8, @vitejs/plugin-react 6.1.2,
  oxlint 1.90.0 (24 packages, 0 vulnerabilities).

**Tests and results**

| Check | Result |
| --- | --- |
| `python -m pytest -v` (backend) | ✅ 4 passed |
| JSON logging smoke test | ✅ valid JSON emitted |
| Live `GET /api/health` | ✅ 200 |
| Live `GET /` | ✅ 200 |
| Live `GET /api/health/live` | ✅ 200 |
| `npm run build` | ✅ built in 330 ms |
| `GET http://localhost:5173/` | ✅ 200 |
| `GET http://localhost:5173/api/health` (Vite proxy) | ✅ 200, backend JSON |

**Problems encountered and their solutions**

1. **Python 3.14 is very new**, so package compatibility was a risk. *Solution:*
   installed the dependency set up-front and confirmed wheels exist for
   `pydantic-core`, `sqlalchemy` and `psycopg2-binary` on cp314. No source builds
   were required.
2. **`python-json-logger` 4.x changed its import path.** *Solution:* used
   `from pythonjsonlogger import json as json_logger` and verified the JSON
   formatter works with a smoke test.
3. **PowerShell quoting broke inline Python during verification.** *Solution:*
   switched the live checks to `curl.exe`.
4. **`127.0.0.1:5173` refused connections while `Get-NetTCPConnection` reported
   the port as listening.** *Cause:* Vite binds to `localhost`, which resolves to
   IPv6 `::1` on this machine. *Solution:* verify the dev server via
   `http://localhost:5173`; this is documented in the README.
5. **Backgrounded `Start-Process` servers were killed when the shell exited.**
   *Solution:* ran start → wait-for-port → request → cleanup inside a single
   command for deterministic verification.
6. **PostgreSQL rejects connections** (`fe_sendauth: no password supplied`).
   No credentials are configured yet. *Handled by design:* the app starts anyway
   and reports `"database": "unavailable"`. Must be resolved before database work.

**Remaining work**

- Step 1 and beyond (see `TASK_CHECKLIST.md`).

---

### Developer decisions recorded (end of Step 0)

Asked the developer the two questions the master instructions require before
Step 1, and recorded the answers in `PROJECT_PROGRESS.md` §12:

1. **Gemini API key — available.** The developer will supply it in
   `backend/.env`; Step 1 will therefore use **real Gemini reasoning** rather than
   a mock LLM.
2. **PostgreSQL — use a dedicated local dev database** (`xfactor` with a known dev
   user), configured through `POSTGRES_*` in `backend/.env`.

**Open blocker:** the local PostgreSQL instance rejects connections with
`fe_sendauth: no password supplied` and its superuser credentials are not known,
so the dev database cannot be created automatically. The exact `CREATE USER` /
`CREATE DATABASE` statements are documented in `PROJECT_PROGRESS.md` §12 for the
developer to run.

No code changes were made after this decision; Step 0 remains the last completed
step and Step 1 has **not** been started, per the roadmap rule "do not proceed to
the next step automatically".

---

## 2026-11-22 — Session 2: Step 1 — Gemini Integration and Disruption Sensing Agent

### Starting point (session-recovery protocol)

Resumed from `PROJECT_PROGRESS.md`. Step 0 was verified complete, so Step 1 was
the first incomplete task. Before writing code the existing Step 0 files were
re-inspected (nothing was rebuilt) and the credentials the developer supplied
were used directly.

### Credential resolution

1. **`backend/.env` was 0 bytes on disk** — the editor buffer had never been
   flushed, so `pydantic-settings` silently fell back to `localhost:5432`. The
   canonical `backend/.env` was written with the supplied Aiven connection string.
2. **`POSTGRES_DB`** was clarified: it is the database *name* (the last path
   segment of the URL). The Aiven URI ends in `/defaultdb`, so `POSTGRES_DB` was
   set to `defaultdb` to agree with the URI that takes precedence.
3. **TLS + timeout:** the remote host needs `sslmode=require`, and
   `DB_CONNECT_TIMEOUT` was raised from 3 → 10 to survive the remote handshake.
4. **Gemini model churn was discovered empirically:** `gemini-1.5-*` and
   `gemini-2.5-*` return **404 "no longer available to new users"** for this key;
   `gemini-3.8-flash` / `gemini-flash-latest` returned transient **503 high
   demand**. `gemini-3.5-flash` returned `200` with a valid `responseSchema`
   reply and was adopted as the default everywhere.

### Work completed

1. **`app/services/gemini_service.py`** — REST `generateContent` client using
   `responseMimeType: application/json` + `responseSchema`, `thinkingBudget: 0`,
   retry with back-off on `429/500/502/503/504`, and a loud, actionable failure
   when `GEMINI_API_KEY` is missing or the reply is unusable. No mock-reasoning
   fallback.
2. **`app/schemas/disruption_schemas.py`** — the three-layer contract:
   `DisruptionReport` (input), `LLMAssessment` (the only fields the model
   decides — deliberately **without** a risk score/severity), and
   `DisruptionAssessment` (validated output). Enums cover all 8 disruption
   categories + `Unrelated`, 5 severity bands and 12 `RiskFactor`s.
3. **`app/services/risk_scoring.py`** — deterministic scoring: a 12-row weight
   table (8–22 points), capped exposure points for validated shipments/suppliers,
   severity bands at 0/10/35/60/85, and a 100-point cap. Irrelevant reports
   short-circuit to 0.
4. **`app/models/supply_chain.py`** — `Supplier` and `Shipment` ORM models.
5. **`app/services/supply_chain_repository.py`** — a `Protocol` plus a PostgreSQL
   implementation that resolves LLM-claimed shipment/supplier ids and affected
   locations against real master data, and reports unknown ids as
   `unvalidated_*_references`.
6. **`app/agents/disruption_sensing.py`** — the Disruption Sensing Agent: Gemini
   call with a strict system instruction and response schema, then deterministic
   post-processing (scoring, reference validation, provenance, missing
   information, contradictions). Analysis only — it never executes an action.
7. **Demo reference data** — `app/services/reference_data.py` (5 suppliers,
   10 shipments, explicitly labelled demo data) and
   `scripts/seed_reference_data.py`, run against the live database.
8. **Tests** — `tests/fakes.py` (`StubGeminiService`,
   `InMemorySupplyChainRepository`) plus `test_gemini_service.py` (httpx
   `MockTransport`), `test_risk_scoring.py`,
   `test_supply_chain_repository.py` (skips without PostgreSQL) and
   `test_disruption_sensing.py` (the five required scenarios + an opt-in
   `RUN_LIVE_GEMINI=1` live test).

**Important implementation decisions**

- The LLM/deterministic split is enforced by the *schema*, not by convention:
  `LLMAssessment` has no score field, so the model cannot return one.
- Reference validation is a hard gate: only ids found in PostgreSQL can appear in
  `affected_shipments` / `affected_suppliers`; everything else is surfaced as
  unvalidated so nothing is silently invented.
- The source report is always prepended to the evidence list deterministically,
  so every assessment carries provenance even if the model omits citations.
- Rule 12 (mocks only when real access is unavailable) is honoured by labelling
  the *demo data* seed, not by faking LLM *reasoning*.
- LangGraph is **not** installed yet — the Gemini call uses the existing `httpx`
  and LangGraph is first needed in Step 4.

**Dependencies installed**

- None. Step 1 reuses already-installed packages (`httpx`, `pydantic`,
  `sqlalchemy`, `psycopg2-binary`).

**Tests and results**

| Check | Result |
| --- | --- |
| `python -m pytest -q` (full backend suite) | ✅ **59 passed, 1 skipped** |
| `RUN_LIVE_GEMINI=1 pytest tests/test_disruption_sensing.py -k live` | ✅ 1 passed (real Gemini + PostgreSQL) |
| `python -m scripts.seed_reference_data` | ✅ 5 suppliers, 10 shipments |
| Live `GET /api/health` | ✅ 200, `"database": "connected"` |

**Problems encountered and their solutions**

1. **`backend/.env` was empty on disk** → the app silently used defaults.
   *Solution:* wrote the canonical `.env`; confirmed with a debug script reading
   `dotenv_values()`.
2. **Retired Gemini models (404)** → *Solution:* probed candidates live and
   adopted `gemini-3.5-flash`.
3. **Remote TLS vs a 3-second connect timeout** → *Solution:* raised
   `DB_CONNECT_TIMEOUT` to 10.
4. **One test asserted the wrong severity band** (score 42 was expected to be
   HIGH but the pinned bands put 35–59 at MODERATE). *Solution:* corrected the
   test expectation — the implementation was right, the assertion was wrong.

**Remaining work**

- Step 2 and beyond (see `TASK_CHECKLIST.md`). Step 1 is complete and verified;
  the roadmap rule "do not proceed to the next step automatically" was observed.

---

## 2026-11-22 — Session 3: Step 2 — External Tools and Deterministic Business Logic

### Starting point (session-recovery protocol)

Resumed from `PROJECT_PROGRESS.md` §12, which listed the Step 2 sub-tasks. Step 1
was verified complete, so Step 2 was the first incomplete task. Nothing working
was rebuilt: `app/tools/` and `app/integrations/` were inspected first, and the
Step 1 risk engine (`app/services/risk_scoring.py`) was deliberately **reused, not
duplicated** — `app.tools.risk` is a thin delegate to it.

### Work completed

**Shared foundations (written and verified before the bulk work):**

1. **`app/integrations/base.py`** — the connector contract: `Provenance`
   (frozen, with `is_mock` + a `[SIMULATED]` `label`), `HttpJsonClient`
   (retries on `429/500/502/503/504`, `x-api-key` header, configurable timeout),
   the `Connector` protocol, `BaseConnector` / `MockConnector` / `HttpConnector`,
   `stable_seed()` for deterministic sample data, and the
   `IntegrationError` / `IntegrationNotConfiguredError` / `IntegrationRequestError`
   hierarchy.
2. **`app/tools/base.py`** — the engine contract: `EngineResult` (frozen, with an
   `assumptions` tuple), `ToolInputError`, the `require_*` guards and the
   normalisation / weighting / rounding helpers.
3. **Settings block** — `INTEGRATION_TIMEOUT_SECONDS`, `INTEGRATION_MAX_ATTEMPTS`
   and one `*_API_BASE_URL` / `*_API_KEY` pair per external source.
4. **Exemplar engines** verified by hand before the rest were built: `costing.py`
   (cost, 103810.0 for 11 000 km Sea / $1.25M / 7.5% tariff), `safety_stock.py`
   (146 / 986 at 95%), `compliance.py` (3 violations, approval required), and the
   reference **`weather.py` connector**.

**A. External connectors (`app/integrations/`)** — 10 modules, each mirroring the
weather reference shape (domain enum → record model with `provenance: Provenance`
→ `Protocol` → `Simulated*Connector` → `Live*Connector` → `get_*_connector()`
factory):

| Module | Interface |
| --- | --- |
| `weather.py` | `get_alerts(*, location)` |
| `news.py` | `get_headlines(*, query, limit=10)` |
| `maritime_alerts.py` | `get_alerts(*, region)` |
| `port_congestion.py` | `get_congestion(*, port)` — always exactly one record |
| `tariffs.py` | `get_rate(*, origin_country, destination_country, hs_code)` |
| `suppliers.py` | `get_profile(*, supplier_id)` (None if unknown) / `list_profiles()` |
| `carriers.py` | `list_services(*, transport_mode=None)` |
| `shipment_tracking.py` | `get_events(*, shipment_id)` |
| `mapping.py` | `get_route(*, origin, destination)` — `is_estimated` flag |
| `sap.py` | **read-only** `SAPConnector` (shipments/suppliers/inventory/POs) |

**B. Deterministic engines (`app/tools/`)** — 10 engines, all pure arithmetic with
no network/DB/LLM call: `risk.py` (delegates to the Step 1 engine), `costing.py`,
`route_optimization.py`, `lead_time.py`, `inventory.py`, `safety_stock.py`,
`supplier_ranking.py`, `compliance.py`, `budget.py`, `approval.py`.

**Tests** — `tests/test_integrations.py` (62 tests covering the simulated/labelled
contract, determinism, the congestion band thresholds and live mapping via
`httpx.MockTransport`) plus one test module per engine.

**Important implementation decisions**

- **Simulated data cannot masquerade as live data.** Every external record carries
  a frozen `Provenance` with `is_mock`; simulated adapters set it `True`, and the
  live adapters raise `IntegrationNotConfiguredError` rather than falling back to
  sample data. Sample values are derived via `stable_seed()` (SHA-1), never
  randomly.
- **All arithmetic is outside prompts.** Each engine validates inputs
  (`ToolInputError`) and returns a frozen Pydantic result that documents its
  `assumptions`.
- **The risk model lives in exactly one place.** `app.tools.risk` is a documented
  delegate to `app.services.risk_scoring`; no second weight table exists.
- **Compliance refuses to rubber-stamp.** `validate_compliance` raises
  `ToolInputError` if given no applicable rules — it will not declare a proposal
  compliant without deterministic validation.
- **SAP is read-only.** `SAPConnector` defines read methods only; the roadmap's
  SAP *write* operations belong to Step 6 (approved execution) and Step 7.
- **No new AI agents** were built, per the Step 2 checklist.

**Dependencies installed**

- None. Step 2 reuses `httpx`, `pydantic`, `sqlalchemy` and `psycopg2-binary`.

**Tests and results**

| Check | Result |
| --- | --- |
| `python -m pytest -q` (full backend suite) | ✅ **176 tests collected; all passing** (175 passed, 1 opt-in live test skipped with PostgreSQL up) |
| `pytest tests/test_integrations.py` | ✅ **62 passed** |
| Engine unit tests (costing, safety stock, compliance, risk, route optimisation, lead time, inventory, supplier ranking, budget, approval) | ✅ passed |

**Problems encountered and their solutions**

1. **A parallel sub-agent delegated the 9 remaining connectors and returned an
   empty result** — nothing had actually been written. *Solution:* re-inspected
   `app/integrations/` (only `base.py` + `weather.py` existed), then wrote the 9
   remaining connectors directly and verified them.
2. **The determinism tests compared whole models and failed.** *Cause:*
   `Provenance.retrieved_at` (and `observed_at` / tracking `occurred_at`) are
   stamped per call, so two calls are never byte-identical. *Solution:* the tests
   now compare the *deterministic* fields only (values, bands, statuses) — the
   timestamp is provenance metadata, not part of the answer.
3. **`pytest`'s final summary line is not captured by the shell.** *Cause:*
   terminal capture drops the last line. *Solution:* appended a marker command or
   used `--collect-only` to read the count reliably (176 collected).

**Remaining work**

- Step 3 (the four remaining agents) and beyond — see `TASK_CHECKLIST.md`. Step 2
  is complete and verified; the roadmap rule "do not proceed to the next step
  automatically" was observed.

---

## 2026-11-22 — Session 4: Step 3 — Build the Remaining Four AI Agents

### Starting point (session-recovery protocol)

Resumed from `PROJECT_PROGRESS.md` §12 and `TASK_CHECKLIST.md` Step 3. Steps 0–2
were verified complete, and the four new agent modules plus their schema modules
were already written, so no working component was rebuilt. The Step 3 work left to
do was **verification**: read every new agent and its deterministic dependencies to
confirm the LLM/deterministic split, fix the defects found, then write and run the
four test modules.

### Defects found and fixed

1. **`app/agents/scenario_planning.py` — dead code.** `_attach_assessments` was
   defined but never called, so the model's per-scenario assessments were validated
   and then silently discarded. Fixed by calling it immediately after `_narrate()`.
2. **`app/integrations/sap.py` — single-plant sample inventory.** Every material
   existed at exactly one plant, so Agent 4 could only ever emit the "only plant
   holding this material" gap and never demonstrate a real transfer. Fixed by
   adding two rows (MAT-PHARMA-001 @ Hamburg DC, MAT-ELEC-003 @ Singapore DC).
   Verified non-breaking: no test pins the row count, and `get_inventory_item()`
   still returns the first match.

### Work completed

**Test doubles** (`tests/fakes.py`): added `FakeMappingConnector`,
`FakeCarrierConnector`, `FakeSAPConnector` and the `make_provenance` /
`make_carrier_service` / `make_inventory_item` builders, so the four agents can be
driven end-to-end without any provider.

**Four test modules, one per agent:**

| Module | Agent | Result |
| --- | --- | --- |
| `tests/test_rerouting_logistics.py` | 3 — Rerouting & Logistics | ✅ 11 passed, 1 skipped |
| `tests/test_inventory_rebalancing.py` | 4 — Inventory Rebalancing | ✅ 14 passed, 1 skipped |
| `tests/test_compliance_audit.py` | 5 — Compliance & Audit | ✅ 16 passed, 1 skipped |
| `tests/test_scenario_planning.py` | 2 — Scenario Planning | ✅ 16 passed, 1 skipped |

Each module asserts the hand-computed engine numbers, that number/decision-bearing
fields are **absent** from the agent's Gemini schema, that "the model cannot change
the decision", plus malformed-output and missing-key failures, and an opt-in
`RUN_LIVE_GEMINI=1` test over the simulated connectors.

**Important implementation decisions**

- **The response schema is the enforcement.** Each agent's `*_SCHEMA` omits every
  field a decision depends on (`verdict`, `rank`, `weighted_score`,
  `total_cost_usd`, `transfer_recommendations`, …), so the model cannot return one
  even if it tries.
- **Deterministic post-processing runs after the narrative.** Incumbent route rank,
  feasibility tiers and gaps are computed in code, then attached; the model's
  per-scenario assessments are folded into the matching `ScenarioComparison.notes`.
- **Agent composition uses public entry points.** Agent 2 holds injected
  `ReroutingLogisticsAgent` / `InventoryRebalancingAgent` instances and calls
  `analyse()` / `plan()` — no reaching into internals, and the Step 4 supervisor
  can reuse the same entry points.
- **Safety stock is protected by arithmetic, not prompting.** Agent 4 releases
  only stock above a source's safety stock and excludes committed stock; refused
  sources are returned as `RejectedTransfer`s with a reason.
- **The supervisor was deliberately not built**, per the Step 3 checklist
  ("do not implement the central supervisor yet").

**Dependencies installed**

- None. Step 3 reuses `httpx`, `pydantic` and the Step 1/2 layers. LangGraph
  remains deferred to Step 4.

**Tests and results**

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite) | ✅ **232 passed, 5 skipped** (237 collected; the 5 skips are the opt-in `RUN_LIVE_GEMINI=1` tests) |
| The four Step 3 agent test modules | ✅ **57 passed, 4 skipped** |

**Problems encountered and their solutions**

1. **First Agent 2 run failed on `weighted_score`** — asserted `0.6056` where the
   engine returns `0.6556`. *Cause:* the reliability criterion is
   `(0.95-0.90)/(0.99-0.90) = 0.556`, not `0.056`. *Solution:* corrected the
   assertion — the implementation was right.
2. **`pytest`'s summary line is suppressed in this shell.** *Cause:* `pytest.ini`
   sets `addopts = -q`, and an extra `-q` on the command line makes it `-qq`, which
   drops the final counts line. *Solution:* run without the extra `-q` (or to a file)
   to read the counts reliably.

**Remaining work**

- Step 4 (LangGraph supervisor and orchestration) and beyond — see
  `TASK_CHECKLIST.md`. Step 3 is complete and verified; the roadmap rule "do not
  proceed to the next step automatically" was observed.

---

## 2026-11-22 — Session 4: Step 4 — LangGraph Supervisor and Orchestration

**Work completed**

1. **Dependency install** — `langgraph` (1.2.24), `langgraph-checkpoint-postgres`
   (3.2.1), `psycopg[binary]` (3.3.9) added to `backend/requirements.txt`; the whole
   LangGraph stack (langgraph-checkpoint, langgraph-prebuilt, langchain-core,
   psycopg-pool, …) installed and verified importable.
2. **`app/orchestration/state.py`** — the shared `WorkflowState` (TypedDict with
   `operator.add` reducers for the accumulating fields and a custom `_merge_attempts`
   reducer for retry counters), `RecoveryRequest`, `SupervisorDecision`,
   `RecoveryRecommendation`, the node/agent identifiers, the eight `STATUS_*`
   constants and the default compliance policy.
3. **`app/orchestration/checkpointing.py`** — `in_memory_checkpointer()` (InMemorySaver)
   and `postgres_checkpointer()` (PostgresSaver), plus `checkpointer_dsn()` which
   strips the `+psycopg2` suffix because the checkpoint adapter speaks psycopg 3 while
   the app's engine speaks psycopg2. `open_checkpointer()` selects by
   `LANGGRAPH_CHECKPOINT_BACKEND` (default `postgres`).
4. **`app/orchestration/workflow.py`** — the compiled supervisor graph: one
   supervisor node, the five agent nodes, an approval gate, an error handler and the
   `finalize` terminal, joined by conditional edges. The supervisor implements the six
   roadmap decisions (logistics? inventory? more scenarios? scenario revision?
   compliance? proceed to approval?) and records a `SupervisorDecision(step, action,
   reason)` for every pass. Each agent is attempted at most twice; hard failures
   (`GeminiNotConfiguredError`, `IntegrationNotConfiguredError`, `ToolInputError`,
   base `ValidationError`) are never retried. The loop is bounded by
   `LANGGRAPH_MAX_ITERATIONS × 5`.
5. **`app/orchestration/__init__.py`** — re-exports the orchestration API.
6. **`tests/test_orchestration.py`** — 20 tests covering the six roadmap scenarios
   (normal disruption; multiple shipments; missing route information; no feasible
   recovery; agent failure; invalid agent output) plus approval interrupt/resume,
   the JSON-only state contract and an opt-in `RUN_LIVE_GEMINI=1` check.
7. **`app/api/orchestration.py`** — HTTP surface (`POST /api/orchestration/workflows`,
   `POST …/{thread_id}/resume`, `GET …/{thread_id}/state`), registered in
   `app/api/router.py`.
8. **`backend/docs/workflow.md`** — the required graph visualisation, containing the
   verbatim `mermaid_diagram(graph)` output plus a readable view, the node table, the
   six decisions and the bounds/retry/interrupt rules.

**Important implementation decisions**

- **The supervisor decides from structured results, never a transcript.** Every
  branch reads validated state (assessment counts, scenario feasibility, audit
  verdict) and writes its reason to the decision log, so the run is auditable after
  the fact.
- **State holds JSON dictionaries**, not live Pydantic objects
  (`model_dump(mode="json")`), which is what the PostgreSQL checkpointer requires;
  each node re-validates what it reads.
- **`ScenarioPlanningAgent` already composes** the rerouting and inventory agents, so
  the supervisor runs the standalone rerouting/inventory nodes only on the direct
  path or as the single bounded scenario revision — it never double-invokes them.
- **A zero-cost proposal is never audited.** When no feasible recovery exists, the
  workflow short-circuits to `finalize` with `STATUS_NO_FEASIBLE_RECOVERY`.

**Dependencies installed**

- LangGraph 1.2.24, langgraph-checkpoint-postgres 3.2.1, langgraph-checkpoint 4.3.2,
  langgraph-prebuilt 1.1.3, psycopg 3.3.9 (+ binary), psycopg-pool, langchain-core
  1.8.4 and their transitive dependencies.

**Tests and results**

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite) | ✅ **251 passed, 6 skipped** (257 collected; the 6 skips are the opt-in `RUN_LIVE_GEMINI=1` tests) |
| `tests/test_orchestration.py` | ✅ **19 passed, 1 skipped** |
| `app.main` OpenAPI route check | ✅ `/api/orchestration/workflows`, `…/{thread_id}/resume`, `…/{thread_id}/state` mounted |
| Step 4 smoke run (`xf_step4_smoke.py`) | ✅ exit 0 — direct path, no-carrier path, High-severity path and the full Mermaid source |
| Diagnostic (`xf_diag.py`) | ✅ exit 0 — confirmed the smoke "anomalies" were the smoke test's own inputs |
| Live PostgreSQL checkpoint (`xf_pg_checkpoint.py`) | ✅ `open_checkpointer(backend="postgres")` opened, `setup()` ran, a checkpoint was written and read back (`{'n': 21, 'doubled': 42}`) against the live Aiven database |

**Problems encountered and their solutions**

1. **Six `tests/test_orchestration.py` failures on first run** — all test-side:
   (a) `RecoveryRecommendation.event_id` is derived from the report, so the fixture
   needed an explicit `event_id`; (b) four assertions read optional `TypedDict` keys
   (`rerouting`, `scenario_plan`, `audit_report`) that LangGraph legitimately omits
   when the channel is never written — changed to `state.get(...)`; (c) the inventory
   test hit a *correct* approval interrupt (a ≥500-unit transfer), so it now asserts
   the paused `awaiting_approval` state and resumes.
2. **`_IncludedRouter` has no `.path` in Starlette 1.10** — `app.routes` no longer
   exposes nested routes flatly. *Solution:* assert the mounted paths through
   `app.openapi()["paths"]` instead.
3. **Scripts outside `backend/` cannot import `app`.** *Solution:* set
   `PYTHONPATH=d:\X Factor\backend` when running a temp script from
   `%TEMP%`.

**Remaining work**

- Step 5 (multi-agent collaboration and autonomous replanning) and beyond — see
  `TASK_CHECKLIST.md`. Step 4 is complete and verified; the roadmap rule "do not
  proceed to the next step automatically" was observed.

---

## 2026-11-22 — Session 5: Step 5 — Multi-Agent Collaboration and Autonomous Replanning

### Starting point (session-recovery protocol)

Resumed from `PROJECT_PROGRESS.md` §12 and `TASK_CHECKLIST.md` Step 5. Steps 0–4
were verified complete (the suite passed 251 / 6 skipped), so Step 5 was the first
incomplete task. The Step 4 supervisor graph, state and tests were read first and
**extended, not rebuilt**: delegation order, the six decisions, statuses and
interrupt/resume are unchanged and re-verified by the Step 4 tests.

### Work completed

1. **`app/schemas/collaboration_schemas.py`** — the structured protocol:
   `AgentTask`, `ToolInvocation`, `AgentExecution`, `ScenarioEvaluation`,
   `ScenarioScreening`, `ScenarioHistoryEntry`, `ReplanningRecord`, plus
   `ToolCallStatus` and `ExecutionStatus`.
2. **`app/utils/tool_recording.py`** — a context-local `ToolCallRecorder`,
   `call_recorded` (records duration/outcome and re-raises unchanged),
   `RecordingConnector` / `wrap_connector` (transparent proxy over external
   connectors) and `record_tool_call`. All helpers are no-ops when no recorder is
   active, so direct agent calls in unit tests behave exactly as before.
3. **`app/orchestration/collaboration.py`** — the deterministic decisions:
   `build_agent_task`, `evaluate_scenario_plan` (reuses the Agent 5 compliance,
   budget and approval engines), `screening_requires_replan`,
   `build_scenario_revision`, `build_history_entry`, `build_replanning_record`,
   the `AGENT_TOOLS` / `AGENT_OBJECTIVES` maps and `MAX_REPLAN_ROUNDS = 2`.
4. **`app/orchestration/state.py`** — added `STATUS_NO_COMPLIANT_RECOVERY`; the
   `RecoveryRecommendation` gained the collaboration record; `WorkflowState` gained
   accumulating `tasks` / `agent_executions` / `scenario_history` / `replanning` /
   `skipped_agents` channels and control `scenario_screening` / `scenario_revision`
   / `replan_rounds`.
5. **`app/orchestration/workflow.py`** — each agent node now issues a real
   `AgentTask`, activates a `ToolCallRecorder`, writes an `AgentExecution`
   (completed, failed or skipped), screens a returned `ScenarioPlan`, opens the
   bounded replanning loop and records everything in `finalize`.
6. **Agent instrumentation** — Disruption Sensing, Rerouting, Inventory,
   Compliance and Scenario planning wrap their deterministic engine calls and
   Gemini call with `call_recorded`; connector calls are recorded by the proxy.
7. **`app/agents/scenario_planning.py`** — `plan(request, revision=None)` applies
   a revision deterministically (drops rejected ids and excluded carriers, never
   invents a replacement) and degrades gracefully when the inventory integration
   is unavailable.
8. **`app/api/orchestration.py`** — the response now also returns
   `agent_executions`, `scenario_screening`, `replanning`, `replanning_rounds` and
   `skipped_agents`.
9. **`backend/docs/collaboration.md`** — the collaboration record, screening,
   feedback loop, bounds and the new status.
10. **`tests/test_collaboration.py`** — 14 tests (listed under "Tests and results").

### Important implementation decisions

- **Recorded, not narrated.** A task exists only for an executed decision, an
  execution only when the node ran, and a tool call only when the tool was called;
  tests assert this correspondence.
- **Screening mirrors the audit.** Using the same engines and verdict derivation
  means a plan that passes screening cannot later fail the audit, so replanning is
  triggered only by a real deterministic rejection.
- **Bounded and history-preserving.** `MAX_REPLAN_ROUNDS = 2`; revisions exclude
  rejected alternatives, the replaced plan is stored as a `ScenarioHistoryEntry`,
  and an empty revised plan ends in `no_compliant_recovery` instead of looping.
- **Unavailable tools degrade honestly.** `IntegrationNotConfiguredError` is
  recorded as `unavailable`; the optional inventory node becomes `SKIPPED` and
  scenario planning continues without inventory data — never simulated data.
- **Attempts are delegation ordinals.** `_next_attempt` counts prior tasks for the
  agent, so a retry and a replan both read attempts `[1, 2]`.

### Dependencies installed

- None. Step 5 reuses LangGraph, Pydantic and the existing layers.

### Tests and results

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite) | ✅ **265 passed, 6 skipped** (271 collected; the 6 skips are the opt-in `RUN_LIVE_GEMINI=1` tests) |
| `pytest tests/test_collaboration.py` | ✅ **14 passed** |
| `pytest tests/test_orchestration.py` | ✅ **19 passed, 1 skipped** (Step 4 behaviour unchanged) |
| `pytest tests/test_scenario_planning.py tests/test_rerouting_logistics.py tests/test_inventory_rebalancing.py tests/test_compliance_audit.py` | ✅ passed (agent instrumentation changed nothing observable) |
| `RUN_LIVE_GEMINI=1 pytest tests/test_orchestration.py -k live` | ✅ **1 passed** — real Gemini reasoning through the new tool-recording wrappers |

### Problems encountered and their solutions

1. **`make_request(applicable_rules=...)` rejected the override** — the helper
   always passes its own list. *Solution:* added `request_with_rules(rules)` using
   `make_request().model_copy(update={"applicable_rules": rules})`.
2. **Both replan executions reported attempt 1** — the attempt was taken from the
   retry counter. *Solution:* added `_next_attempt`, which counts prior issued
   tasks for that agent; retries and replans now both read `[1, 2]`.
3. **The unavailable-SAP test never ran the standalone rebalancing node** — the
   default multi-shipment payload takes the scenario path. *Solution:* the test
   uses `direct_path_gemini()`.
4. **`state["audit_report"]` raised `KeyError` when absent** — LangGraph omits
   never-written channels. *Solution:* read `state.get("audit_report")`.

### Remaining work

- Step 6 (human-in-the-loop and authorised execution) and beyond — see
  `TASK_CHECKLIST.md`. Step 5 is complete and verified; the roadmap rule "do not
  proceed to the next step automatically" was observed.

---

_All progress files updated at the end of this milestone._
