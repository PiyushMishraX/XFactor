# X FACTOR — TASK CHECKLIST

Derived from `DEVELOPMENT_ROADMAP.txt`. Statuses:

- `[ ]` Not started
- `[/]` In progress
- `[x]` Completed
- `[!]` Blocked

> A task is only marked `[x]` once its implementation has been **verified**.
> Never mark a task complete based on intent alone.

---

## STEP 0 — Project Initialization and Architecture ✅

- [x] Inspect existing project directory and structure
- [x] Create backend directory structure (`app/api, agents, orchestration, tools, integrations, models, schemas, services, database, config, utils`, `tests/`)
- [x] Create frontend directory structure (`src/components, pages, services, hooks, layouts, assets`)
- [x] Configure FastAPI application (`backend/app/main.py`)
- [x] Configure React + Vite (`frontend/vite.config.js`, `index.html`)
- [x] Configure PostgreSQL connection (lazy SQLAlchemy engine + session factory)
- [x] Configure Pydantic settings and environment variables
- [x] Add health-check endpoint (`/api/health`, `/api/health/live`)
- [x] Configure CORS
- [x] Add basic logging (`configure_logging`, plain + JSON)
- [x] Add basic error handling (global exception handler)
- [x] Prepare configuration placeholders for Gemini, LangGraph and SAP
- [x] Create clean README
- [x] Add `.gitignore`
- [x] Create requirements file with compatible dependencies
- [x] Backend unit tests for the skeleton (4 passing)
- [x] Verify frontend and backend run independently
- [x] Verify frontend successfully communicates with the backend
- [x] Do **not** implement any AI agents in this step

---

## STEP 1 — Gemini Integration and Disruption Sensing Agent ✅

- [x] Add + install Gemini and LangGraph dependencies (Gemini uses the existing `httpx`; LangGraph is deferred to Step 4 where it is first needed)
- [x] Implement `gemini_service.py`
- [x] Implement `disruption_schemas.py` (structured Pydantic I/O)
- [x] Implement `disruption_sensing.py` agent
- [x] Deterministic risk-scoring function based on evidence (not LLM-invented)
- [x] Identify disruption type / affected locations / impact
- [x] Identify affected shipments and suppliers from database information
- [x] Validate shipment references against PostgreSQL
- [x] Recommend next investigation / recovery action
- [x] Handle missing and contradictory information
- [x] Include source information and timestamps where available
- [x] Support all 8 disruption categories
- [x] Do not execute operational actions
- [x] Unit tests: maritime disruption
- [x] Unit tests: severe weather event
- [x] Unit tests: supplier failure
- [x] Unit tests: irrelevant news article
- [x] Unit tests: incomplete disruption report

---

## STEP 2 — External Tools and Deterministic Business Logic ✅

### A. External and internal tools

- [x] Weather API connector
- [x] News API connector
- [x] Maritime Alerts API connector
- [x] Port Congestion API connector
- [x] Tariff Data API connector
- [x] Supplier API connector
- [x] Carrier API connector
- [x] Shipment Tracking API connector
- [x] Mapping API connector
- [x] SAP Connector interface
- [x] Configurable credentials and timeouts
- [x] Labelled mock adapters where paid access/credentials are unavailable

### B. Deterministic business logic

- [x] Risk Scoring Engine
- [x] Cost Calculation Engine
- [x] Route Optimization Engine
- [x] Lead-Time Estimation Engine
- [x] Inventory Calculation Engine
- [x] Safety Stock Calculation Engine
- [x] Supplier Ranking Engine (configurable weighted criteria)
- [x] Compliance Rules Engine (specific rule violations)
- [x] Budget Validation Engine
- [x] Approval Management Engine
- [x] Input validation and structured outputs
- [x] Unit tests for each engine
- [x] Documented assumptions
- [x] No calculations inside LLM prompts
- [x] Tools independently reusable by multiple agents
- [x] Do **not** build additional AI agents in this step

---

## STEP 3 — Build the Remaining Four AI Agents ✅

### Agent 2 — Scenario Planning Agent

- [x] Receive disruption details and affected supply-chain information
- [x] Generate multiple recovery strategies (≥3 when data allows)
- [x] Request route/logistics analysis
- [x] Request inventory impact analysis
- [x] Compare recovery alternatives (financial impact, delivery time, risk)
- [x] Rank feasible scenarios
- [x] Explain why the recommended scenario is preferable
- [x] Never invent feasibility or cost data

### Agent 3 — Rerouting & Logistics Agent

- [x] Identify alternative transportation routes
- [x] Evaluate available carriers
- [x] Calculate transportation costs (deterministic tools)
- [x] Estimate delivery time
- [x] Evaluate route-related risks
- [x] Compare logistics alternatives
- [x] Return ranked feasible options

### Agent 4 — Inventory Rebalancing Agent

- [x] Inspect inventory across warehouses
- [x] Identify shortages
- [x] Calculate safety stock requirements
- [x] Identify alternative warehouses
- [x] Evaluate stock redistribution
- [x] Recommend inventory transfers
- [x] Estimate impact on product availability
- [x] Never recommend transferring unavailable / committed inventory

### Agent 5 — Compliance & Audit Agent

- [x] Validate proposed recovery strategies
- [x] Check regulatory restrictions
- [x] Validate budget requirements
- [x] Check operational policies
- [x] Identify approval requirements
- [x] Reject proposals violating mandatory rules
- [x] Generate structured audit evidence
- [x] LLM may explain but never override failed validation

### Common requirements

- [x] Independent agent modules
- [x] Pydantic input/output schemas
- [x] Tool access implemented
- [x] Gemini used for reasoning
- [x] Structured JSON returned
- [x] Missing-information handling
- [x] Logging added
- [x] Unit tests added
- [x] Confidence and evidence included where appropriate
- [x] Do **not** implement the central supervisor yet

---

## STEP 4 — LangGraph Supervisor and Orchestration ✅

- [x] Pydantic/TypedDict workflow state
- [x] Five agent nodes
- [x] Supervisor node
- [x] Conditional routing (dynamic, not fixed sequence)
- [x] Shared state
- [x] Error-handling nodes
- [x] Workflow checkpointing
- [x] PostgreSQL-backed persistent checkpoints
- [x] Dynamic decisions: logistics required?
- [x] Dynamic decisions: inventory analysis required?
- [x] Dynamic decisions: additional scenarios required?
- [x] Dynamic decisions: scenario revision needed?
- [x] Dynamic decisions: compliance validation required?
- [x] Dynamic decisions: proceed to approval?
- [x] Initial workflow invocation
- [x] State updates
- [x] Retry handling
- [x] Workflow interruption
- [x] Resume from checkpoint
- [x] Graph visualisation / Mermaid workflow documentation
- [x] Test: normal disruption
- [x] Test: disruption affecting multiple shipments
- [x] Test: missing route information
- [x] Test: no feasible recovery scenario
- [x] Test: agent failure
- [x] Test: invalid agent output

---

## STEP 5 — Multi-Agent Collaboration and Autonomous Replanning ✅

- [x] Dynamic task delegation
- [x] Structured inter-agent communication
- [x] Shared workflow state
- [x] Agent result evaluation
- [x] Feedback loops
- [x] Conditional replanning
- [x] Tool selection
- [x] Failure recovery
- [x] Scenario comparison
- [x] Bounded autonomous iteration (max iteration limits, no infinite loops)
- [x] Track agent execution history
- [x] Record tool calls and results
- [x] Handle unavailable tools
- [x] Track why the supervisor selected each agent
- [x] Preserve previous scenario results when replanning
- [x] No fabricated agent messages — interactions must reflect executed functions

---

## STEP 6 — Human-in-the-Loop and Authorized Execution ✅

- [x] Approval Management Engine evaluates approval requirements
- [x] LangGraph interrupt when approval is mandatory
- [x] Approval interface displays the proposal
- [x] Manager can approve / reject / request modifications
- [x] Resume workflow from saved checkpoint
- [x] Execute authorised operations on approval
- [x] Return rejection feedback to the supervisor
- [x] Record the entire decision history
- [x] Approval required: high-impact shipment rerouting
- [x] Approval required: major inventory redistribution
- [x] Approval required: actions exceeding budget thresholds
- [x] Approval required: sensitive supplier changes
- [x] Only authenticated/authorised users can approve
- [x] Never trust unauthenticated frontend approval status
- [x] Record approver identity and timestamp
- [x] Prevent duplicate execution (idempotency keys)
- [x] Validate approval against current proposal version
- [x] Execution service: shipment plan updates
- [x] Execution service: inventory transfer requests
- [x] Execution service: carrier change requests
- [x] Execution service: SAP API execution
- [x] Mock execution adapters where real credentials are unavailable, clearly labelled

---

## STEP 7 — SAP Integration ✅

- [x] Modular SAP connector
- [x] Environment-based authentication
- [x] Explore/prepare connectors: SAP S/4HANA
- [x] Explore/prepare connectors: SAP Business Accelerator Hub APIs
- [x] Explore/prepare connectors: SAP BTP
- [x] Explore/prepare connectors: SAP Integration Suite
- [x] Read: shipment information
- [x] Read: purchase orders
- [x] Read: supplier records
- [x] Read: inventory levels
- [x] Read: material information
- [x] Write: shipment plan updates (where supported)
- [x] Write: inventory transfer requests (where supported)
- [x] Write: approved operational changes
- [x] Request validation
- [x] Rate-limit and API-failure handling
- [x] Log requests/responses without exposing secrets
- [x] Separate read and write permissions
- [x] Approval required before sensitive write operations
- [x] Labelled mock SAP adapter if sandbox credentials are unavailable

---

## STEP 8 — Agent Activity and Decision Dashboard ✅

- [x] Overview page
- [x] Disruption Monitoring page
- [x] Agent Activity page (**highest priority**)
- [x] Scenario Comparison page
- [x] Approval Center page
- [x] Shipment Management page
- [x] Inventory Management page
- [x] Audit History page
- [x] Agent Activity: workflow ID, active disruption, supervisor decision
- [x] Agent Activity: five agents, execution status, current task, tools invoked
- [x] Agent Activity: structured results, handoffs, replanning events, progress, errors/retries
- [x] React Flow agent workflow visualisation
- [x] Scenario Comparison: route, delivery time, cost, risk, inventory impact, compliance, recommendation
- [x] Approval Center: proposed action, reason, cost/risk impact, validations, controls, history
- [x] Enterprise control-tower design (dark navy / clean light theme)
- [x] Responsive layout, professional status indicators, interactive charts
- [x] Every page connected to actual FastAPI endpoints
- [x] Loading, error and empty states
- [x] No hardcoded fake agent execution results

---

## STEP 9 — Testing and End-to-End Validation ✅

> The Mumbai → Rotterdam golden path is verified end to end by a deterministic
> E2E test (all five agents, approval pause, Director approval, three labelled
> `[SIMULATED]` executions, replay refused). A live replay through Gemini was
> attempted three times and blocked by the free-tier daily quota
> (`429`, 20 requests/day for `gemini-3.6-flash`); the two prior live runs are
> recorded as genuine failures and the successful live approval/execution proof
> comes from `EV-UI-VERIFY-003`, which completed and executed after the quota
> window. Details: `backend/docs/validation-report.md`.

- [x] End-to-end scenario: Mumbai → Rotterdam pharmaceutical maritime disruption
- [x] Verify disruption ingestion
- [x] Verify Disruption Sensing Agent
- [x] Verify risk scoring
- [x] Verify supervisor delegation
- [x] Verify Scenario Planning Agent
- [x] Verify Rerouting & Logistics Agent
- [x] Verify Inventory Rebalancing Agent
- [x] Verify Compliance & Audit Agent
- [x] Verify agent collaboration
- [x] Verify autonomous replanning
- [x] Verify human approval
- [x] Verify workflow checkpointing
- [x] Verify authorised execution
- [x] Verify SAP connector
- [x] Verify database persistence
- [x] Verify audit history
- [x] Verify frontend updates
- [x] Failure test: Gemini API unavailable
- [x] Failure test: external API timeout
- [x] Failure test: invalid LLM output
- [x] Failure test: missing shipment data
- [x] Failure test: no alternative routes
- [x] Failure test: insufficient inventory
- [x] Failure test: compliance violation
- [x] Failure test: manager rejects proposal
- [x] Failure test: duplicate execution request
- [x] Failure test: database connection failure
- [x] Add unit tests
- [x] Add integration tests
- [x] Add end-to-end workflow tests
- [x] Fix critical errors
- [x] Validate security boundaries
- [x] Check logging and exception handling
- [x] Verify workflow state persists
- [x] Verify rejected actions are never executed
- [x] Generate final report (features, limitations, results, bugs, readiness)

**Step 9 defects found and fixed**

- [x] Scenario-path inventory transfer never reached the audit/proposal/execution
      plan (only the standalone rebalancing node was read) — carried on
      `ScenarioPlan.inventory_transfer_units` with fallbacks in the workflow and
      proposal builder
- [x] `Rotterdam DC` held no `MAT-PHARMA-001` position, so the Mumbai → Rotterdam
      rebalancing target failed — added the eighth seed inventory row
- [x] No test covered the scenario path E2E, an HTTP timeout, or a database outage
      in the dashboard API — three tests added

**Test totals:** 368 passed, 6 skipped (`pytest` from `backend/`). Full report:
`backend/docs/validation-report.md`.

---

## STEP 10 — Deployment and Hackathon Demonstration

- [x] Prepare Dockerfiles (`backend/Dockerfile` non-root + liveness healthcheck,
      `frontend/Dockerfile` multi-stage node build → nginx)
- [x] Configure Docker Compose (`db`, one-shot `seed`, `backend`, `frontend`;
      named volume, dependency-ordered health, `stop_grace_period`)
- [x] Configure frontend and backend environment variables (Compose anchor,
      `DATABASE_URL` left empty so discrete `POSTGRES_*` apply; secrets stay in
      `backend/.env`, never baked into images)
- [x] Configure PostgreSQL (postgres:16-alpine, `pg_isready`, idempotent seed of
      5 suppliers / 10 shipments)
- [x] Configure persistent workflow checkpoints (`LANGGRAPH_CHECKPOINT_BACKEND=postgres`;
      4 checkpoint tables, 40 rows, state survived a backend restart)
- [x] Verify service communication (nginx `/api` proxy to `backend:8000`; 200 via
      `:8080`; CORS origins set for `localhost:8080`)
- [x] Add health checks (backend `/api/health/live`, nginx `/healthz`, DB
      `pg_isready`, Compose conditions)
- [x] Verify startup and shutdown behaviour (ordered start; graceful uvicorn
      shutdown on `docker compose stop`; clean restart)
- [x] Prepare one complete Red Sea disruption demo scenario
- [x] Demo shows disruption detection
- [x] Demo shows supervisor reasoning and task delegation
- [x] Demo shows all five specialised agents executing
- [x] Demo shows external tool usage
- [x] Demo shows deterministic calculations
- [x] Demo shows agent collaboration
- [x] Demo shows scenario comparison
- [x] Demo shows compliance rejection and replanning
- [x] Demo shows human approval
- [x] Demo shows authorised execution
- [x] Demo shows audit record creation
- [x] Final deliverables: architecture diagram
- [x] Final deliverables: LangGraph workflow diagram
- [x] Final deliverables: API documentation
- [x] Final deliverables: database schema
- [x] Final deliverables: test report
- [x] Final deliverables: demo scenario and sample data
- [x] Ensure all presentation claims match implemented functionality (docs
      distinguish live vs `[SIMULATED]`; failed demo runs are recorded as failed;
      `backend/docs/test-report.md` §6.1 carries the container evidence)

**Step 10 verification**

- Container stack: `db` healthy, `seed` exited 0, `backend` healthy, `frontend`
  healthy; `/api/health` connected through both `:8000` and `:8080`.
- Checkpoint persistence: 40 rows across 4 LangGraph tables; thread state readable
  after `docker compose restart backend`.
- Lifecycle: `docker compose stop` logged a clean uvicorn shutdown; `start`
  brought db → backend → frontend up in order.
- Live demo blocked by upstream Gemini quota (`503` then `429`, 20/day free
  tier); four attempts recorded as failed with no execution. Golden path remains
  proven by the deterministic E2E test (no Gemini call).

**Multi-key Gemini follow-up (2026-11-24)**

- [x] Accept multiple keys (`GEMINI_API_KEYS`) with deduplication against `GEMINI_API_KEY`
- [x] Distribute keys across the five agents deterministically (round-robin, `GEMINI_KEY_SLOTS` overrides)
- [x] Fail loudly on unknown agents or out-of-range slots
- [x] Add per-key request pacing (`GEMINI_MIN_INTERVAL_SECONDS`) shared across agents
- [x] Make retry backoff configurable (`GEMINI_RETRY_BACKOFF_SECONDS`)
- [x] Tests for assignment, wiring, request headers, fail-loud errors and pacing (14 new)
- [x] Treat a daily-quota 429 as terminal for that key (no in-process retry; supervisor does not retry the agent)
- [x] Quarantine an exhausted key for its reset window and rotate to the agent's next key in slot order
- [x] Honour only short Google `retryDelay` values (`GEMINI_QUOTA_RETRY_MAX_SECONDS`, default 120 s)
- [x] Fail with quota id, model and UTC reset time only when every key is cooling down
- [x] Tests for quota rotation, quarantine, short delays and fallback order (8 new)
- [x] Live probe of both assigned keys (2026-11-24 18:18 UTC, inside the backend container): slot-0 key returned `{"ok": true}`; slot-1 key reported `GenerateRequestsPerDayPerProjectPerModel-FreeTier` and the call rotated to slot 0 and succeeded
- [ ] Full workflow/demo run under live quota (needs ~5 calls of headroom and an approver credential; approval currently fails closed with 503)

**One-click Start and overload guard (2026-11-25)**

- [x] Add a process-wide `WorkflowGuard` that admits one supervisor run at a time
- [x] Route both start endpoints through the guard; a concurrent start returns `409` with the active thread id
- [x] Add `POST /api/orchestration/workflows/start` using the bundled Red Sea scenario under a fresh `EV-UI-START-…` event id
- [x] Add `GET /api/orchestration/workflows/active` for the UI's disabled state
- [x] Add the Overview **Start agents** panel with running state, active-run polling and run output
- [x] Tests for the guard, both endpoints, run recording, active endpoint, fresh ids and missing-demo failure (9 new)
- [x] Live UI click started one run; concurrent start returned `409`; run recorded `awaiting_approval` (4 agent executions, proposal `632eec40e5aa393c`)
- [x] Rebuild backend and frontend containers; health and proxy verified

**Approval Center token fix (2026-11-25)**

- [x] 401 message explains that only the token part (before the first `:`) is sent
- [x] API client attaches the HTTP status so the UI can detect auth failures
- [x] Approval Center clears a rejected token from sessionStorage and prompts re-entry
- [x] Field label, placeholder and empty state describe the `token:id:Role` format
- [x] Tests assert the hint and reject the whole-entry form
- [x] Live: stale token cleared and explained; correct token loads the pending proposal and its run context; decision left to the human approver

**Test totals:** 406 collected, 400 passed, 6 skipped, 0 failures (`pytest` from
`backend/` using the repository `.venv`). Full report:
`backend/docs/test-report.md`.

---

## Cross-cutting (applies to every step)

- [x] Progress files maintained (`PROJECT_PROGRESS.md`, `DEVELOPMENT_LOG.md`, `TASK_CHECKLIST.md`)
- [x] Gemini API key available (configured and verified live, `gemini-3.5-flash`)
- [x] PostgreSQL credentials configured (live managed instance, demo data seeded)
- [x] SAP credentials available, otherwise clearly labelled mock mode
- [x] Tests added for every major component
- [x] README updated after each major phase
- [x] No secrets committed or exposed in frontend code
- [x] Human approval enforced before high-impact real-world actions

---

## Progress summary

| Step | Status |
| --- | --- |
| 0 — Project Initialization | ✅ Complete |
| 1 — Gemini + Disruption Sensing Agent | ✅ Complete |
| 2 — Tools + Deterministic Business Logic | ✅ Complete |
| 3 — Remaining Four Agents | ✅ Complete |
| 4 — LangGraph Supervisor | ✅ Complete |
| 5 — Collaboration + Replanning | ✅ Complete |
| 6 — Human-in-the-Loop + Execution | ✅ Complete |
| 7 — SAP Integration | ✅ Complete |
| 8 — Agent Activity Dashboard | ✅ Complete |
| 9 — Testing + E2E Validation | ✅ Complete |
| 10 — Deployment + Demo | ✅ Complete |
