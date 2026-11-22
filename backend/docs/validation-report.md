# X FACTOR — Step 9 Validation Report

**Date:** 2026-11-22
**Scope:** full technical audit from disruption ingestion to authorized execution, plus the required failure matrix.
**Environment:** local FastAPI (`127.0.0.1:8000`) + Vite (`localhost:5173`), live Aiven PostgreSQL, PostgreSQL LangGraph checkpointer, Gemini `gemini-3.5-flash` (resolves to `gemini-3.6-flash`).

> Honesty note: the LLM is a free-tier external dependency with a hard daily cap.
> The Mumbai → Rotterdam walkthrough was executed live twice; both runs stopped at
> the Gemini call with HTTP 429 (quota), never because of platform logic. The
> deterministic end-to-end test below drives the real graph, real simulated
> connectors and the seeded demo data, with only the LLM scripted.

## 1. Test scenario

Maritime security event in the Bab-el-Mandeb → shipment **SH001** (Pharmaceutical
API, Mumbai → Rotterdam, Maersk, USD 1,250,000, supplier **SUP001**) → reroute
and/or inventory cover at **Rotterdam DC** for **MAT-PHARMA-001**.

## 2. Roadmap verification

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Disruption ingestion | Pass | `POST /api/orchestration/workflows` accepted the report; `DisruptionReport` schema; run recorded (`workflow_runs`). |
| 2 | Disruption Sensing Agent | Pass (tests + live path) | Live EV-UI-VERIFY-003 sensing completed in 8.0 s; tests `test_disruption_sensing.py` (all 8 categories, reference validation). |
| 3 | Risk scoring | Pass | Deterministic `risk_scoring.compute_risk_score`; model only selects observed factors. Live valid run: risk 58 / Moderate (Shanghai payload); Mumbai test: ≥60 / High. |
| 4 | Supervisor delegation | Pass | Decision log records every delegation with a reason; live run delegated sensing → scenario → compliance. |
| 5 | Scenario Planning Agent | Pass | ≥3 ranked alternatives, deterministic scorecard; live run produced SC3 and 12 recorded tool calls. |
| 6 | Rerouting & Logistics Agent | Pass | Composed inside Scenario Planning (live: 12 tool calls); direct-path tests in `test_rerouting_logistics.py`. |
| 7 | Inventory Rebalancing Agent | Pass | Shortage/safety-stock/surplus engines; Rotterdam DC is short, Mumbai/Hamburg surplus covers it (new E2E test). |
| 8 | Compliance & Audit Agent | Pass | Deterministic verdict, no model override; live verdict “Approved subject to human approval” across 4 rules. |
| 9 | Agent collaboration | Pass | Screening, bounded replanning and history in `test_collaboration.py` and orchestration tests. |
| 10 | Autonomous replanning | Pass | `MAX_REPLAN_ROUNDS = 2`, revision payloads driven by deterministic evaluation; covered by tests. |
| 11 | Human approval | Pass (live) | EV-UI-VERIFY-003 approved at Director level with an authenticated credential; 401/403/409 paths exercised live. |
| 12 | Workflow checkpointing | Pass (live) | The proposal was created at 17:05, survived several backend restarts, and was approved at 17:28; `checkpoint_*` tables present in PostgreSQL. |
| 13 | Authorized execution | Pass (live) | Three simulated actions executed once, labelled `[SIMULATED]`; duplicate decision returned 409; DB holds exactly one decision and three actions. |
| 14 | SAP connector | Pass | Live `/api/dashboard/inventory`: 8 positions, `is_mock=true`, simulated provenance; write interface requires approval evidence; no write methods on the read connector. |
| 15 | Database persistence | Pass | Direct SQL: `approval_requests.status=approved`, 1 decision, 3 executed actions; `workflow_runs` row `completed`, `execution_count=3`, `error_count=0`. |
| 16 | Audit history | Pass | `/api/dashboard/runs/EV-UI-VERIFY-003` and the Audit History page show verdict, rule findings, agent durations/tool counts and the approver record. |
| 17 | Frontend updates | Pass | Browser verification: Overview (5 runs / 10 shipments / 12 executions), Inventory (8 positions incl. Rotterdam 3,000 vs 6,000 safety), Approval Center (0 pending), Audit History (approval + execution). |

## 3. Live run journal

| Thread | Outcome | Detail |
|--------|---------|--------|
| `EV-STEP9-MUMBAI-001` | Failed at Scenario Planning | `InventoryRebalancingError: Target plant 'Rotterdam DC' does not hold material 'MAT-PHARMA-001'` — demo dataset lacked a Rotterdam pharma position; retry then hit HTTP 429. |
| `EV-STEP9-MUMBAI-002` | Failed at Sensing | HTTP 429 `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20/day for `gemini-3.6-flash`, retry after ≈14 h 32 m. Two attempts recorded, fail-closed, no execution. |
| `EV-UI-VERIFY-003` | Completed + executed | Director approval applied live; 3 simulated actions (`shipment_plan_update`, `carrier_change`, `sap_execution`); duplicate refused. |

## 4. Failure-test matrix

| Required failure | Coverage |
|------------------|----------|
| Gemini API unavailable | Live HTTP 429 handled with one retry, honest failed run and dashboard error; `test_gemini_service.py` (transient retry, persistent failure, network error), `test_orchestration.py::test_agent_failure_from_a_missing_key_is_not_retried`. |
| External API timeout | **Added** `test_integrations.py::test_live_connector_retries_a_timeout_then_reports_it_clearly` — timeout retried `DEFAULT_MAX_ATTEMPTS` times, then `IntegrationRequestError`. |
| Invalid LLM output | Per-agent `malformed_model_output_raises_a_clear_error`; `test_orchestration.py::test_invalid_agent_output_is_retried_once_then_fails`. |
| Missing shipment data | `test_disruption_sensing.py` invented references flagged/excluded, all-unknown contradiction; `test_inventory_rebalancing.py` unknown material/target errors. |
| No alternative routes | `test_rerouting_logistics.py::rerouting_never_invents_a_route_when_no_service_matches`; `test_orchestration.py::test_no_feasible_recovery_short_circuits_before_the_audit`. |
| Insufficient inventory | `test_inventory_rebalancing.py` no-transfer case, committed stock excluded, single-plant material. |
| Compliance violation | `test_compliance_audit.py::audit_rejects_a_mandatory_rule_failure_even_when_within_budget`, `model_cannot_override_a_rejection`. |
| Manager rejects proposal | `test_orchestration.py::test_approval_gate_records_a_rejection`; `test_approvals.py::test_rejection_closes_the_workflow_without_execution`. Not replayed live because the daily quota blocks a new paused run. |
| Duplicate execution request | Live: repeated decision → HTTP 409, execution report unchanged. Tests: `test_simulated_execution_is_labelled_and_replayed_idempotently`, `test_approval_decision_resumes_executes_and_prevents_duplicates`. |
| Database connection failure | **Added** `test_dashboard.py::test_unavailable_database_returns_503`; health endpoint degrades to `database: unavailable`. |

## 5. Defects found and fixed

1. **Inventory transfer dropped in the scenario path (critical).**
   Scenario Planning composes Agent 4 internally and the supervisor's separate
   rebalancing node never runs, but the audit request, screening and approval
   proposal read transfer units only from `state["rebalancing"]`. Any inventory
   transfer recommended by the scenario analysis was therefore invisible to the
   audit/approval proposal and to the execution plan.
   Fix: `ScenarioPlan.inventory_transfer_units` is populated by the agent and is
   used as a fallback in `_audit_request`, `_screening_update` and
   `build_proposal_snapshot`. The E2E test now asserts an `inventory_transfer`
   execution action.
2. **Demo dataset could not support the walkthrough.** No `MAT-PHARMA-001`
   position existed at `Rotterdam DC`. Added the missing position (3,000 on hand
   against 6,000 safety stock); docs updated from seven to eight positions.
3. **Coverage gaps.** Added the external-timeout test and the database-failure
   dashboard test, both promised by earlier docstrings but not implemented.

## 6. Security and operational checks

- **Approval authentication (live):** no token → 401; unknown token → 401;
  Manager on a Director proposal → 403; stale proposal version → 409; duplicate
  decision → 409. Only the authenticated Director credential succeeded.
- **Identity binding:** the decision records `approver_id`, role, proposal
  version (0a2f4e993d7eb75e) and timestamp; the version is recomputed from the
  proposal, never supplied by the client beyond the “seen version” check.
- **Execution safety:** execution runs only after an approve decision; evidence
  is mandatory for SAP writes; the second identical request executed nothing.
- **Secret hygiene:** no `AIza…`/`AVNS_…` literals in `frontend/src`,
  `frontend/dist` or backend logs; `.env` is git-ignored; only variable names are
  documented. The ephemeral test approver credential was passed to the local
  process environment only and is not written to any file.
- **Logging and exceptions:** Gemini, integration and adapter failures are
  recorded in workflow state and appear in `/api/dashboard/runs`; database
  failures map to 503; cancelled/partial execution is reported honestly.

## 7. Test results

| Suite | Result |
|-------|--------|
| Backend (`pytest tests`, run from `backend/`) | **368 passed, 6 skipped** (skip = opt-in live Gemini tests) |
| New Step 9 tests | `test_e2e_mumbai_rotterdam.py` (2), external timeout (1), dashboard DB failure (1) |
| Frontend build | Passed (`vite build`) |
| Frontend lint | 0 errors, 2 warnings (pre-existing) |
| Live API | health `ok`, DB connected; dashboard endpoints 200; approvals 401 without token |

## 8. Known limitations

- **Gemini free tier:** 20 generate-content requests per day per project; the
  daily budget was exhausted during validation. A full live workflow needs 5
  calls, so the live Mumbai replay is blocked until the quota resets
  (≈14 h 32 m from 17:27 UTC) or billing is enabled.
- **Live rejection** was not replayed after the quota block; it is covered by
  graph and API tests, including “no execution after rejection”.
- **Approver credential** is still not persisted. Approvals run only when
  `APPROVER_CREDENTIALS` is supplied to the backend process; otherwise the API
  fails closed with 503. The credential used here was a temporary local test
  token.
- **Simulated data:** shipments/suppliers come from PostgreSQL demo seed data
  and SAP reads from the simulated connector; both are labelled `[SIMULATED]`.
  The platform does not claim live SAP connectivity.
- **Frontend approval flow** requires the approver to paste the bearer token;
  there is no login/session layer yet.

## 9. Deployment readiness

Step 9 is complete; the system is demonstrable end to end with the documented
quota caveat. Step 10 (Dockerfiles, Compose, deployment configuration, demo
script) has not started, so the platform is not yet packaged for deployment.
