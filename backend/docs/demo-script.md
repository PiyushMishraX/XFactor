# X FACTOR — Hackathon Demo Script

**Scenario:** a maritime security event closes the Bab-el-Mandeb / Red Sea route
used by shipment **SH001** (Pharmaceutical API, Mumbai → Rotterdam, Maersk,
USD 1.25 M, four containers). The platform must detect it, coordinate five
agents, compare recovery scenarios, rebalance Rotterdam DC inventory, obtain a
human decision and execute only what was approved.

Everything shown is produced by the running system. No agent activity, timing,
number or execution result in this script is hand-written or back-filled.

---

## 1. Sample data (all labelled demo data)

| Item | Value | Source |
| --- | --- | --- |
| Shipment | `SH001` Mumbai → Rotterdam via Suez / Red Sea / Bab-el-Mandeb, Sea, Maersk, In Transit | Seeded `shipments` table |
| Supplier | `SUP001` Aurora Pharma Ingredients, India, Medium risk | Seeded `suppliers` table |
| Cargo | Pharmaceutical API, USD 1,250,000, 4 containers | Demo scenario payload |
| Inventory | `MAT-PHARMA-001` Paracetamol API | Simulated SAP connector |
| Rotterdam DC | 3,000 on hand / 6,000 safety / 7,000 reorder | Simulated SAP connector |
| Mumbai DC | 42,000 on hand / 12,000 safety / 20,000 reorder | Simulated SAP connector |
| External data | weather, news, maritime alerts, congestion, tariffs, carriers, mapping | Simulated adapters, `is_mock=true` |

The inventory is always labelled `[SIMULATED]` in the UI and API. No SAP tenant
or external data provider is contacted.

---

## 2. Prepare

```powershell
cd "D:\X Factor"

# Compose stack (PostgreSQL + seed + backend + frontend).
docker compose up --build -d

# Secrets used by the demo.
# backend/.env must contain:
#   GEMINI_API_KEY=...
#   APPROVER_CREDENTIALS=<token>:demo-director:Director
# The approval API returns 503 until APPROVER_CREDENTIALS is set.
```

Check readiness:

```powershell
curl http://localhost:8000/api/health        # status ok, database connected
curl http://localhost:8080/healthz           # ok
```

**Gemini quota:** a full run makes about five LLM calls. The free tier allows
20 requests/day per model, so budget the key or use a quota-backed one for the
live demo. If the quota is exhausted the run fails honestly with a recorded
`429`; it is not presented as a success.

---

## 3. Act 1 — detection to approval

Run the scenario from a terminal (or use the UI):

```powershell
cd backend
..\.venv\Scripts\python.exe -m scripts.run_demo_scenario
```

Or in the container:

```powershell
docker compose exec backend python -m scripts.run_demo_scenario --base-url http://127.0.0.1:8000/api
```

The helper prints only recorded facts:

1. **Disruption ingestion** — the report is accepted for the demo thread.
2. **Supervisor decisions** — each `step`, chosen node and structured reason.
3. **Agent executions** — Disruption Sensing, Scenario Planning (which composes
   Rerouting & Logistics and Inventory Rebalancing) and Compliance & Audit, with
   their tool-call counts.
4. **Scenarios** — each alternative's carrier/mode, transit days, cost and risk
   score, plus the deterministic recommendation.
5. **Screening** — scenario count, evaluations and whether all were rejected.
6. **Inventory cover** — units transferred, shortage after the transfer and the
   target plant.
7. **Approval request** — proposal version, approval level and the deterministic
   reasons.
8. The workflow is **paused** at the human gate; no execution has happened.

UI walkthrough at `http://localhost:8080`:

| Page | Show |
| --- | --- |
| Overview | KPI counts, status chart, latest runs |
| Disruption Monitoring | The assessed disruption, risk and supervisor decision |
| Agent Activity | Decision trail, five agent cards, tool invocations, handoffs, React Flow graph, timeline |
| Scenario Comparison | Routes, days, cost, risk, inventory impact, feasibility, compliance, recommendation |
| Inventory Management | `[SIMULATED]` positions including Rotterdam DC |

---

## 4. Act 2 — compliance rejection and autonomous replanning

Run the variant with a deliberate three-day lead-time ceiling:

```powershell
cd backend
..\.venv\Scripts\python.exe -m scripts.run_demo_scenario `
  --scenario demo/mumbai_rotterdam_replan_scenario.json
```

The deterministic screening rejects the slower Sea alternatives for
`POL-DEMO-MAX-LEAD-TIME`, the supervisor requests exactly one revision, the
rejected plan is preserved in `scenario_history`, and the revised plan contains
the compliant alternative. In **Agent Activity**, show the replanning record, the
two Scenario Planning attempts and the preserved history. This is the
"compliance rejection and replanning" requirement — it is real recorded state,
not a mock animation.

---

## 5. Act 3 — human approval and authorised execution

Approve through the UI (Approval Center: paste the token, review the proposal,
approve) or:

```powershell
cd backend
..\.venv\Scripts\python.exe -m scripts.run_demo_scenario `
  --action approve --token "<demo-director-token>"
```

The helper prints the decision (action, approver id and role, workflow status)
and the execution report. Each action carries `[SIMULATED]` because
`EXECUTION_USE_MOCK=true`; no operational system is changed. Expected action
types are the shipment plan update, the inventory transfer and the SAP execution
record.

Demonstrate the guard rails:

- Approving again with the same token returns `409`; the action count does not
  change.
- Rejecting a fresh thread returns no execution report.
- A Manager token on a high-impact reroute returns `403`.
- Omitting the token returns `401`.

---

## 6. Act 4 — persistence and audit

1. `docker compose restart backend` (or `down` / `up`).
2. Reload the dashboard: the run, its decision and its execution report are
   still there — they are read from PostgreSQL, not process memory.
3. Open Audit History: approval identity, timestamp, proposal version and the
   execution actions are recorded.
4. Approve a workflow that paused *before* the restart: it resumes from the
   LangGraph checkpoint.

---

## 7. Requirement → demonstration map

| Roadmap requirement | Where it is visible |
| --- | --- |
| Disruption detection | Disruption Monitoring; Sensing agent result |
| Supervisor reasoning and delegation | Agent Activity decision trail |
| All five agents executing | Agent Activity agent cards + executions |
| External tool usage | Tool invocations with provenance (`is_mock`) |
| Deterministic calculations | Scenario costs/days/risk, inventory numbers, audit verdict |
| Agent collaboration | Handoffs, task records, composed Scenario Planning |
| Scenario comparison | Scenario Comparison page |
| Compliance rejection and replanning | Replan variant: `all_rejected` round, revision, history |
| Human approval | Approval Center; `409`/`403`/`401` guards |
| Authorised execution | Execution report, `[SIMULATED]` actions |
| Audit record creation | Audit History; `workflow_runs` and `approval_requests` |

---

## 8. Known demo limitations

- No live SAP tenant or external data provider is configured; those adapters are
  simulated and labelled.
- Execution is simulated (`EXECUTION_USE_MOCK=true`); no real booking occurs.
- The Gemini free-tier quota can interrupt a live run; use a quota-backed key or
  run the deterministic E2E test (`pytest tests/test_e2e_mumbai_rotterdam.py`)
  as the offline proof of the same flow.
- The approver token is supplied at runtime; it is never stored in the bundle.
