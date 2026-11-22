# X FACTOR

**Agentic AI-Powered Supply Chain Resilience Platform** — built for the SAP Resilient Supply Chains Hackathon.

X FACTOR is not a dashboard of chatbots. It is one coordinated agentic system that
detects supply-chain disruptions, reasons about recovery options with specialised
agents, simulates and compares scenarios, requires human approval for high-impact
actions, and then executes authorised operations.

**Detect → Reason → Simulate → Approve → Execute**

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │  React Frontend (Vite)       │
                    │  Agent Activity & Decision   │
                    │  Center                      │
                    └──────────────┬───────────────┘
                                   │ REST / JSON
                    ┌──────────────▼───────────────┐
                    │  FastAPI Backend             │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  LangGraph Supervisor        │
                    │  (state + conditional edges) │
                    └──────────────┬───────────────┘
                                   │
      ┌────────────┬───────────────┼───────────────┬────────────┐
      ▼            ▼               ▼               ▼            ▼
 Disruption    Scenario      Rerouting &     Inventory     Compliance
 Sensing       Planning      Logistics       Rebalancing   & Audit
      └────────────┴───────────────┴───────────────┴────────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                ▼                                     ▼
        Deterministic tools                  Gemini LLM reasoning
        (calculations, validation)           (interpretation only)
                                   │
                    ┌──────────────▼───────────────┐
                    │  PostgreSQL                  │
                    │  (data + workflow checkpoints)│
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  SAP connectors              │
                    └──────────────────────────────┘
```

Key principles:

- **LLM reasoning is separated from deterministic business logic.** Gemini
  interprets unstructured information; all costs, distances, inventory
  quantities, risk scores and compliance results are computed by deterministic
  Python functions and validated.
- **All agent I/O is structured** with Pydantic schemas.
- **Mocked integrations are always labelled** — mock data is never presented as
  live data.
- **High-impact real-world actions require human approval** and are never
  executed twice.

---

## Project structure

```
X Factor/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app (CORS, logging, error handling)
│   │   ├── api/               HTTP routers (health, orchestration, approvals, dashboard)
│   │   ├── agents/            Specialised AI agents (Steps 1 & 3)
│   │   ├── orchestration/     LangGraph supervisor (Steps 4–6)
│   │   ├── tools/             Deterministic business logic (Step 2)
│   │   ├── integrations/      External APIs and SAP connectors (Steps 2 & 7)
│   │   ├── models/            SQLAlchemy ORM models (incl. workflow run history)
│   │   ├── schemas/           Pydantic schemas
│   │   ├── services/          Application services (execution, approval, dashboard)
│   │   ├── database/          Engine, sessions, declarative base
│   │   ├── config/            Settings and logging configuration
│   │   └── utils/             Shared helpers
│   ├── tests/                 pytest test-suite
│   ├── docs/                  Workflow, collaboration, approval, SAP and dashboard notes
│   ├── requirements.txt
│   ├── pytest.ini
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/        Reusable UI components (incl. the React Flow agent graph)
│   │   ├── pages/             Eight control-tower pages
│   │   ├── services/          Backend API client
│   │   ├── hooks/             React hooks (health check, async data)
│   │   ├── layouts/           Sidebar + topbar shell
│   │   ├── constants/         Agent metadata and navigation
│   │   ├── utils/             Formatting helpers
│   │   └── assets/            Static assets
│   ├── vite.config.js         Dev server + /api proxy
│   └── .env.example
├── MASTER_INSTRUCTIONS.txt    Development rules
├── DEVELOPMENT_ROADMAP.txt    Step-by-step implementation roadmap
├── PROJECT_PROGRESS.md        Recovery file — current state
├── DEVELOPMENT_LOG.md         Chronological development log
└── TASK_CHECKLIST.md          Roadmap task status
```

---

## Prerequisites

| Tool | Version used |
| --- | --- |
| Python | 3.14 (3.11+ should work) |
| Node.js | 24.x |
| npm | 11.x |
| PostgreSQL | optional for Step 0 (needed from later steps) |

---

## Setup

### 1. Backend

```powershell
cd "d:\X Factor"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Configure environment (optional for Step 0)
Copy-Item backend\.env.example backend\.env
# then edit backend\.env and fill in PostgreSQL / Gemini / SAP values
```

### 2. Frontend

```powershell
cd "d:\X Factor\frontend"
npm install
Copy-Item .env.example .env   # optional
```

---

## Running the project

### Backend (http://127.0.0.1:8000)

```powershell
cd "d:\X Factor\backend"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

| Endpoint | Description |
| --- | --- |
| `GET /` | Service index |
| `GET /api/health` | Service + PostgreSQL health |
| `GET /api/health/live` | Liveness probe (no dependencies) |
| `POST /api/orchestration/workflows` | Start a supervisor recovery run |
| `GET /api/orchestration/workflows/{thread_id}/state` | Read the last saved workflow state |
| `GET /api/approvals/pending` | Proposals awaiting an authenticated decision |
| `GET /api/approvals/{thread_id}` | One proposal with its full decision history |
| `POST /api/approvals/{thread_id}/decision` | Approve, reject or request modifications |
| `GET /api/approvals/{thread_id}/execution` | The execution report produced after approval |
| `GET /api/dashboard/overview` | KPI counts, latest runs and declared data sources |
| `GET /api/dashboard/runs` | Recorded workflow runs (newest first, optional `status` filter) |
| `GET /api/dashboard/runs/{thread_id}` | One run with its full recorded workflow state |
| `GET /api/dashboard/disruptions` | Assessed disruptions with the supervisor's decision |
| `GET /api/dashboard/shipments` | Seeded shipment master data with suppliers |
| `GET /api/dashboard/inventory` | SAP inventory positions and materials with provenance |
| `GET /docs` | OpenAPI / Swagger UI |

The `/api/approvals/*` endpoints require `Authorization: Bearer <token>` and
return `503` until `APPROVER_CREDENTIALS` is configured. The unauthenticated
Step 4 resume endpoint was replaced by these authenticated decision endpoints.

### Frontend (http://localhost:5173)

```powershell
cd "d:\X Factor\frontend"
npm run dev
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8000`, so the frontend
never needs CORS or a hard-coded backend host.

---

## Environment variables

Names only — never commit real values.

| Variable | Purpose |
| --- | --- |
| `APP_NAME`, `APP_VERSION`, `APP_ENV`, `DEBUG` | Application metadata |
| `LOG_LEVEL`, `LOG_JSON` | Logging behaviour |
| `API_PREFIX` | API route prefix (default `/api`) |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | PostgreSQL connection |
| `DB_CONNECT_TIMEOUT` | Database connect timeout (seconds) |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS` | Gemini LLM reasoning |
| `LANGGRAPH_MAX_ITERATIONS`, `LANGGRAPH_CHECKPOINT_BACKEND` | Orchestration limits |
| `APPROVER_CREDENTIALS` | Comma-separated `token:approver_id:Role` approver tokens (approval API returns 503 until set) |
| `EXECUTION_USE_MOCK`, `EXECUTION_BASE_URL`, `EXECUTION_CLIENT_ID`, `EXECUTION_CLIENT_SECRET`, `EXECUTION_TIMEOUT_SECONDS`, `EXECUTION_MAX_ATTEMPTS` | Authorized execution (simulated by default) |
| `SAP_API_FAMILY`, `SAP_BASE_URL`, `SAP_AUTH_URL`, `SAP_CLIENT_ID`, `SAP_CLIENT_SECRET` | SAP profile and authentication |
| `SAP_READ_SCOPE`, `SAP_WRITE_SCOPE`, `SAP_WRITE_ENABLED`, `SAP_USE_MOCK` | SAP scopes, separate write permission (disabled by default) and mock mode |
| `VITE_API_BASE_URL` (frontend) | Backend API base URL |

---

## Tests

```powershell
cd "d:\X Factor\backend"
..\.venv\Scripts\python.exe -m pytest -v
```

Frontend production build check:

```powershell
cd "d:\X Factor\frontend"
npm run build
```

---

## Current status

**Phase: Step 8 — Agent Activity and Decision Dashboard (complete).**

Steps 0–7 delivered the platform skeleton, Gemini reasoning, the deterministic
tools, all five specialised agents, the compiled LangGraph supervisor, the
auditable collaboration layer, the authenticated approval and execution path,
and the SAP read/write boundary.

Step 8 adds the control tower:

- a **`workflow_runs` projection** that records every supervisor run (failures
  included) and is refreshed after an authenticated decision; the LangGraph
  checkpoint remains the source of truth for resuming;
- a **read-only `/api/dashboard/*` API** for overview KPIs, run history, one
  run's full state, disruptions, seeded shipments and SAP inventory provenance;
- **eight pages** — Overview, Disruption Monitoring, Agent Activity, Scenario
  Comparison, Approval Center, Shipment Management, Inventory Management and
  Audit History — each with loading, error and empty states;
- an **Agent Activity** view with the workflow id, active disruption, supervisor
  decision trail, five agent executions, current task, tools invoked, structured
  results, handoffs, replanning, progress, errors/retries and a React Flow graph
  drawn from the recorded executions;
- **Scenario Comparison** with route, delivery time, cost, risk, inventory
  impact, feasibility and compliance; and an **Approval Center** with proposed
  action, cost/risk impact, per-agent validations, decision controls and history;
- a responsive dark-navy control-tower theme with a numbered sidebar.

The dashboard recomputes no verdict and contains no sample agent activity. Two
verification runs (`EV-UI-VERIFY-001/002`) failed on live Gemini `503`/`429`
quota, so populated *successful* Scenario Comparison and Approval Center views
were not exercised in a browser; the failure-path UI and every other page were.
See [backend/docs/dashboard.md](backend/docs/dashboard.md) for the details.

Backend suite: **364 passed, 6 skipped** (the skips are the opt-in
`RUN_LIVE_GEMINI=1` tests). Frontend build and lint pass.

The next step is **Step 9 — Testing and End-to-End Validation** (not started).

Workflow details: [backend/docs/workflow.md](backend/docs/workflow.md),
[backend/docs/collaboration.md](backend/docs/collaboration.md),
[backend/docs/approval-and-execution.md](backend/docs/approval-and-execution.md),
[backend/docs/sap-integration.md](backend/docs/sap-integration.md) and
[backend/docs/dashboard.md](backend/docs/dashboard.md).
See [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md) for the live status and
[DEVELOPMENT_ROADMAP.txt](DEVELOPMENT_ROADMAP.txt) for the full roadmap.
