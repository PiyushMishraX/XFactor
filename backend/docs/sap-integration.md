# X FACTOR SAP Integration (Step 7)

Step 7 adds the enterprise-system boundary: SAP reads feed the agents, and SAP
writes are possible only after a recorded human approval. The read connector from
Step 2 stays **read-only**; write capability lives in a separate module with a
separate permission and mandatory approval evidence.

```
SAP enterprise system
        │  (OData / REST, OAuth2 or API key)
        ▼
SAP connector (read)  ──►  agents / LangGraph supervisor
        │
        ▼
Proposal ──► human approval (Step 6) ──► SAP write connector (Step 7)
                                          │  validation + idempotency
                                          ▼
                                   SAP operational update
```

## 1. Real versus simulated

No live SAP tenant has been contacted in this project. `SAP_USE_MOCK=true` is the
default, so:

* every read record carries `provenance.is_mock=True` and renders with a
  `[SIMULATED]` label;
* every write result has `status="simulated"`, `is_mock=True` and a
  `[SIMULATED] …` message;
* no claim of successful live SAP integration is made anywhere in the code or UI.

The live adapters are implemented and unit-tested against `httpx.MockTransport`.
They are selected only when `SAP_USE_MOCK=false` and credentials are configured.

## 2. Prepared connector profiles

`app/integrations/sap_profiles.py` prepares one profile per SAP API family. The
profile supplies the relative read/write paths; selecting it is configuration
only.

| `SAP_API_FAMILY` | Transport | Notes |
| --- | --- | --- |
| `s4hana` (default) | OData V2 | S/4HANA OData services activated in the tenant |
| `business_accelerator_hub` | REST | Published SAP APIs behind a gateway |
| `btp` | REST | BTP service instance / destination brokering S/4HANA |
| `integration_suite` | REST | Integration Suite / CPI mediated routes |

**Honesty:** the relative paths are prepared gateway defaults, not verified
tenant endpoints. They must be confirmed against the tenant's service catalogue
before live use. `supports_write` describes what the connector can do, not an
entitlement the tenant has granted.

## 3. Environment-based authentication

| Variable | Purpose |
| --- | --- |
| `SAP_AUTH_URL` | OAuth2 token endpoint (client credentials) |
| `SAP_CLIENT_ID` / `SAP_CLIENT_SECRET` | OAuth client, or gateway credentials |
| `SAP_READ_SCOPE` | Scope requested by the read connector (default `sap.read`) |
| `SAP_WRITE_SCOPE` | Scope requested by the write connector (default `sap.write`) |
| `SAP_BASE_URL` | Gateway / tenant base URL |
| `SAP_API_FAMILY` | Profile selection |
| `SAP_WRITE_ENABLED` | Separate write permission (default `false`) |
| `SAP_USE_MOCK` | Simulated adapters (default `true`) |

When `SAP_AUTH_URL` is set, `SAPOAuthTokenProvider` requests a token with
`grant_type=client_credentials`, the configured client id/secret and the scope for
that code path. Tokens are cached in memory until shortly before expiry; the read
and write connectors request **different scopes**, so a read token is never
write-capable. Without a token endpoint the connector falls back to the Step 2
gateway `x-api-key` convention.

Tokens and secrets are never logged. `redact_headers()` masks
`Authorization`, `x-api-key` and cookie headers, and a token-endpoint rejection
reports only the status code (the body is never echoed, because it can contain the
client secret).

## 4. Read interface

`app/integrations/sap.py` exposes read-only methods only:

| Method | Capability |
| --- | --- |
| `list_shipments()` / `get_shipment(shipment_id=…)` | Shipment information |
| `list_purchase_orders(supplier_id=…)` | Purchase orders |
| `list_suppliers()` / `get_supplier(supplier_id=…)` | Supplier records |
| `list_inventory()` / `get_inventory_item(material_id=…)` | Inventory levels |
| `list_materials()` / `get_material(material_id=…)` | Material information |
| `list_shipments()` etc. on the live adapter | Same data through the profile paths |

`SimulatedSAPConnector` returns five suppliers, ten shipments, five material
master records, eight inventory positions and four purchase orders. Shipments and
suppliers mirror the seeded PostgreSQL reference data, so the connector and the
database describe the same records.

The connector deliberately has **no** write methods; a regression test asserts
that `apply_*`, `write` and `execute` do not exist on it.

## 5. Authorized write interface

`app/integrations/sap_write.py` is the only path that can change SAP. It defines
three validated request types and three corresponding methods:

| Request | Method | Validation |
| --- | --- | --- |
| `SAPShipmentPlanUpdate` | `apply_shipment_plan(...)` | non-empty request/shipment ids; cost ≥ 0; days ≥ 0 |
| `SAPInventoryTransferRequest` | `request_inventory_transfer(...)` | non-empty ids; `units > 0`; source ≠ target plant; cost ≥ 0 |
| `SAPOperationalChange` | `record_operational_change(...)` | non-empty request id, change type and description; cost ≥ 0 |

Every method takes a keyword-only `approval: SAPApprovalEvidence`. Omitting it is
a `TypeError`; passing `None` raises `SAPWriteNotAuthorizedError`. Evidence can
only be built from an approved decision:

```python
from app.integrations.sap_write import approval_evidence_from_decision, get_sap_write_connector

evidence = approval_evidence_from_decision(decision_record, thread_id=thread_id)
writer = get_sap_write_connector(settings)
result = writer.apply_shipment_plan(request, approval=evidence)
```

`approval_evidence_from_decision` refuses a `reject` or `request_modifications`
decision. The evidence carries the approver id and role, the workflow thread, the
exact `proposal_version` that was reviewed, and the decision timestamp, so an
approval of an older proposal cannot authorise a newer one.

### Idempotency

Each request is keyed
`sap:{thread_id}:{proposal_version}:{request_type}:{request_id}`. The live adapter
sends it as both the `Idempotency-Key` header and a body field. A retried call
with the same key cannot apply the same change twice; the simulated adapter
derives a deterministic `SIM-SAP-…` reference from the same key.

### Results

| `SAPWriteStatus` | Meaning |
| --- | --- |
| `accepted` | The live SAP API accepted the write |
| `simulated` | The mock adapter accepted it; no SAP system changed |
| `rejected` | SAP refused it (400 / 409 / 422) |
| `failed` | Transport failure, authentication failure or 5xx after retries |

Every result carries a `Provenance` record, the idempotency key and a reference
when one was returned.

## 6. Separate read and write permissions

Reading and writing are independently controlled:

* reads follow `SAP_USE_MOCK` and the read credentials/scope;
* writes additionally require `SAP_WRITE_ENABLED=true` — the default is `false`;
* the write connector requests `SAP_WRITE_SCOPE`, never the read scope;
* configuring read credentials does **not** enable writes, and the test suite
  asserts that (`test_read_access_does_not_imply_write_access`).

Enabling writes while mock mode is on returns the simulated writer; enabling them
against a live system requires `SAP_BASE_URL`, client credentials and a profile
that supports writes.

## 7. Rate limits and failures

The shared `HttpJsonClient` retries `429 / 500 / 502 / 503 / 504` and transport
errors up to `INTEGRATION_MAX_ATTEMPTS`. It now honours a numeric `Retry-After`
header (clamped to 30 seconds); when no header is present it uses the normal
linear back-off. Non-retryable 4xx responses raise `IntegrationRequestError`
carrying `status_code`, which the write connector uses to distinguish a SAP
rejection from a failure.

Token requests use the same retry policy and fail loudly rather than degrading
into simulated data.

## 8. What is logged

* Read/write path and capability, request id, outcome and external reference.
* Token acquisition logs only the scope and lifetime.
* Failure logs contain the HTTP status and a truncated message.

Never logged: `SAP_CLIENT_SECRET`, token values, `Authorization` or `x-api-key`
headers. `redact_headers()` is available for any future diagnostic logging.

## 9. Tests

`backend/tests/test_sap_integration.py` — 37 tests:

* all four profiles exist, are selected by `SAP_API_FAMILY`, and declare every
  read/write capability;
* OAuth token request shape, caching, bearer header, no `x-api-key`, failure
  classification, and no secret/token in logs or error messages;
* simulated material master and profile-aware live read paths (including 404 →
  `None`);
* request validation rejects missing ids, non-positive transfers and identical
  plants;
* only an `approve` decision produces evidence, and evidence requires a thread;
* every write method requires keyword approval evidence;
* simulated writes are labelled, deterministic and cover all three operations;
* write access is disabled by default, requires a separate permission, and read
  credentials do not imply it;
* live writes send the validated body, bearer token and idempotency key, and
  classify 400 as `rejected` and 503 as `failed`;
* `Retry-After` is honoured;
* an approved decision can be written to the mock SAP system while a rejection
  cannot be turned into evidence.

Full backend suite after Step 7: **352 passed, 6 skipped** (the skips are the
opt-in `RUN_LIVE_GEMINI=1` / live-database tests).

## 10. Limitations

1. **No live SAP tenant is connected.** The mock adapter is the honest default;
   the live adapters are tested only through `httpx.MockTransport`.
2. **Profile paths are prepared defaults.** Confirm them against the tenant's
   activated services and API catalogue before enabling live access.
3. **Writes are not yet invoked from the approval API.** Step 6 executes the
   approved proposal through the generic execution gateway (simulated by
   default). Step 7 supplies the SAP write interface and the approval-evidence
   bridge; wiring shipment-level context from the workflow into SAP write
   requests is deferred to the Step 8/9 dashboard and end-to-end work so the
   platform never guesses shipment or plant identifiers.
4. **Tenant entitlements are unknown.** `supports_write` describes the connector,
   not a verified SAP authorisation.
