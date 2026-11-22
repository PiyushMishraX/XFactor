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

**Phase: Step 9 — Testing and End-to-End Validation (complete).**

Steps 0–8 delivered the platform skeleton, Gemini reasoning, the deterministic
tools, all five specialised agents, the compiled LangGraph supervisor, the
auditable collaboration layer, the authenticated approval and execution path,
the SAP read/write boundary and the control-tower dashboard.

Step 9 validated the whole product without adding features:

- a **deterministic end-to-end test** drives the Mumbai → Rotterdam
  pharmaceutical maritime disruption through all five agents, deterministic
  calculations, the approval interrupt, a Director decision and three labelled
  `[SIMULATED]` executions, and proves a replay is refused;
- **live approval and execution** were completed on a recorded workflow
  (`EV-UI-VERIFY-003`): `401`/`403`/`409` boundaries, Director approval,
  idempotent execution and a refreshed `workflow_runs` row;
- **checkpoint persistence** was proven by approving a run created before
  several backend restarts;
- **failure handling** is covered for Gemini unavailability/quota, HTTP timeout,
  invalid model output, missing shipment, no viable route, insufficient
  inventory, compliance violation, rejection, duplicate execution and database
  outage;
- **three defects were found and fixed**: the scenario path never passed the
  inventory transfer to audit/approval/execution, the Rotterdam DC pharma
  inventory position was missing, and three paths had no tests.

A live Mumbai replay was blocked by the Gemini free-tier daily quota (`429`,
20 requests/day for `gemini-3.6-flash`); the failed runs are recorded honestly.
See [backend/docs/validation-report.md](backend/docs/validation-report.md) for
the full 17-point audit, failure matrix and limitations.

Backend suite: **368 passed, 6 skipped** (the skips are the opt-in
`RUN_LIVE_GEMINI=1` tests; run pytest from `backend/`). Frontend build and lint
pass.

The next step is **Step 10 — Deployment and Hackathon Demonstration**
(not started).

Workflow details: [backend/docs/workflow.md](backend/docs/workflow.md),
[backend/docs/collaboration.md](backend/docs/collaboration.md),
[backend/docs/approval-and-execution.md](backend/docs/approval-and-execution.md),
[backend/docs/sap-integration.md](backend/docs/sap-integration.md),
[backend/docs/dashboard.md](backend/docs/dashboard.md) and
[backend/docs/validation-report.md](backend/docs/validation-report.md).
See [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md) for the live status and
[DEVELOPMENT_ROADMAP.txt](DEVELOPMENT_ROADMAP.txt) for the full roadmap.
