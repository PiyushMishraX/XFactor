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
│   ├── demo/                  Red Sea demo scenario payloads
│   ├── docs/                  Architecture, deployment, API, schema, workflow,
│   │                          collaboration, approval, SAP, dashboard and
│   │                          validation notes
│   ├── Dockerfile
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
│   ├── Dockerfile             Vite build + nginx
│   ├── nginx.conf             SPA fallback and /api proxy
│   ├── vite.config.js         Dev server + /api proxy
│   └── .env.example
├── docker-compose.yml         PostgreSQL + seed + backend + frontend
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
| `POST /api/orchestration/workflows/start` | One-click Start: the bundled demo scenario, once, under a fresh event id |
| `GET /api/orchestration/workflows/active` | Whether a supervisor run currently holds the single-flight slot |
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

Both start endpoints are admitted through one process-wide single-flight guard:
while a run is in flight, another start returns `409` with the active thread id,
so repeated clicks, extra tabs and the shipment form cannot launch overlapping
five-agent runs. The dashboard's **Start agents** button and the active-run
status endpoint use the same slot. This assumes the single-uvicorn-worker
deployment in the Compose stack; horizontal scaling would need a database
advisory lock instead.

### Frontend (http://localhost:5173)

```powershell
cd "d:\X Factor\frontend"
npm run dev
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8000`, so the frontend
never needs CORS or a hard-coded backend host.

### Docker Compose (demo deployment)

```powershell
cd "d:\X Factor"
# backend\.env must contain GEMINI_API_KEY and (for approvals) APPROVER_CREDENTIALS
docker compose up --build -d
```

| Service | URL | Notes |
| --- | --- | --- |
| Frontend | `http://localhost:8080` | nginx serves the SPA and proxies `/api` |
| Backend | `http://localhost:8000` | API docs at `/docs`, health at `/api/health` |
| PostgreSQL | internal `db:5432` | Named volume `postgres-data` keeps runs, approvals and checkpoints |
| Seed | one-shot | Idempotently loads 5 suppliers and 10 shipments |

`docker compose down` keeps the data volume; `down -v` is destructive. See
[backend/docs/deployment.md](backend/docs/deployment.md) for health checks,
startup/shutdown behaviour, environment wiring and troubleshooting, and
[backend/docs/demo-script.md](backend/docs/demo-script.md) for the walkthrough.

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
| `GEMINI_API_KEYS`, `GEMINI_KEY_SLOTS` | Extra keys and per-agent assignment (round-robin by default) |
| `GEMINI_MIN_INTERVAL_SECONDS`, `GEMINI_RETRY_BACKOFF_SECONDS`, `GEMINI_QUOTA_RETRY_MAX_SECONDS` | Per-key request spacing, retry backoff and short quota-wait ceiling |
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

**Phase: Step 10 — Deployment and Hackathon Demonstration (complete).**

Steps 0–9 delivered the platform skeleton, Gemini reasoning, the deterministic
tools, all five specialised agents, the compiled LangGraph supervisor, the
auditable collaboration layer, the authenticated approval and execution path,
the SAP read/write boundary, the control-tower dashboard, and a validated
end-to-end product.

Step 10 packaged and documented the product without changing its logic:

- **Docker images** for the backend and frontend (nginx serving the built SPA and
  reverse-proxying `/api` to the backend, so the browser stays same-origin);
- **Docker Compose** with PostgreSQL 16, a one-shot idempotent seed job, the
  backend with PostgreSQL LangGraph checkpoints, and dependency-ordered health
  checks and restart behaviour;
- a **Red Sea demo scenario** (Mumbai → Rotterdam pharma, `SH001`/`SUP001`) plus
  a replan variant that triggers a deterministic compliance rejection, and
  `scripts/run_demo_scenario.py` to drive it with an authenticated decision;
- deliverable documentation: architecture, LangGraph diagram, API reference,
  database schema, deployment guide, demo script and this test report.

Verified live: all four containers healthy, seed loaded 5 suppliers / 10
shipments, the `/api` proxy works through `:8080`, 40 checkpoints persisted in
PostgreSQL and survived a backend restart, stop/start is clean and ordered, and
approvals fail closed without a credential. The live demo itself is blocked by
the Gemini free-tier daily quota (`503` then `429`); the failed runs are recorded
honestly and no execution occurred. Gemini failures are now handled as the quota
error they are: an exhausted key is quarantined and the call rotates to the next
configured key, short per-minute retry delays are honoured, and a run fails fast
with the quota id and reset time only when every key is out. A live probe on
2026-11-24 confirmed the slot-0 key answers and an exhausted slot-1 key rotates to
slot 0 and succeeds; the full demo still needs ~5 calls of headroom. The
authoritative golden-path proof is the deterministic end-to-end test, which does
not call Gemini.

**One-click Start with single-flight admission:** the Overview page has a
**Start agents** button that runs the validated Red Sea scenario once under a
fresh `EV-UI-START-…` id and shows the run output (status, agents executed,
proposal version, recommendation or errors) with links to Agent Activity and the
Approval Center. The backend guard refuses a concurrent start with `409`; this
was verified live on 2026-11-25 UTC: a UI click started a run, the button showed
**Agents running…**, a second POST returned `409` naming the active thread, and
the completed run recorded `awaiting_approval` with four agent executions and a
proposal version. One transient Gemini `503` was retried by the supervisor and
recorded truthfully.

Backend suite: **400 passed, 6 skipped** (406 collected; the skips are the opt-in
`RUN_LIVE_GEMINI=1` tests; run pytest from `backend/` with the repository
virtualenv). Frontend build and lint pass.

Start the demo with `docker compose up --build`, open
<http://localhost:8080>, and follow
[backend/docs/demo-script.md](backend/docs/demo-script.md).

Documents: [architecture](backend/docs/architecture.md),
[workflow](backend/docs/workflow.md),
[LangGraph diagram](backend/docs/langgraph-workflow.mmd),
[API](backend/docs/api.md), [database schema](backend/docs/database-schema.md),
[collaboration](backend/docs/collaboration.md),
[approval and execution](backend/docs/approval-and-execution.md),
[SAP integration](backend/docs/sap-integration.md),
[dashboard](backend/docs/dashboard.md),
[deployment](backend/docs/deployment.md),
[demo script](backend/docs/demo-script.md),
[test report](backend/docs/test-report.md) and the
[Step 9 validation report](backend/docs/validation-report.md).
See [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md) for the live status and
[DEVELOPMENT_ROADMAP.txt](DEVELOPMENT_ROADMAP.txt) for the full roadmap.
