# X FACTOR Human-in-the-Loop and Authorized Execution (Step 6)

Step 4 paused the supervisor at an approval gate; Step 5 recorded the
collaboration that produced the proposal. Step 6 turns that pause into a
**controlled, authenticated decision and an idempotent execution**:

* the exact proposal a reviewer sees is snapshotted and versioned;
* only a bearer-authenticated approver with a sufficient role may decide;
* the decision is bound to that proposal version and recorded with identity and
  timestamp;
* a reviewer may approve, reject or request modifications, and modifications are
  bounded;
* only an approved, still-current proposal is executed, exactly once.

Nothing in this layer trusts a status supplied by the frontend. The request body
carries an action, a comment and a proposal version — never an approver identity
or an "approved" flag.

The mechanics live in these modules:

| Module | Responsibility |
| --- | --- |
| `app/schemas/approval_schemas.py` | `ProposalSnapshot` (+ deterministic version), `ApproverIdentity` / `ApproverRole`, `ApprovalDecisionRequest` / `Record` / `Outcome`, `ApprovalRequestView` |
| `app/schemas/execution_schemas.py` | `ExecutionAction`, `ExecutionReport`, action/run statuses |
| `app/models/approvals.py` | `ApprovalRequestRow` (`approval_requests`, one row per thread) |
| `app/services/approval_auth.py` | Constant-time token authentication and the role hierarchy |
| `app/services/approval_repository.py` | Queue persistence (`PostgresApprovalRepository`, `InMemoryApprovalRepository`) |
| `app/services/approval_service.py` | The ordered security model: authenticate → validate version → authorize → resume → record → execute |
| `app/services/execution.py` | Deterministic execution plan, simulated/live adapters, idempotent `ExecutionService` |
| `app/orchestration/approvals.py` | Proposal snapshot, resume payload, legacy parsing, bounded modification revisions |
| `app/api/approvals.py` | The authenticated approval API |
| `frontend/src/pages/ApprovalCenter.jsx` | The approval interface |

## 1. When approval is required

The Step 2 Approval Management Engine remains the single decision point. Its
default policy (`app/tools/approval.py`) requires a human when any of these fire:

| Rule | Default threshold | Level |
| --- | --- | --- |
| High-impact reroute | explicit flag, or shipment value ≥ 1,000,000 USD | Director |
| Major inventory redistribution | transfer ≥ 500 units | Manager |
| Spend above the approval threshold | cost > 250,000 USD | Manager |
| Sensitive supplier change | risk tier `High` or `Critical` | Manager |
| Compliance-mandated approval | rule-driven flag | Manager |

`approval_level` is **Director** when the cost reaches 500,000 USD
(`director_threshold_multiplier × budget_approval_threshold_usd`) or the reroute
is explicitly high-impact; otherwise it is **Manager** whenever approval is
required. A caller can supply a different `ApprovalPolicy` on the
`RecoveryRequest`; no threshold is decided by an LLM.

When the audit verdict requires approval, the supervisor routes to
`NODE_APPROVAL_GATE` and LangGraph raises an `interrupt`, which saves the
checkpoint and returns an `approval_required` payload.

## 2. Proposal snapshot and version

`build_proposal_snapshot(thread_id, state)` reads only deterministic state
(`audit_report`, `scenario_plan` or `rerouting`, and the request) and produces a
`ProposalSnapshot`: the recommendation, carrier/mode, cost, transit days,
shipment value, transfer units, supplier, approval level, reasons, violations and
the execution actions. It never calls an agent or an LLM.

`proposal_version` is the first 16 hex characters of a SHA-256 digest over the
snapshot's canonical JSON. Three fields are excluded because they identify or
timestamp the *review*, not the proposal: `thread_id`, `proposal_version` and
`created_at`. This is what lets the graph (which does not receive a thread id)
and the API agree on the same version for the same proposal.

Changing any operational fact changes the version. A decision that targets an
older version is rejected with `409`, both against the stored queue item and
against the workflow's *current* paused proposal.

## 3. Authentication and authorization

`APPROVER_CREDENTIALS` is a comma-separated list of
`token:approver_id:Role` entries, where `Role` is `Manager`, `Director` or
`Admin`. There is no default credential and no anonymous fallback.

* Tokens are compared with `secrets.compare_digest` against **every** entry, so a
  match position is not observable.
* `extract_bearer_token` requires `Authorization: Bearer <token>`.
* `ApproverIdentity.can_approve(level)` enforces the hierarchy: Manager → 1,
  Director → 2, Admin → 3. An unknown level is treated as the strictest.
* Malformed credentials fail closed; an empty `APPROVER_CREDENTIALS` makes every
  approval endpoint return `503` rather than letting callers through.

Only environment-variable names are documented. Never commit real tokens.

## 4. Persistence and decision history

`ApprovalRequestRow` holds one row per workflow thread: the current proposal JSON,
its version and level, its status, the full decision-history JSON and any
execution report.

`ApprovalRepository` semantics, identical for the Postgres and in-memory
implementations:

* a new proposal version starts a new `pending` review, keeps the decision
  history and clears the previous execution report;
* re-recording the same **already-decided** version refreshes the displayed
  snapshot but never reopens the item;
* a decision appends one immutable `ApprovalDecisionRecord`
  (`action`, `approver_id`, `approver_role`, `comment`, `proposal_version`,
  `decided_at`, `workflow_status`);
* an execution report is stored only for the version that was executed, so a
  version change automatically prevents an old report from being replayed.

`ensure_approval_schema` creates the table at startup with `checkfirst=True`; the
table is never created by importing the application.

## 5. Decisions and the bounded modification loop

`ApprovalService.decide` applies this order — the order *is* the security model:

1. authenticate the bearer token;
2. load the checkpoint and confirm the workflow is paused at
   `NODE_APPROVAL_GATE`;
3. build the workflow's current snapshot and record the queue item if missing;
4. reject the decision unless the thread is `pending`;
5. compare the submitted version with the stored version **and** the current
   workflow version;
6. authorize the approver's role against the proposal's level;
7. resume the graph with `build_resume_payload` (action, comment, version,
   authenticated identity, timestamp);
8. append the decision record;
9. on `approve` + `completed`, run the idempotent execution and save its report;
10. if the graph paused again on a revised proposal, record the new version as a
    fresh pending item with the history preserved.

`build_approval_gate` accepts this payload *and* the Step 4 legacy payloads
(`{"approved": true}`, a bare boolean or a word), which are attributed to
`"human"` so the Step 4 tests and behaviour are unchanged.

**Request modifications** sends the proposal back to the Scenario agent through
the existing `ScenarioRevision` mechanism. `build_modification_revision` excludes
the recommended scenario and carries the reviewer's comment as feedback;
`_decide` recognises the `"Human review requested modifications"` prefix and
records that reason in the decision log. The loop is capped by
`MAX_MODIFICATION_ROUNDS = 2`; one request beyond the cap closes the workflow with
`approval_rejected`, an explanatory error and the full decision history.

**Rejection** closes the workflow as `approval_rejected`, records the comment in
`errors`, and produces no execution.

## 6. Authorized execution

`build_execution_plan(proposal)` derives the operational actions from the approved
snapshot, in a stable order:

| Action | Added when |
| --- | --- |
| `shipment_plan_update` | always |
| `inventory_transfer` | `inventory_transfer_units > 0` |
| `carrier_change` | `carrier_change_requested` |
| `sap_execution` | a `supplier_id` is present |

Every action's idempotency key is
`"{thread_id}:{proposal_version}:{action_type}"`.

`ExecutionService.execute` refuses a proposal that did not require approval, has
no version or is not bound to a thread (`ExecutionNotAuthorizedError`). It checks
the store for an existing report for that thread and version and replays it with
`idempotent_replay=True` instead of executing again. A run reports `completed`,
`partial` or `failed`; an adapter exception is recorded as a failed action, never
swallowed.

Two adapters exist:

* `SimulatedExecutionAdapter` (default, `EXECUTION_USE_MOCK=true`) returns
  deterministic `SIM-…` references and a `[SIMULATED]` message, and changes no
  operational system.
* `HttpExecutionAdapter` posts each action to its gateway endpoint
  (`/shipments/plan`, `/inventory/transfers`, `/carriers/change`, `/sap/execute`)
  with the standard `Idempotency-Key` header and an `x-client-id`, and maps a
  gateway rejection to a failed action.

The factory raises `IntegrationNotConfiguredError` when mock mode is off but
`EXECUTION_BASE_URL`, `EXECUTION_CLIENT_ID` and `EXECUTION_CLIENT_SECRET` are not
all configured.

## 7. The secured approval API

All endpoints require `Authorization: Bearer <token>`.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/approvals/pending` | Proposals awaiting a decision |
| `GET /api/approvals/{thread_id}` | One proposal, its status and full decision history |
| `POST /api/approvals/{thread_id}/decision` | `{action, comment, proposal_version}` |
| `GET /api/approvals/{thread_id}/execution` | The execution report, when one exists |

The decision body never carries an approver identity or an approval status. Error
mapping:

| Status | Meaning |
| --- | --- |
| `401` | Missing, malformed or unknown bearer token (`WWW-Authenticate: Bearer`) |
| `403` | Authenticated but the role is below the proposal's approval level |
| `404` | No approval item or execution report exists |
| `409` | Not paused, already decided, or a stale proposal version |
| `503` | `APPROVER_CREDENTIALS` or the execution gateway is not configured |

The unauthenticated Step 4 `POST …/resume` endpoint was **removed**; all decisions
go through the authenticated approval API.

## 8. Frontend approval interface

`frontend/src/pages/ApprovalCenter.jsx` is reachable from the app's tab bar. An
approver pastes a bearer token (kept in `sessionStorage` only), sees the pending
queue, the proposal headline/summary/version/reasons/violations and the full
decision history, and can approve, reject or request modifications. A comment is
required for reject and modifications. The resulting execution report is rendered
with its `[SIMULATED]` marker, and the token is never placed in source code.

## 9. Tests

`backend/tests/test_approvals.py` — 50 tests covering:

* proposal version stability, exclusions and change detection, and agreement
  between the graph and the API;
* credential parsing, constant-time authentication, role hierarchy and
  bearer-header parsing;
* legacy and Step 6 decision payloads;
* authenticated approval, rejection and identity/timestamp/history recording;
* the revision loop and its `MAX_MODIFICATION_ROUNDS` bound;
* execution plan ordering and idempotency keys, simulated labelling, replay,
  refusal without approval, partial/failed reports, the live adapter through
  `httpx.MockTransport` (`POST`, `Idempotency-Key`, `x-client-id`, rejection) and
  the adapter factory;
* repository history/version behaviour in memory and through SQLite;
* the API's 401 / 403 / 409 / 503 responses, approval → execution → duplicate
  prevention, stale versions, rejection and the modification round-trip.

Full backend suite after Step 6: **315 passed, 6 skipped** (the skips are the
opt-in `RUN_LIVE_GEMINI=1` tests).
