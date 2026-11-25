# X FACTOR — Test Report

**Scope:** unit, integration and end-to-end coverage plus the Step 10 container
verification. The functional audit itself (17 roadmap checks, live run journal,
security checks) is in [validation-report.md](validation-report.md); this report
focuses on how to reproduce the results.

---

## 1. How to run

```powershell
cd "D:\X Factor\backend"
..\.venv\Scripts\python.exe -m pytest -v

cd "D:\X Factor\frontend"
npm run build
npm run lint
```

Run pytest from `backend/` so the `.env` file is found by pydantic-settings;
running from the repository root skips the eight PostgreSQL-backed tests.

---

## 2. Backend suite

| Metric | Result |
| --- | --- |
| Collected | 406 |
| Passed | **400** |
| Skipped | **6** (5 opt-in `RUN_LIVE_GEMINI=1` agent tests, 1 live supervisor test) |
| Failures / errors | 0 |
| Duration | ≈10 s |

| Area | Modules | What is covered |
| --- | --- | --- |
| Agents | `test_disruption_sensing.py`, `test_scenario_planning.py`, `test_rerouting_logistics.py`, `test_inventory_rebalancing.py`, `test_compliance_audit.py` | Deterministic numbers, schema validation, model-cannot-override rules, failure paths |
| LLM client | `test_gemini_service.py`, `test_gemini_multi_key.py`, `test_gemini_quota_rotation.py` | Request shape, retries, key distribution, per-key pacing, quota rotation and quarantine |
| Orchestration | `test_orchestration.py`, `test_collaboration.py` | Routing, interrupts/resume, iteration bound, screening, bounded replanning, JSON state |
| Start admission | `test_workflow_start.py` | Single-flight guard admits one run and names the active thread; both start endpoints return `409` while busy; one-click run records history; active endpoint; fresh event ids; honest `500` when the demo file is missing |
| Approval / execution | `test_approvals.py` | Proposal versions, roles, `401`/`403`/`409`/`503`, idempotent execution, partial failure |
| SAP | `test_sap_integration.py` | Profiles, OAuth, read/write boundary, approval evidence, idempotency |
| Integrations | `test_integrations.py` | Simulated contracts, live adapters via `httpx.MockTransport`, retries, timeout |
| Deterministic tools | `test_risk_scoring.py`, `test_costing.py`, `test_safety_stock.py`, `test_compliance.py`, `test_route_optimization.py`, `test_lead_time.py`, `test_inventory.py`, `test_supplier_ranking.py`, `test_budget.py`, `test_approval.py` | Arithmetic and rule engines |
| Dashboard | `test_dashboard.py` | Projection, endpoints, `404`, database `503`, run recorded on start |
| E2E | `test_e2e_mumbai_rotterdam.py` | Full golden path with real simulated connectors and seeded data |

---

## 3. Failure matrix

| Required failure | Test |
| --- | --- |
| Gemini API unavailable | `test_gemini_service.py`; `test_orchestration.py::test_agent_failure_from_a_missing_key_is_not_retried` |
| Gemini daily quota exhausted | `test_gemini_quota_rotation.py` (no retry, rotate to next key, quarantine, all-cooling error) |
| External API timeout | `test_integrations.py::test_live_connector_retries_a_timeout_then_reports_it_clearly` |
| Invalid LLM output | `test_orchestration.py::test_invalid_agent_output_is_retried_once_then_fails`; per-agent malformed-output tests |
| Missing shipment data | `test_disruption_sensing.py` invented-reference handling; `test_inventory_rebalancing.py` unknown material/target |
| No alternative routes | `test_rerouting_logistics.py::rerouting_never_invents_a_route_when_no_service_matches` |
| Insufficient inventory | `test_inventory_rebalancing.py` no-transfer / committed-stock cases |
| Compliance violation | `test_compliance_audit.py::audit_rejects_a_mandatory_rule_failure_even_when_within_budget` |
| Manager rejects proposal | `test_orchestration.py::test_approval_gate_records_a_rejection`; `test_approvals.py::test_rejection_closes_the_workflow_without_execution` |
| Duplicate execution request | `test_approvals.py` idempotent/duplicate cases; live `409` in Step 9 |
| Overlapping workflow starts | `test_workflow_start.py` `409` while the slot is held; live second start refused with the active thread id |
| Database connection failure | `test_dashboard.py::test_unavailable_database_returns_503`; health degrades |

---

## 4. End-to-end golden path

`test_e2e_mumbai_rotterdam.py` exercises the real graph, the five agents, the
deterministic tools and the real simulated connectors with the seeded data. Only
Gemini is scripted. Assertions:

- one execution of each of the five agent prompts;
- risk score ≥ 60 and High severity;
- `SH001` and `SUP001` linked from the report;
- at least three ranked scenarios and a deterministic recommendation;
- screening passes and the inventory shortage is closed;
- the graph pauses for a Director-level approval;
- on approval: status `completed`, three `[SIMULATED]` actions including
  `INVENTORY_TRANSFER`;
- a replay raises `ApprovalConflictError` and adds no action.

---

## 5. Frontend

| Check | Result |
| --- | --- |
| `npm run build` | Pass (production bundle produced) |
| `npm run lint` | 0 errors, 2 pre-existing warnings (`useAsyncData` non-literal deps, `useHealthCheck` set-state-in-effect) |
| Browser walkthrough | Overview, Disruption Monitoring, Agent Activity, Scenario Comparison, Approval Center, Shipments, Inventory, Audit History verified against a live backend in Steps 8–9 |

---

## 6. Container verification (Step 10)

| Check | Command | Result |
| --- | --- | --- |
| Compose model | `docker compose config --quiet` | Valid |
| Image builds | `docker compose build` | See §6.1 |
| Stack health | `docker compose ps` | See §6.1 |
| API health | `GET :8000/api/health` | See §6.1 |
| Frontend proxy | `GET :8080/api/health` | See §6.1 |
| Seed job | `docker compose logs seed` | See §6.1 |
| Persistence | restart backend, read the paused thread | See §6.1 |
| Stop/start | `docker compose stop` → `start` | See §6.1 |

### 6.1 Verified results — 2026-11-24

| Check | Evidence |
| --- | --- |
| Images | `xfactor-backend` 407 MB, `xfactor-seed` 407 MB (same image), `xfactor-frontend` 74.4 MB |
| Stack health | `db` healthy (`pg_isready`), `seed` exited 0, `backend` healthy, `frontend` healthy |
| Seed job | `Seeded: 5 suppliers, 10 shipments`; dashboard reports 10 shipments, 5 suppliers |
| API health | `GET :8000/api/health` → `{"status":"ok","database":"connected"}` |
| Frontend proxy | `/healthz` 200, `/api/health` 200 and `/` 200 through `:8080` |
| Checkpoint tables | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` present; 40 checkpoint rows after runs |
| Persistence across restart | `docker compose restart backend` → `GET /api/orchestration/workflows/EV-DEMO-RED-SEA-5/state` still returned the saved failed state (2 errors) |
| Startup order | `docker compose start` waited for `db` healthy before `backend`, then `frontend` after backend healthy |
| Graceful shutdown | uvicorn logs `Waiting for application shutdown` → `Application shutdown complete` on stop |
| Approval auth (container) | `GET /api/approvals/pending` → 401 without token, 503 with an unknown token because `APPROVER_CREDENTIALS` is unset (fail-closed) |
| Live demo | **Blocked by upstream quota**: four attempts (`EV-DEMO-RED-SEA`…`-5`) failed honestly at Disruption Sensing with Gemini HTTP 503 then HTTP 429 (20/day free tier). Recorded in the Compose database as `failed`; no execution occurred |

The paused-thread resume path through the container could not be replayed live
while the quota was exhausted; it is covered by the graph/API tests and by the
Step 9 live run on the Aiven database.

---

## 7. Known gaps

- Live Gemini is quota-limited (20 requests/day/model); the offline E2E test is
  the authoritative golden-path proof when the quota is exhausted.
- Live SAP and external data providers are not configured; simulated adapters
  are labelled and their live counterparts are unit-tested with transport
  doubles.
- The frontend approval flow requires pasting a bearer token; there is no login
  layer.
- The four failed verification runs from Steps 8–9 remain in the shared Aiven
  database by design until an explicit cleanup is approved.
