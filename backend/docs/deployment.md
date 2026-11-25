# X FACTOR — Deployment

The demo stack is four containers: PostgreSQL, a one-shot seed job, the FastAPI
backend and nginx serving the React build. The application is unchanged by
containerisation — the same images run the same code paths verified in Steps
0–9.

---

## 1. Prerequisites

| Tool | Version used |
| --- | --- |
| Docker Desktop | 29.1.3 (Engine + Compose v2.40) |
| Gemini API key | `GEMINI_API_KEY` in `backend/.env` |
| Approver credential | `APPROVER_CREDENTIALS` in `backend/.env` for live decisions |

No host Python or Node is needed for the Compose deployment.

---

## 2. Compose topology

| Service | Image / build | Port | Health check |
| --- | --- | --- | --- |
| `db` | `postgres:16-alpine` | internal 5432 | `pg_isready` |
| `seed` | built from `./backend` | — | exits after seeding |
| `backend` | built from `./backend` | `8000:8000` | `GET /api/health/live` |
| `frontend` | built from `./frontend` | `8080:80` | `GET /healthz` |

- `frontend` waits for `backend` to be healthy.
- `backend` waits for `db` to be healthy **and** `seed` to complete.
- `seed` is idempotent (`primary-key merge`), so every `up` refreshes the demo
  master data without duplicating rows.

---

## 3. Environment configuration

Compose reads `backend/.env` (never baked into an image) and overrides the
database target so the bundled PostgreSQL is always used:

| Variable | Compose source | Notes |
| --- | --- | --- |
| `DATABASE_URL` | forced empty | Empty means use the discrete `POSTGRES_*` parts |
| `POSTGRES_HOST` | forced `db` | Container network name |
| `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `${...:-xfactor}` | Override from the shell or a root `.env` |
| `LANGGRAPH_CHECKPOINT_BACKEND` | forced `postgres` | Persistent checkpoints |
| `CORS_ORIGINS` | `http://localhost:8080,...` | Only needed for direct API calls |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, … | `backend/.env` | LLM reasoning |
| `GEMINI_API_KEYS`, `GEMINI_KEY_SLOTS` | `backend/.env` | Extra keys and per-agent slot overrides |
| `GEMINI_MIN_INTERVAL_SECONDS`, `GEMINI_RETRY_BACKOFF_SECONDS` | `backend/.env` | Per-key pacing and retry spacing |
| `GEMINI_QUOTA_RETRY_MAX_SECONDS` | `backend/.env` | Longest quota retry delay waited on; longer (daily) quotas rotate keys |
| `APPROVER_CREDENTIALS` | `backend/.env` | Fail-closed `503` when unset |
| `SAP_*`, `EXECUTION_*`, `*_API_BASE_URL` / keys | `backend/.env` | Simulated adapters by default |

### Gemini key distribution

Set `GEMINI_API_KEY` to one key and `GEMINI_API_KEYS=key2,key3…` for the rest
(duplicates are ignored). With two keys the agents are assigned round-robin:

| Agent | Key slot |
| --- | --- |
| `disruption_sensing` | 0 |
| `scenario_planning` | 1 |
| `rerouting_logistics` | 0 |
| `inventory_rebalancing` | 1 |
| `compliance_audit` | 0 |

Override any of them with `GEMINI_KEY_SLOTS="agent=index,…"`; unknown agents or
out-of-range slots fail at startup instead of silently sharing a key.

Each HTTP attempt waits until `GEMINI_MIN_INTERVAL_SECONDS` has elapsed since
the previous request **on that key** (state is per process and shared by agents
holding the same key). Retry attempt *N* waits *N ×*
`GEMINI_RETRY_BACKOFF_SECONDS`. Pacing is skipped when the interval is `0`.

### Quota failures, rotation and quarantine

A free-tier key that exhausts its daily quota answers HTTP `429` with
`RESOURCE_EXHAUSTED`, a `QuotaFailure` detail (for example
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`) and a `RetryInfo` delay of
hours. Sleeping for that long inside a request is useless, so the client:

1. does **not** retry the same key — the supervisor also treats quota exhaustion
   as terminal for that agent instead of retrying the agent;
2. quarantines the key for the reported window (process-wide, by key
   fingerprint) and immediately tries the agent's next key in rotation;
3. waits in-process only when Google reports a *short* delay
   (`≤ GEMINI_QUOTA_RETRY_MAX_SECONDS`, default 120 s), which fits a per-minute
   throttle;
4. fails with the quota id, model and reset time only when every configured key
   is exhausted.

Note that Google's daily request quota is counted **per project, per model**.
Two keys from the same Google Cloud project share one 20-request bucket, so
rotation only adds capacity when the keys belong to different projects (or when
billing is enabled).

To point the deployment at an external database instead, replace the
`DATABASE_URL` override in `docker-compose.yml`.

Secrets are never copied into an image (`backend/.dockerignore` excludes
`.env`) and are never exposed to the frontend — only names appear in docs.

---

## 4. Run

```powershell
cd "D:\X Factor"

# 1. Configure secrets (once).
Copy-Item backend\.env.example backend\.env
#    Edit backend\.env: set GEMINI_API_KEY and APPROVER_CREDENTIALS.

# 2. Build and start.
docker compose up --build -d

# 3. Readiness.
docker compose ps
curl http://localhost:8000/api/health
curl http://localhost:8080/healthz
```

Open `http://localhost:8080` for the dashboard and
`http://localhost:8000/docs` for the API.

Stop and restart:

```powershell
docker compose down          # keeps the postgres-data volume (runs, approvals, checkpoints)
docker compose up -d         # picks up where the data left off
docker compose down -v      # destructive: deletes the volume and all recorded state
```

---

## 5. Persistent workflow checkpoints

- `LANGGRAPH_CHECKPOINT_BACKEND=postgres` selects `PostgresSaver`.
- `PostgresSaver.setup()` creates `checkpoints`, `checkpoint_blobs`,
  `checkpoint_writes` and `checkpoint_migrations` idempotently.
- The database directory lives on the named volume `postgres-data`.
- Consequently a workflow that pauses for approval can be approved after a
  `docker compose restart` (or a full `down`/`up`) and resumes from its saved
  state. This was verified for `EV-UI-VERIFY-003` across backend restarts in
  Step 9.

---

## 6. Startup and shutdown behaviour

- Startup runs the FastAPI lifespan hook: logs the version/environment, checks
  PostgreSQL, and ensures the `approval_requests` and `workflow_runs` schemas.
  A database outage does **not** crash the process; `/api/health` reports
  `degraded` and database-backed endpoints return `503`.
- The image runs a single uvicorn process (no `--reload`).
- `stop_grace_period: 30s` lets in-flight requests finish. Uvicorn handles
  `SIGTERM`, which runs the lifespan shutdown log; PostgreSQL closes cleanly.
- `restart: unless-stopped` restarts the API and frontend after a daemon
  restart; `seed` has `restart: "no"`.

### Single-flight start admission

Both workflow start paths — `POST /api/orchestration/workflows` and the
dashboard's one-click `POST /api/orchestration/workflows/start` — are admitted
through one process-wide `WorkflowGuard` (a non-blocking `threading.Lock`). While
a run is in flight, another start returns `409` naming the active thread, so
repeated clicks, extra tabs and the shipment form cannot launch overlapping
five-agent runs and multiply Gemini load. `GET
/api/orchestration/workflows/active` reports the slot for the UI.

The guard is in-process and therefore correct for this stack's single uvicorn
worker. A multi-worker or multi-replica deployment would need a database
advisory lock instead; do not add `--workers` without replacing the guard.

---

## 7. Health checks

| Probe | Use |
| --- | --- |
| `GET /api/health/live` | Container liveness; no dependencies |
| `GET /api/health` | Readiness view; reports `status: ok/degraded` and database state |
| `GET /healthz` (nginx) | Frontend container liveness |

The backend container health check deliberately uses the liveness probe, so a
brief database restart does not cause Docker to kill a healthy API process.

---

## 8. Verification performed

Verified on 2026-11-24 from a clean `docker compose up --build`.

| Check | Command | Result |
| --- | --- | --- |
| Compose model | `docker compose config --quiet` | valid |
| Backend / seed image | `docker compose build` | built, 407 MB |
| Frontend image | `docker compose build` | built, 74.4 MB |
| Database readiness | `docker compose ps` / `pg_isready` | healthy |
| Seed job | `docker compose logs seed` | exited 0 — 5 suppliers, 10 shipments |
| Backend health | `curl :8000/api/health` | `status: ok`, database connected |
| Frontend proxy | `curl :8080/api/health` | 200, proxied backend JSON |
| SPA | `curl :8080/` | 200 `index.html` |
| Checkpoint tables | `psql \dt` | 4 LangGraph tables present, 40 checkpoint rows |
| Restart persistence | `docker compose restart backend` then read thread state | saved state returned intact |
| Graceful stop | `docker compose stop` | uvicorn logged shutdown complete; all containers exited |
| Restart order | `docker compose start` | db healthy → backend healthy → frontend started |
| Approval auth | `curl :8080/api/approvals/pending` | 401 without token; 503 (fail-closed) when `APPROVER_CREDENTIALS` is unset |
| One-click start (2026-11-25 UTC) | UI **Start agents** click | started one run; button disabled with **Agents running…**; output recorded `awaiting_approval` with 4 agent executions, proposal version `632eec40e5aa393c` |
| Single-flight refusal (2026-11-25 UTC) | second `POST /workflows/start` during that run | `409`, detail named the active `EV-UI-START-20261124-183758-cf0e25` thread |
| Run output | `GET /api/dashboard/runs?limit=1` | thread recorded with status, execution count and one transient Gemini `503` |
| Demo scenario | `python -m scripts.run_demo_scenario` | blocked by upstream Gemini quota (HTTP 503 → 429); four failed runs recorded honestly, no execution |

---

## 9. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `503 The workflow database is unavailable.` | `db` not healthy; check `docker compose logs db`. |
| Approval returns `503` | `APPROVER_CREDENTIALS` is unset in `backend/.env`; set it and recreate the backend. |
| Workflow fails with Gemini `429` | Free-tier daily quota (20 requests/day/model). Wait for reset or use a quota-backed key. |
| Start returns `409` | A supervisor run is already in flight; wait for it to finish. Check `GET /api/orchestration/workflows/active` for the active thread. |
| Start returns `500` “bundled demo scenario is unavailable” | `backend/demo/mumbai_rotterdam_scenario.json` is missing or unreadable in the image; rebuild the backend. |
| Port 8080/8000 already in use | Stop the local Vite/uvicorn processes or change the published ports. |
| Demo run says shipment missing | The `seed` service did not run; `docker compose run --rm seed`. |
| `docker compose build` cannot connect | Start Docker Desktop and wait for the engine. |
