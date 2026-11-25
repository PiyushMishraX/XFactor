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

## 2026-11-22 — Session 6: Step 6 — Human-in-the-Loop and Authorized Execution

### Starting point (session-recovery protocol)

Resumed from `PROJECT_PROGRESS.md` §12 and `TASK_CHECKLIST.md` Step 6, with Step 5
verified complete (suite 265 passed / 6 skipped). The Step 4 approval gate,
Step 5 collaboration record and the Step 2 `evaluate_approval` engine were read
first and **extended, not replaced**: the legacy `{"approved": bool}` interrupt
payload still works, and every Step 0–5 test still passes.

### Work completed

1. **`app/schemas/approval_schemas.py`** — `ProposalSnapshot` with a deterministic
   `compute_version()`, `ApproverIdentity` / `ApproverRole`, decision request,
   record and outcome models, and `ApprovalRequestView` for the queue.
2. **`app/schemas/execution_schemas.py`** — `ExecutionAction`,
   `ExecutionActionType`, action/run statuses and `ExecutionReport`.
3. **`app/models/approvals.py`** — `ApprovalRequestRow` (`approval_requests`), one
   row per thread holding the current proposal, version, level, status,
   decision-history JSON and execution report.
4. **`app/services/approval_auth.py`** — `APPROVER_CREDENTIALS` parsing
   (`token:approver_id:Role`), constant-time authentication with
   `secrets.compare_digest` across every entry, Manager < Director < Admin
   hierarchy, bearer-header parsing and fail-closed configuration errors.
5. **`app/services/approval_repository.py`** — `ApprovalRepository` protocol,
   `PostgresApprovalRepository`, `InMemoryApprovalRepository` and
   `ensure_approval_schema`.
6. **`app/services/execution.py`** — `build_execution_plan`, `ExecutionService`
   (idempotent replay, refusal of unapproved/unversioned proposals),
   `SimulatedExecutionAdapter` and `HttpExecutionAdapter`, plus the
   `get_execution_adapter` factory.
7. **`app/services/approval_service.py`** — the ordered decision coordinator:
   authenticate → confirm paused at `approval_gate` → ensure/record the queue item
   → require pending → match the submitted version to the stored and current
   workflow versions → authorize the role → resume → append the decision record →
   execute only on approve + `completed` → record the next pending version when
   paused again.
8. **`app/orchestration/approvals.py`** — proposal snapshot from state, resume
   payload, legacy decision parsing, `build_modification_revision` and
   `MAX_MODIFICATION_ROUNDS = 2`.
9. **`app/orchestration/state.py` / `workflow.py`** — `RecoveryRecommendation`
   gained `proposal_version` / `approval_history`; the state gained accumulating
   `approval_history` and `modification_rounds`; the gate publishes its version,
   accepts authenticated and legacy payloads, records identity, role, comment,
   version, timestamp and history, and routes a modification request back to the
   Scenario agent.
10. **`app/api/approvals.py`** — `GET /api/approvals/pending`,
    `GET /api/approvals/{thread_id}`, `POST /api/approvals/{thread_id}/decision`
    and `GET /api/approvals/{thread_id}/execution`, with 401/403/404/409/503
    mapping and bearer authentication. The unauthenticated Step 4
    `POST /api/orchestration/…/resume` endpoint was removed.
11. **`app/config/settings.py`** — `APPROVER_CREDENTIALS`, `EXECUTION_USE_MOCK`,
    `EXECUTION_BASE_URL` / `CLIENT_ID` / `CLIENT_SECRET`, timeout and attempts,
    with derived properties.
12. **`app/integrations/base.py`** — added `post_json` with an
    `Idempotency-Key` header; the retry transport now handles GET and POST.
13. **`app/main.py`** — creates the `approval_requests` schema at startup when the
    database is reachable.
14. **Frontend Approval Center** (`frontend/src/pages/ApprovalCenter.jsx` plus
    `App.jsx`, `services/api.js`, `index.css`) — token entry kept in
    `sessionStorage`, pending queue, proposal with version/reasons/violations,
    full decision history, approve/reject/request-modification actions and the
    execution report with its `[SIMULATED]` marker.
15. **`backend/docs/approval-and-execution.md`**, **`tests/test_approvals.py`**
    (50 tests), plus README, both `.env.example` templates, `TASK_CHECKLIST.md`
    and `PROJECT_PROGRESS.md`.

### Important implementation decisions

- **Version-bound decisions.** The version is a SHA-256 digest of canonical JSON
  excluding `thread_id`, the version and `created_at`, so the graph and the API
  derive the same value; a stale submitted version is rejected with `409`.
- **Fail closed.** No approver identity or approval flag is accepted from the
  body; identity comes only from a bearer token. Unconfigured/malformed
  credentials return `503`, and an unknown approval level is Admin-only.
- **Idempotent execution.** Action keys are
  `thread_id:proposal_version:action_type`; a repeated request replays the stored
  report with `idempotent_replay=True` instead of re-executing.
- **Bounded human loop.** `MAX_MODIFICATION_ROUNDS = 2`; each revision excludes
  the rejected recommendation and preserves history, and exceeding the bound
  closes the workflow as `approval_rejected`.
- **Persisted queue, not in-memory.** A decision can be taken in a different
  process from the one that interrupted the run; a new version opens a new pending
  review and clears the old execution report.
- **Simulated by default.** `EXECUTION_USE_MOCK=true` returns `SIM-…` references
  and `[SIMULATED]` messages, so the platform never claims a real operational
  change.

### Dependencies installed

- None. Step 6 reuses SQLAlchemy/PostgreSQL, the standard-library `secrets`
  module, the Step 2 `httpx` transport and FastAPI.

### Tests and results

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite) | ✅ **315 passed, 6 skipped** (321 collected) |
| `pytest tests/test_approvals.py` | ✅ **50 passed** |
| `pytest tests/test_orchestration.py` | ✅ **19 passed, 1 skipped** (Step 4 behaviour unchanged, legacy payload still accepted) |
| `pytest tests/test_collaboration.py` | ✅ **14 passed** (Step 5 behaviour unchanged) |
| `npm run build` | ✅ passes, including the Approval Center |
| Modification-loop probe | ✅ initial version `f374ff35a40bb879` → revised plan `e238c95bc72b356b` → revert → bound hit → `approval_rejected` with three `request_modifications` history entries |

### Problems encountered and their solutions

1. **`NameError: STATUS_RUNNING` in `build_approval_gate`** when a modification
   request resumed the graph. *Solution:* `STATUS_RUNNING` was missing from the
   state import block; added it and re-probed the full modification loop.
2. **Adapter configuration failure bypassed the 503 mapping** — FastAPI resolves
   dependencies before the endpoint's own `try/except`. *Solution:* the
   `execution_adapter` dependency catches `IntegrationNotConfiguredError` and
   raises `HTTPException(503)` itself.
3. **The queue had to survive a process boundary** — an in-memory-only design
   would make a paused run unresumable after restart. *Solution:* the
   `approval_requests` table plus a repository protocol with a Postgres
   implementation and an in-memory fake for tests.

### Remaining work

- Step 7 (SAP Integration) and beyond — see `TASK_CHECKLIST.md`. Step 6 is
  complete and verified; the roadmap rule "do not proceed to the next step
  automatically" was observed. A manual browser walkthrough of the Approval
  Center is still pending and is tracked with the Step 8 dashboard work.

---

## 2026-11-22 — Session 7: Step 7 — SAP Integration

### Starting point (session-recovery protocol)

Resumed from `PROJECT_PROGRESS.md` §12 and `TASK_CHECKLIST.md` Step 7, with
Step 6 verified complete (suite 315 passed / 6 skipped). The Step 2
`app/integrations/sap.py` connector, the shared `base.py` transport, the Step 6
approval schemas and the `.env` templates were read first and **extended, not
replaced**: the Step 2 read-only contract (and its regression test that forbids
write methods) still holds.

### Work completed

1. **`app/integrations/sap_profiles.py`** — frozen `SAPApiProfile` records for
   `s4hana`, `business_accelerator_hub`, `btp` and `integration_suite`, each with
   transport, authentication style, declared read/write capabilities and prepared
   paths; `resolve_sap_profile(settings)` selects one from `SAP_API_FAMILY`, and
   an undeclared capability raises `IntegrationNotConfiguredError`.
2. **`app/integrations/sap_auth.py`** — `SAPOAuthTokenProvider` (OAuth2
   client-credentials, cached until `expires_in - 30`, never echoing a token
   error body), `SAPHttpClient` (adds `Authorization: Bearer`, drops `x-api-key`),
   `redact_headers` and `sap_token_provider(settings, scope=…)`.
3. **`app/integrations/base.py`** — `IntegrationRequestError.status_code`,
   numeric `Retry-After` parsing (clamped to 30 s) and retry sleeps that honour
   it.
4. **`app/integrations/sap.py`** — the read connector gained material information
   (`SAPMaterial`, `list_materials`, `get_material`, a labelled 5-row sample),
   profile-aware paths and status-code-based 404 handling; it still exposes no
   write method.
5. **`app/integrations/sap_write.py`** — `SAPWriteType`, three validated request
   models, mandatory `SAPApprovalEvidence` (approve-only), the
   `approval_evidence_from_decision` bridge, `sap_idempotency_key`,
   `SimulatedSAPWriteConnector` and `HttpSAPWriteConnector`, with a
   fail-closed `get_sap_write_connector` factory (`SAP_WRITE_ENABLED`,
   capability, credentials, mock).
6. **`app/config/settings.py`** — `SAP_API_FAMILY`, `SAP_AUTH_URL`,
   `SAP_READ_SCOPE`, `SAP_WRITE_SCOPE`, `SAP_WRITE_ENABLED` and the
   `sap_oauth_configured` property.
7. **`backend/docs/sap-integration.md`**, **`tests/test_sap_integration.py`**
   (37 tests), `app/integrations/__init__.py`, both `.env.example` templates,
   README, `TASK_CHECKLIST.md` and `PROJECT_PROGRESS.md`.

### Important implementation decisions

- **Profiles are data, not subclasses.** One frozen record per API family avoids
  four near-identical connector classes and makes a path correction a one-line
  data change.
- **Writes are physically separate.** `sap_write.py` owns a different protocol,
  credential scope, permission flag and approval evidence, so the read connector
  cannot mutate anything.
- **Approval is mandatory, typed and approve-only.** A rejected or
  modification-requested decision cannot be turned into evidence, and there is
  no write entry point without it.
- **Idempotency per proposal version.**
  `sap:{thread}:{version}:{type}:{request_id}` is sent both as `Idempotency-Key`
  and in the payload; 400/409/422 map to `rejected`, timeouts/5xx to `failed`.
- **Honest prepared defaults.** Paths, scopes and entitlements are documented as
  unverified because no tenant was contacted; `SAP_USE_MOCK=true` stays the
  default and every record/result is labelled `[SIMULATED]`.

### Dependencies installed

- None. Step 7 reuses `httpx`, pydantic v2 and the standard library.

### Tests and results

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite) | ✅ **352 passed, 6 skipped** (358 collected) |
| `pytest tests/test_sap_integration.py` | ✅ **37 passed** |
| `pytest tests/test_integrations.py` | ✅ **62 passed** (Step 2 contract unchanged, including the read-only assertion) |

### Problems encountered and their solutions

1. **A multi-line edit to the `base.py` retry loop matched nothing.** *Solution:*
   split it into three small edits (initialize `retry_after`, handle the retryable
   branch, raise 4xx with `status_code` and choose the sleep), each verified.
2. **An `__init__.py` edit failed on a docstring mismatch.** *Solution:* rewrote
   the small package docstring in full.
3. **The first live-write test built a response with an inline `__import__`
   expression.** *Solution:* added a normal `import json` and parsed
   `request.content` directly.

### Remaining work

- Step 8 (Agent Activity and Decision Dashboard) and beyond — see
  `TASK_CHECKLIST.md`. Step 7 is complete and verified; the roadmap rule "do not
  proceed to the next step automatically" was observed. Two documented
  follow-ups: invoking SAP writes from the approval/execution path once proposals
  carry shipment/plant identifiers, and the Approval Center browser walkthrough.

## 2026-11-22 — Session 8: Step 8 — Agent Activity and Decision Dashboard

### Starting point

Session recovery found Step 7 complete and verified (352 passed, 6 skipped) and
Step 8 not started. Backend work for Step 8 (run registry, dashboard API,
recording hooks) had already landed in the working tree; the eight frontend
pages and the shared control-tower shell were still Vite-era placeholder screens
with a two-tab layout. The dashboard had to be built on recorded state only —
no sample executions, no write endpoints.

### Work completed

1. **Run registry and dashboard API (backend).** Added `WorkflowRunRow`
   (`workflow_runs`), `workflow_history` (recording, listing, detail,
   disruptions, status counts, `json_safe`, schema ensure), `dashboard_service`
   (overview KPIs, shipments) and the read-only `/api/dashboard/*` router.
   `POST /api/orchestration/workflows` now records every run including failures,
   and an authenticated decision refreshes the same row. Both writes are
   best-effort and never fail the operation. Startup ensures the table exists.
2. **Application shell rewrite.** `AppLayout` became a numbered 01–08 sidebar
   with a sticky topbar, mobile drawer and footer; `App.jsx` now hosts all eight
   pages with shared run selection and cross-page navigation.
3. **Eight pages.** Overview (KPI tiles, status chart, pipeline, latest runs),
   Disruption Monitoring (list + assessment/decision detail), **Agent Activity**
   (run selector, supervisor trail, five agent cards, execution progress,
   structured results, tool invocations, handoffs, replanning, errors, React Flow
   graph, timeline, decision log), Scenario Comparison (routes, days, cost, risk,
   inventory impact, feasibility, compliance, recommendation, screening and
   replanning history), Approval Center (token gate, queue, proposed action,
   cost/budget impact, per-agent validations, audit verdict, history, controls,
   execution report), Shipment Management (filterable master data),
   Inventory Management (positions, materials, `[SIMULATED]` banner) and Audit
   History (recorded runs with decision/approval detail).
4. **Shared frontend infrastructure.** `useAsyncData` (loading/error/reload),
   `constants/domain.js` (agent ids/labels, tones, navigation), `utils/format.js`,
   and the components `PageHeader`, `StatePanel`, `KpiCard`, `BarChart`,
   `RunSelector` and `AgentWorkflowGraph` (React Flow, `@xyflow/react`).
5. **Theme rewrite.** `index.css` replaced with a dark-navy control-tower system:
   design tokens, panels, KPI grid, tables, chips, progress, timeline, decision
   log, impact tiles, validation list and responsive breakpoints at
   1180/1024/760/480 px.
6. **Bug fixes found during verification.** `AgentActivity` used `onOpenThread`
   without accepting it as a prop; the Shipment page claimed live master data;
   `InventoryManagement` carried an unused helper; `ApprovalCenter` needed
   explicit tones for not-delegated validations and cost deltas.

### Design decisions

- The dashboard is a **projection**, never a second source of truth; the
  checkpoint remains authoritative for resuming.
- History writes are **best-effort**, so observability cannot break a workflow or
  a decision.
- The React Flow graph is generated from **recorded executions**, so a skipped,
  failed or never-delegated agent is drawn as such.
- Provenance is carried into the UI: seeded shipments are labelled as demo rows
  and simulated SAP inventory keeps its `[SIMULATED]` banner.
- Failed and empty states are shown honestly; nothing is back-filled to look
  successful.

### Dependencies installed

- Backend: none.
- Frontend: `@xyflow/react` 13.0.2.

### Tests and results

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite) | ✅ **364 passed, 6 skipped in 9.74s** (370 collected) |
| `pytest tests/test_dashboard.py` | ✅ **12 passed** |
| `npm run build` | ✅ 57 modules; 555.19 kB JS, 40.68 kB CSS; built in 330 ms |
| `npm run lint` | ✅ 0 errors, 2 pre-existing warnings |
| Browser walkthrough (Vite + live backend + Aiven PostgreSQL) | ✅ Overview, Shipment Management, Inventory Management, Disruption Monitoring, Agent Activity (real failed run with React Flow/timeline/tools/handoffs), Scenario Comparison empty plan, Audit History, Approval Center fail-closed states |

### Problems encountered and their solutions

1. **`AgentActivity` crashed when opening a scenario from the detail panel** —
   the page called `onOpenThread` but did not accept it as a prop. *Solution:*
   added it to the props destructure.
2. **Live verification workflow failed on Gemini twice.** The first run returned
   `503 UNAVAILABLE`; the retry returned `429` (`free_tier_requests, limit: 5`).
   *No workaround was invented:* both runs were recorded as genuine failures
   (`EV-UI-VERIFY-001/002`) and the dashboard shows them as failed. Populated
   successful Scenario Comparison and Approval Center views therefore remain
   browser-unverified; the API paths stay covered by tests.
3. **Browser screenshots intermittently reported
   `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`** in the ~498×570 in-app viewport.
   *Solution:* relied on accessibility snapshots and retried screenshots; a
   desktop-width visual pass is deferred to Step 9.
4. **The two verification runs remain in the shared database.** Deleting rows
   from a shared Aiven instance is destructive and was not authorised, so they
   were left in place and documented instead.

### Remaining work

- **Step 9 (Testing and End-to-End Validation)** is next and was deliberately
  not started. It should exercise the Mumbai → Rotterdam golden path, the
  documented failure modes, the two browser views Gemini quota blocked, and
  decide whether the `EV-UI-VERIFY-*` rows should be removed.

---

## 2026-11-22 — Session 9: Step 9 — Testing and End-to-End Validation

### Starting point

Session recovery found Step 8 complete (364 passed, 6 skipped) and Step 9 not
started. The task was validation rather than new features: audit the 17 roadmap
verification points, execute the Mumbai → Rotterdam pharmaceutical maritime
scenario through approval and execution, run the ten required failure tests,
fix critical errors, and write the final report.

### Work completed

1. **Live golden-path attempt.** Started the Mumbai → Rotterdam run through the
   real API. The first attempt failed with
   `InventoryRebalancingError: Target plant 'Rotterdam DC' does not hold material
   'MAT-PHARMA-001'`. Fixed the seed data, then the retry failed on Gemini
   `429 RESOURCE_EXHAUSTED` — `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
   limit 20/day for `gemini-3.6-flash`, retry in ~14 h. No success was invented:
   both runs (`EV-STEP9-MUMBAI-001/002`) remain recorded as genuine failures.
2. **Deterministic end-to-end proof.** Added
   `tests/test_e2e_mumbai_rotterdam.py`, which runs the real graph, agents and
   deterministic tools with a scripted Gemini. It asserts all five agent markers
   execute once, risk ≥ 60, SH001/SUP001 are linked, at least three scenarios
   are produced, screening passes, the inventory shortage is covered, the graph
   pauses for a Director, resumes, and produces an approved execution with three
   `[SIMULATED]` actions; a replay raises `ApprovalConflictError` with an
   unchanged action count.
3. **Critical defect found by that test — inventory transfer dropped.**
   On the scenario-planning path the transfer total lived only on the transient
   `inventory` object, so the audit request, screening input, proposal snapshot
   and execution plan omitted the transfer entirely. Added
   `ScenarioPlan.inventory_transfer_units`, populated it in the Scenario
   Planning agent, and added fallbacks in `_audit_request`, `_screening_update`
   and `build_proposal_snapshot`. The test now asserts the `INVENTORY_TRANSFER`
   action exists.
4. **Data defect — missing destination position.** Added the eighth
   `SimulatedSAPConnector` row (`MAT-PHARMA-001` at Rotterdam DC:
   3 000/6 000/7 000) and corrected the "seven positions" wording.
5. **Failure-test audit.** Mapped all ten required failure cases to existing or
   new tests. Added a live-connector timeout test (`httpx.ReadTimeout`, three
   attempts, clear `IntegrationRequestError`) and a dashboard database-outage
   test (`OperationalError` → `503`).
6. **Live approval and execution.** Completed the previously paused
   `EV-UI-VERIFY-003`: 401 without a token, 403 for a Manager on a high-impact
   re-route, 409 for a stale/duplicate decision, Director approval, three
   simulated executions, a duplicate decision refused, `workflow_runs`
   refreshed (`execution_count` 3, `error_count` 0). The checkpoint created
   before three backend restarts resumed successfully, proving PostgreSQL
   checkpoint persistence.
7. **Browser verification.** With the fixed backend and a Director credential
   supplied through the process environment, verified the Overview KPIs,
   Inventory (including the new Rotterdam DC row), the Approval Center with a
   completed and executed proposal, and Audit History with approval/execution
   records.
8. **Report.** Wrote `backend/docs/validation-report.md` with the 17-item audit
   table, live journal, failure matrix, security checks, test results, known
   limitations and deployment readiness.

### Design decisions

- The deterministic E2E test is the authoritative proof of the golden path while
  the free-tier quota blocks live runs; the live evidence that does exist is
  reported separately and precisely.
- Failures stay in the shared database unless deletion is explicitly approved.
- The inventory transfer is carried on the plan rather than re-derived from
  transient agent objects, so every downstream consumer sees one number.

### Dependencies installed

- None.

### Tests and results

| Check | Result |
| --- | --- |
| `python -m pytest` (full backend suite, from `backend/`) | ✅ **368 passed, 6 skipped in 12.34s** (374 collected) |
| `pytest tests/test_e2e_mumbai_rotterdam.py` | ✅ 2 passed |
| `pytest tests/test_integrations.py -k timeout` | ✅ 1 passed |
| `pytest tests/test_dashboard.py -k unavailable` | ✅ 1 passed |
| `npm run build` | ✅ passes |
| `npm run lint` | ✅ 0 errors, 2 pre-existing warnings |
| Live Gemini Mumbai run | ⛔ blocked by daily quota; recorded honestly |

### Problems encountered and their solutions

1. **Rotterdam DC held no `MAT-PHARMA-001`** → added the eighth simulated
   inventory position and updated the docs.
2. **Gemini daily quota** → switched to a deterministic E2E test plus the
   already-completed live approval/execution; documented the limit and the
   ~14 h reset.
3. **Scenario-path transfer lost** → carried `inventory_transfer_units` on the
   plan with downstream fallbacks.
4. **Suite run from the repository root skipped 8 PostgreSQL tests** because
   `env_file=".env"` is CWD-relative → run pytest from `backend/`.
5. **A credential-redaction command failed once and printed a connection URL.**
   The value is not repeated anywhere; only environment-variable names are
   documented.

### Remaining work

- **Step 10 (Deployment and Hackathon Demonstration)** is next and was
  deliberately not started. Pending explicit approval: persisting an approver
  credential and deleting the four failed verification rows. SAP writes remain
  deferred until proposals carry shipment/plant identifiers.

---

## 2026-11-24 — Session 10: Step 10 — Deployment and Hackathon Demonstration

### Objective

Package the finished product for the hackathon without changing decision logic:
containers, Compose, environment wiring, PostgreSQL with persistent checkpoints,
health checks, one Red Sea demo scenario and the final deliverable documents.

### What was built

- `backend/Dockerfile` — python:3.12-slim, non-root `xfactor`, `COPY app scripts
  demo`, liveness healthcheck, uvicorn on 0.0.0.0:8000; `backend/.dockerignore`
  keeps `.env`, tests, docs and caches out of the image.
- `frontend/Dockerfile` — multi-stage `node:22-alpine` build → `nginx:1.27-alpine`;
  `frontend/nginx.conf` serves the SPA with `try_files`, answers `/healthz`, and
  proxies `/api/` to `backend:8000` with a 180 s read timeout so long agent runs
  are not cut off.
- `docker-compose.yml` — `db` (postgres:16-alpine, `postgres-data` volume,
  `pg_isready`), one-shot `seed` (idempotent reference data), `backend`
  (`LANGGRAPH_CHECKPOINT_BACKEND=postgres`, `DATABASE_URL` empty so discrete
  `POSTGRES_*` apply, `stop_grace_period: 30s`), `frontend` published on 8080;
  dependencies use health conditions and `service_completed_successfully`.
- Demo assets: `backend/demo/mumbai_rotterdam_scenario.json`
  (`EV-DEMO-RED-SEA`) and `mumbai_rotterdam_replan_scenario.json`
  (`EV-DEMO-RED-SEA-REPLAN`, lead-time rule 18 days so the 21.7-day sea options
  are rejected and the 16.7-day road option survives); `scripts/run_demo_scenario.py`
  submits a scenario, prints decisions, agent executions, scenarios, screening,
  inventory and approval, and can submit an authenticated decision.
- Documents: `architecture.md`, `langgraph-workflow.mmd`, `api.md`,
  `database-schema.md`, `deployment.md`, `demo-script.md`, `test-report.md`;
  README restructured with Compose usage and links.

### How it is verified

- `docker compose build` produced `xfactor-backend`/`xfactor-seed` at 407 MB and
  `xfactor-frontend` at 74.4 MB; `docker compose config --quiet` is valid.
- Clean `docker compose up`: db healthy → seed exits 0 ("5 suppliers, 10
  shipments") → backend healthy → frontend healthy.
- `:8080/` 200, `:8080/healthz` 200, `:8080/api/health` 200 with
  `"database":"connected"`; dashboard reports 10 shipments and 5 suppliers.
- Eight tables exist, including `checkpoints`, `checkpoint_blobs`,
  `checkpoint_writes`, `checkpoint_migrations` (40 checkpoint rows).
- `docker compose restart backend` → `GET /api/orchestration/workflows/EV-DEMO-RED-SEA-5/state`
  still returns the saved failed state, proving persistence in PostgreSQL.
- `docker compose stop` logs `Waiting for application shutdown` →
  `Application shutdown complete`; `docker compose start` restarts in order.
- `GET :8080/api/approvals/pending` → 401 unauthenticated, 503 fail-closed with
  no configured credential.
- Full suite: **375 collected, 369 passed, 6 skipped, 0 failures** (the extra
  test validates both demo payloads and the replan revision).

### Problems encountered and their solutions

1. **Docker engine was not running** — the first "build" only appeared to
   succeed because the pipeline swallowed the daemon error. Started Docker
   Desktop and waited for `docker info`.
2. **Corrupted layer download** (`short read … unexpected EOF`) — pulled each
   base image explicitly with retries, then rebuilt.
3. **Demo runner field mismatches** — corrected the runner to the real payloads
   (`scenario_count/evaluations/all_rejected`, state `scenario_plan`,
   `decision.decision.approver_id`, interrupt `approval_level/verdict/reasons`).
4. **Replan variant rejected everything** — the lead-time rule was tighter than
   the demo days; set it to 18.0 so exactly one compliant alternative remains.
5. **Live demo blocked by Gemini** — `503 high demand` for both flash models,
   then `429 quota exceeded` (20/day). Probed models directly, switched
   `.env` to the model that was serving, still exhausted. Failed runs
   `EV-DEMO-RED-SEA`…`-5` are recorded; no execution happened and nothing was
   fabricated.

### Honest limitation

The live container demo — a pause at the approval gate, a decision and three
`[SIMULATED]` executions — could not be produced while the quota was exhausted.
The deterministic E2E test and the Step 9 live run remain the evidence for that
path; §11 items 23–25 of `PROJECT_PROGRESS.md` record the gap.

### Remaining work

- No roadmap step remains. The only outstanding item is Gemini quota capacity
  (billing, a quota-backed key, or key rotation) so the demo can run unattended.
- Deferred pending explicit approval: persisting an approver credential; deleting
  the failed verification/demo rows from the shared Aiven database.

---

## 2026-11-24 — Session 11: Multi-key Gemini distribution and pacing

### Objective

Stop all five agents from sharing one free-tier key and bursting calls. Allow
two (or more) operator keys to be distributed per agent, with deliberate spacing
between requests.

### What was built

- `Settings.GEMINI_API_KEYS` (comma-separated), `GEMINI_KEY_SLOTS`
  (`agent=index` overrides), `GEMINI_MIN_INTERVAL_SECONDS` and
  `GEMINI_RETRY_BACKOFF_SECONDS`. The effective key list is
  `GEMINI_API_KEY` first, then the extra keys, de-duplicated.
- `app/services/gemini_keys.py`: `AGENT_ORDER` (roadmap order),
  `parse_key_slots` and `resolve_agent_keys` — round-robin by default, explicit
  overrides honoured, unknown agents and out-of-range slots rejected with a
  clear `ValueError`.
- `GeminiService` accepts an explicit `api_key` and `agent_name`; when no shared
  service is supplied, `build_agents` creates one service per agent bound to its
  slot. `build_default_agents` passes settings through.
- Process-wide `_KeyThrottle`: every HTTP attempt waits until
  `GEMINI_MIN_INTERVAL_SECONDS` has elapsed since the previous request **on the
  same key fingerprint**, so two agents sharing a key also space out. Retry
  backoff is now `N × GEMINI_RETRY_BACKOFF_SECONDS`.
- Keys are never logged; DEBUG logs show the agent and a 12-character SHA-256
  fingerprint only.
- Local `backend/.env` pacing is 6 s and backoff 5 s. The two operator keys still
  need to be pasted into `GEMINI_API_KEYS` (not committed, not written by me).

### Verification

| Check | Result |
| --- | --- |
| `pytest tests/test_gemini_multi_key.py` | ✅ 14 passed |
| Full suite (`pytest tests`, from `backend/`) | ✅ 389 collected, 383 passed, 6 skipped, 0 failures |
| Distribution with two keys | sensing/rerouting/compliance → slot 0; scenario/inventory → slot 1 |
| Invalid slot / unknown agent | `ValueError` naming the offending entry |
| Explicit shared service | unchanged behaviour (tests and single-key callers) |

Live verification with the real second key is pending: the keys are supplied by
the operator and the Gemini free-tier window was still exhausted.

### Remaining work

- Paste the two keys into `backend/.env` (`GEMINI_API_KEYS`), recreate the
  backend, and confirm per-agent key fingerprints in DEBUG logs.
- If the demo must run before the quota resets (~08:00 UTC), use a billed key.

---

## 2026-11-24 — Session 12: Quota-aware key rotation and quarantine

### Objective

The operator reported the workflow stopping with HTTP `429` at
`disruption_sensing`. The upstream payload was a **daily** cap
(`RESOURCE_EXHAUSTED`, `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
`quotaValue: 20`, `retryDelay: 51075s`), so the previously suggested
"retry with 15–60 s backoff" could not help. The goal was to make the client
behave correctly for this failure: stop retrying a dead key, use the other key,
and report the limit honestly when none is left.

### What was built

- `GeminiQuotaExceededError` and `parse_quota_failure` extract the quota id,
  model and `retryDelay` from Google's `QuotaFailure` / `RetryInfo` details.
- `_KeyCooldown` quarantines an exhausted key (process-wide, keyed by SHA-256
  fingerprint) for the reported reset window.
- `_post` rotates through the agent's candidate keys. `_post_one` sends one key's
  request; a daily quota 429 is not retried three times — it raises immediately,
  the key is quarantined and the next key is tried.
- Only a short `retryDelay` (`≤ GEMINI_QUOTA_RETRY_MAX_SECONDS`, default 120 s)
  is slept on, which is the per-minute-throttle shape. Non-quota 429s keep the
  existing retry/backoff behaviour.
- Each agent's fallback order starts at its assigned slot: with two keys, slot 1
  yields `(key2, key1)`. `resolve_agent_key_order` computes this alongside
  `resolve_agent_keys`.
- `GeminiQuotaExceededError` is in the supervisor's non-retryable set, so an
  exhausted quota does not burn a second agent execution.
- When every key is cooling down, the call fails without any HTTP request and
  states the earliest reset in UTC.

### Verification

| Check | Result |
| --- | --- |
| `pytest tests/test_gemini_quota_rotation.py` | ✅ 8 passed |
| Gemini modules (`quota_rotation`, `multi_key`, `service`) | ✅ 31 passed |
| Full suite (`pytest tests`, from `backend/`) | ✅ 397 collected, 391 passed, 6 skipped, 0 failures |
| Daily quota 429 | 1 HTTP attempt, no sleep, key quarantined, actionable error |
| Primary exhausted | rotates to the fallback key; later calls skip the cooling key with no request |
| All keys cooling | error names the reset time; handler is never called |
| Short `retryDelay` (30 s) | slept once, retried the same key, succeeded |
| Test hygiene | `test_gemini_service.py` now passes `_env_file=None` so a real key in `backend/.env` cannot leak into the missing-key test |
| Live probe (18:18 UTC, in container) | `disruption_sensing` key → `{"ok": true}`; `scenario_planning` key → daily-quota 429, rotated to slot 0, `{"ok": true}`. This is the first live evidence that rotation works against the real API |

The full workflow demo has not been rerun: it needs ~5 calls of headroom plus an
approver credential (approval currently fails closed with 503). The LLM path the
demo uses is the same one exercised by the live probe.

---

## 2026-11-25 — Session 13: One-click Start with single-flight admission

### Objective

The operator asked for a Start button that runs the agents once, so repeated
clicks cannot overload the five agents or the Gemini quota. Every existing start
path invoked the supervisor independently, so overlapping clicks or tabs could
launch concurrent five-agent runs.

### What was built

- `WorkflowGuard` — a process-wide, non-blocking `threading.Lock` that holds the
  active thread id. It matches the Compose stack's single uvicorn worker; the
  docs state that horizontal scaling needs a database advisory lock.
- `_run_guarded` in the orchestration API wraps both start paths. A second start
  while the slot is held returns `409` with the active thread id; the guard is
  always released in `finally`, and approval/history persistence stays inside the
  claimed slot.
- `POST /api/orchestration/workflows/start` loads the bundled validated Red Sea
  scenario, assigns a fresh `EV-UI-START-<UTC>-<hex>` event id to both nested
  event ids, runs it once and records the run in `workflow_runs`.
- `GET /api/orchestration/workflows/active` reports `{running, thread_id}`.
- Overview gained a **Start agents** panel: disabled while any run is in flight
  (polled every 4 s), with a running message, run output (status, agents executed,
  proposal version, recommendation, errors) and links to Agent Activity and the
  Approval Center. The overview refreshes after a run.
- `frontend/src/services/api.js` gained `startAgents()` and `getActiveWorkflow()`.

### Verification

| Check | Result |
| --- | --- |
| `pytest tests/test_workflow_start.py` | ✅ 9 passed |
| Full suite (`pytest tests`, from `backend/`) | ✅ 406 collected, 400 passed, 6 skipped, 0 failures |
| Frontend lint / build | ✅ 0 errors (2 pre-existing warnings) / built |
| Live UI click | ✅ started `EV-UI-START-20261124-183758-cf0e25`; button showed **Agents running…** |
| Concurrent start | ✅ `409` naming the active thread |
| Run output | ✅ recorded `awaiting_approval`, 4 agent executions, proposal `632eec40e5aa393c`, one transient Gemini `503` retried and recorded honestly |
| Slot release | ✅ active returned `{"running": false, "thread_id": null}` after completion |
| Earlier live attempt | `EV-UI-START-20261124-183611-309e66` failed after two `503` attempts; displayed as failed, not masked |

The approval gate is reached but not decided: the human approver has not yet
submitted a decision for the pending proposal.

---

## 2026-11-25 — Session 14: Approval Center token-entry fix

### Problem

The Approval Center showed "The bearer token is not recognised." and an empty
queue while a proposal was actually pending. The browser's sessionStorage held
the entire `APPROVER_CREDENTIALS` entry (`token:approver_id:Role`, 16 chars)
instead of just the token part, and the UI kept that rejected token as if it were
valid, with no hint about the correct format.

### Fix

- `ApprovalAuthorizer` now returns an actionable 401: send only the token part
  (before the first colon), not the whole entry.
- `request()` attaches the HTTP status to thrown errors so the UI can recognise
  authentication failures.
- The Approval Center clears a 401-rejected token from state and sessionStorage,
  shows the token prompt again with the reason, labels the field "token part only"
  and explains the format in the empty state. The same reset applies to a
  rejected decision submission.
- Tests assert both the hint and that the whole-entry form is rejected.

### Verification

| Check | Result |
| --- | --- |
| `pytest tests` (from `backend/`) | ✅ 406 collected, 400 passed, 6 skipped, 0 failures |
| Frontend lint / build | ✅ 0 errors / built |
| Live wrong token | ✅ 401 with the "before the first colon" hint |
| Live UI reload with stale token | ✅ token cleared automatically; prompt and reason shown |
| Live correct token (`abgcg`) | ✅ pending queue shows 1 proposal |
| Proposal detail | ✅ version `632eec40e5aa393c`, cost/risk impact, 4 agent executions, decision controls |

The approval decision is intentionally left to the human approver; nothing was
approved, rejected or executed during this check.

---

_All progress files updated at the end of this milestone._
