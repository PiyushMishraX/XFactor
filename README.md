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
│   │   ├── api/               HTTP routers (health check)
│   │   ├── agents/            Specialised AI agents (Steps 1 & 3)
│   │   ├── orchestration/     LangGraph supervisor (Steps 4–6)
│   │   ├── tools/             Deterministic business logic (Step 2)
│   │   ├── integrations/      External APIs and SAP connectors (Steps 2 & 7)
│   │   ├── models/            SQLAlchemy ORM models
│   │   ├── schemas/           Pydantic schemas
│   │   ├── services/          Application services (execution, approval)
│   │   ├── database/          Engine, sessions, declarative base
│   │   ├── config/            Settings and logging configuration
│   │   └── utils/             Shared helpers
│   ├── tests/                 pytest test-suite
│   ├── docs/                  Workflow, collaboration and approval design notes
│   ├── requirements.txt
│   ├── pytest.ini
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/        Reusable UI components
│   │   ├── pages/             Route-level pages
│   │   ├── services/          Backend API client
│   │   ├── hooks/             React hooks
│   │   ├── layouts/           Page shells
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
| `SAP_BASE_URL`, `SAP_CLIENT_ID`, `SAP_CLIENT_SECRET`, `SAP_USE_MOCK` | SAP integration |
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

**Phase: Step 6 — Human-in-the-Loop and Authorized Execution (complete).**

Steps 0–5 delivered the platform skeleton, Gemini reasoning, the deterministic
tools, all five specialised agents, the compiled LangGraph supervisor and the
auditable collaboration layer. Step 6 makes the human decision and the
subsequent action safe:

- the paused proposal is snapshotted and versioned deterministically, and a
  decision is rejected if it targets a stale version;
- only a bearer-authenticated approver with the required role can decide; the
  approver identity and timestamp are recorded, and the full decision history is
  preserved across reconsideration rounds;
- an approver may approve, reject or request modifications, with the modification
  loop bounded by `MAX_MODIFICATION_ROUNDS = 2`;
- only an approved, completed workflow is executed, through an idempotent
  execution service (shipment plan update, inventory transfer, carrier change and
  SAP execution) that is clearly `[SIMULATED]` by default;
- the approval interface lives in the frontend Approval Center tab.

Backend suite: **315 passed, 6 skipped** (the skips are the opt-in
`RUN_LIVE_GEMINI=1` tests).

The next step is **Step 7 — SAP Integration** (not started). The Step 6 execution
adapter is the write path SAP integration will eventually target.

Workflow details: [backend/docs/workflow.md](backend/docs/workflow.md),
[backend/docs/collaboration.md](backend/docs/collaboration.md) and
[backend/docs/approval-and-execution.md](backend/docs/approval-and-execution.md).
See [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md) for the live status and
[DEVELOPMENT_ROADMAP.txt](DEVELOPMENT_ROADMAP.txt) for the full roadmap.
