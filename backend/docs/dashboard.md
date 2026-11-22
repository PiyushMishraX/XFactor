# Step 8 — Agent Activity and Decision Dashboard

The dashboard is a **read-only projection** of state the platform already
produced. It contains no decision logic, no sample agent activity and no write
endpoints: every number and every execution row is read from PostgreSQL or from
the existing SAP connector. The checkpoint remains the source of truth for
resuming a workflow.

## 1. What is persisted

### `workflow_runs` (`app/models/workflow_runs.py`)

One row per LangGraph thread, written by `record_workflow_run`
(`app/services/workflow_history.py`):

| Column | Meaning |
| --- | --- |
| `thread_id` (PK) | The supervisor thread id (defaults to the disruption event id). |
| `event_id`, `disruption_type`, `severity`, `location`, `origin`, `destination` | Queryable summary taken from the recorded request/assessment. |
| `status`, `awaiting_approval` | Final or current workflow status, and whether a human gate is open. |
| `risk_score`, `recommended_scenario_id` | Deterministic assessment score and the supervisor's selection. |
| `headline`, `summary` | Human-readable summary from the recommendation or assessment. |
| `execution_count`, `error_count` | Counts of recorded agent executions and errors. |
| `state_json` | The **complete JSON-safe workflow state** (assessment, scenario plan, execution records, decisions, approval history, replanning). |
| `created_at`, `updated_at` | Record lifecycle timestamps. |

`json_safe()` recursively converts the graph result for storage: LangGraph's
live `__interrupt__` object and private `__*` keys are dropped, datetimes and
decimals are converted, and unknown objects fall back to their string form.

### When a row is written

- `POST /api/orchestration/workflows` records the run after the graph returns,
  including runs that end in failure (the recorded error is preserved).
- `POST /api/approvals/{thread_id}/decision` refreshes the same row after an
  authenticated decision, so the dashboard reflects the post-approval state.

Recording is **best-effort**: a history failure is logged and rolled back and
must never lose a completed workflow or fail a decision. `session=None` is a
deliberate no-op used by API tests that inject no database.

`ensure_workflow_run_schema()` runs at startup next to the approval schema and
creates the table when it is missing (idempotent).

## 2. API surface (`app/api/dashboard.py`, `app/services/dashboard_service.py`)

| Endpoint | Returns |
| --- | --- |
| `GET /api/dashboard/overview` | KPI counts (`runs`, `awaiting_approval`, `failed`, `rejected`, agent executions, errors, by-status, shipments, suppliers), the five latest runs and the declared data sources. |
| `GET /api/dashboard/runs?limit=&status=` | Recorded run summaries, newest update first. |
| `GET /api/dashboard/runs/{thread_id}` | One run plus its full recorded `state`; `404` when the thread is unknown. |
| `GET /api/dashboard/disruptions?limit=` | Recent assessed disruptions with the assessment, affected shipments/suppliers, risk breakdown, impact, the supervisor's latest decision and the recommendation headline. |
| `GET /api/dashboard/shipments` | Seeded shipment master data joined with supplier records. |
| `GET /api/dashboard/inventory` | SAP connector inventory positions and material master, with `is_mock`, `source` and `endpoint` provenance. |

A database failure maps to `503`; an unconfigured live SAP connector maps to
`503`. There is no fallback payload and no invented run.

## 3. Page-to-endpoint mapping

| Page | Reads |
| --- | --- |
| Overview | `/dashboard/overview` |
| Disruption Monitoring | `/dashboard/disruptions`, `/dashboard/runs/{thread_id}` |
| Agent Activity | `/dashboard/runs`, `/dashboard/runs/{thread_id}` |
| Scenario Comparison | `/dashboard/runs`, `/dashboard/runs/{thread_id}` |
| Approval Center | `/approvals/*` (authenticated) plus `/dashboard/runs/{thread_id}` for context |
| Shipment Management | `/dashboard/shipments` |
| Inventory Management | `/dashboard/inventory` |
| Audit History | `/dashboard/runs`, `/dashboard/runs/{thread_id}` |

The Agent Activity page renders the supervisor decision log, the five agent
cards, the recorded `AgentExecution`/`ToolInvocation` rows, handoffs, replanning
records, progress and errors, plus a React Flow graph built from the recorded
executions (not from a fabricated topology of "active" agents).

## 4. Provenance and honesty rules

- Shipments are the **seeded demo reference rows** in PostgreSQL, labelled as
  such on the page and in the API response's `source`.
- Inventory comes from the Step 2/7 SAP connector. With `SAP_USE_MOCK=true` it is
  labelled `[SIMULATED]` from the record's `Provenance`; the UI shows that banner
  instead of implying live SAP data.
- A failed run is shown as failed, with its recorded error text. Nothing is
  back-filled to look successful.
- Empty states are real: zero runs, no scenario plan, no pending approvals and an
  empty inventory all render an explicit empty state.

## 5. Verification performed

- Backend: `tests/test_dashboard.py` — 12 tests (summary derivation, one-row
  upsert, ordering/filtering, disruption detail, JSON-safe stripping, overview
  counts, run/detail endpoints, shipment and inventory payloads, recording on
  workflow start, route mounting). Full suite: **364 passed, 6 skipped**.
- Frontend: `npm run build` passes; `npm run lint` reports 0 errors.
- Browser walkthrough (Vite + live backend + Aiven PostgreSQL) covered Overview,
  Shipment Management, Inventory Management, Disruption Monitoring, Agent
  Activity (a real failed run with React Flow, timeline, tool and handoff rows),
  Scenario Comparison (empty-plan state), Audit History, and the Approval Center's
  fail-closed token handling.

### Limitation recorded, not hidden

Two real verification runs (`EV-UI-VERIFY-001`, `EV-UI-VERIFY-002`) failed
because Gemini returned `503 UNAVAILABLE` and then `429` free-tier quota
exhaustion. They are genuine failed runs in the shared database. Because of that,
the **populated successful** Scenario Comparison and Approval Center views were
not exercised in a browser on 2026-11-22; those request/response paths are covered
by the backend tests. No successful run was simulated to mask this.

## 6. Configuration

Step 8 adds **no environment variable**. It uses the existing `DATABASE_URL`
(workflow history and shipments) and the existing SAP connector settings
(inventory).
