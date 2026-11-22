"""Step 7 — SAP integration tests.

Covers the four prepared API profiles, OAuth client-credentials authentication
(caching and redaction), the read connector's new material master, write-request
validation, mandatory approval evidence, the simulated and live write adapters,
the separate read/write permission, and the retry-after handling shared with the
Step 2 transport.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.integrations.base import (
    HttpJsonClient,
    IntegrationNotConfiguredError,
    IntegrationRequestError,
)
from app.integrations.sap import (
    HttpSAPConnector,
    SAPMaterial,
    SimulatedSAPConnector,
    get_sap_connector,
)
from app.integrations.sap_auth import (
    SAPHttpClient,
    SAPOAuthTokenProvider,
    redact_headers,
)
from app.integrations.sap_profiles import (
    READ_CAPABILITIES,
    SAP_API_PROFILES,
    WRITE_CAPABILITIES,
    SAPApiFamily,
    get_sap_profile,
    resolve_sap_profile,
)
from app.integrations.sap_write import (
    HttpSAPWriteConnector,
    SAPApprovalEvidence,
    SAPInventoryTransferRequest,
    SAPOperationalChange,
    SAPShipmentPlanUpdate,
    SAPWriteNotAuthorizedError,
    SAPWritePermissionError,
    SAPWriteStatus,
    SimulatedSAPWriteConnector,
    approval_evidence_from_decision,
    get_sap_write_connector,
    sap_idempotency_key,
)
from app.schemas.approval_schemas import ApprovalAction, ApprovalDecisionRecord

_DECIDED_AT = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)


def _blank(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def _client(handler, *, base_url: str = "https://sap.test", **kwargs: object) -> HttpJsonClient:
    return HttpJsonClient(
        connector_name="sap",
        base_url=base_url,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def _decision(
    action: ApprovalAction = ApprovalAction.APPROVE, **overrides: object
) -> ApprovalDecisionRecord:
    data: dict = {
        "action": action,
        "approver_id": "mgr-1",
        "approver_role": "Manager",
        "proposal_version": "abc123def456",
        "decided_at": _DECIDED_AT,
        "comment": "Approved for execution.",
    }
    data.update(overrides)
    return ApprovalDecisionRecord(**data)


def _evidence(**overrides: object) -> SAPApprovalEvidence:
    return approval_evidence_from_decision(
        _decision(**overrides), thread_id="thread-1"
    )


def _shipment_request() -> SAPShipmentPlanUpdate:
    return SAPShipmentPlanUpdate(
        request_id="req-1",
        shipment_id="SH001",
        origin="Mumbai",
        destination="Rotterdam",
        carrier="Maersk",
        transport_mode="Sea",
        planned_cost_usd=120000.0,
        planned_days=21.0,
    )


# ---------------------------------------------------------------------------
# Prepared profiles
# ---------------------------------------------------------------------------


def test_prepared_profiles_cover_the_four_sap_api_families() -> None:
    assert set(SAP_API_PROFILES) == {family.value for family in SAPApiFamily}
    for profile in SAP_API_PROFILES.values():
        assert set(READ_CAPABILITIES) <= set(profile.read_paths)
        assert set(WRITE_CAPABILITIES) <= set(profile.write_paths)
        assert profile.supports_write is True


def test_profile_selection_is_environment_driven() -> None:
    assert resolve_sap_profile(_blank()).family is SAPApiFamily.S4HANA
    assert (
        resolve_sap_profile(_blank(SAP_API_FAMILY="btp")).family is SAPApiFamily.BTP
    )
    with pytest.raises(IntegrationNotConfiguredError, match="Unknown SAP API family"):
        resolve_sap_profile(_blank(SAP_API_FAMILY="crm"))


def test_profile_raises_for_an_undeclared_capability() -> None:
    profile = get_sap_profile("s4hana")
    with pytest.raises(IntegrationNotConfiguredError, match="read path"):
        profile.read_path("payroll")
    with pytest.raises(IntegrationNotConfiguredError, match="write path"):
        profile.write_path("payroll")


# ---------------------------------------------------------------------------
# OAuth and request hygiene
# ---------------------------------------------------------------------------


def test_token_provider_requests_client_credentials_scope_and_caches() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})

    provider = SAPOAuthTokenProvider(
        token_url="https://auth.test/token",
        client_id="client-1",
        client_secret="s3cr3t",
        scope="sap.read",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.access_token() == "tok-1"
    assert provider.access_token() == "tok-1"
    assert len(seen) == 1
    assert seen[0]["grant_type"] == "client_credentials"
    assert seen[0]["client_id"] == "client-1"
    assert seen[0]["scope"] == "sap.read"


def test_token_failure_does_not_echo_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="client_secret=s3cr3t is invalid")

    provider = SAPOAuthTokenProvider(
        token_url="https://auth.test/token",
        client_id="client-1",
        client_secret="s3cr3t",
        scope="sap.read",
        max_attempts=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(IntegrationRequestError) as info:
        provider.access_token()
    assert info.value.status_code == 401
    assert "s3cr3t" not in str(info.value)


def test_token_acquisition_logs_no_secret_or_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.integrations.sap_auth")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tok-secret-value", "expires_in": 60})

    provider = SAPOAuthTokenProvider(
        token_url="https://auth.test/token",
        client_id="client-1",
        client_secret="s3cr3t",
        scope="sap.read",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.access_token()

    assert "tok-secret-value" not in caplog.text
    assert "s3cr3t" not in caplog.text


def test_sap_http_client_sends_bearer_token_without_api_key() -> None:
    captured: list[httpx.Request] = []

    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})

    def api_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": []})

    tokens = SAPOAuthTokenProvider(
        token_url="https://auth.test/token",
        client_id="client-1",
        client_secret="s3cr3t",
        scope="sap.read",
        client=httpx.Client(transport=httpx.MockTransport(token_handler)),
    )
    client = SAPHttpClient(
        connector_name="sap",
        base_url="https://sap.test",
        client=httpx.Client(transport=httpx.MockTransport(api_handler)),
        tokens=tokens,
    )

    client.get_json("/sap/opu/odata/sap/API_SHIPMENT_SRV/Shipments")

    assert captured[0].headers["authorization"] == "Bearer tok-1"
    assert "x-api-key" not in captured[0].headers


def test_redact_headers_masks_credentials() -> None:
    redacted = redact_headers(
        {"Authorization": "Bearer tok", "x-api-key": "key", "Accept": "application/json"}
    )
    assert redacted == {"Authorization": "***", "x-api-key": "***", "Accept": "application/json"}


# ---------------------------------------------------------------------------
# Read connector: material information and profiles
# ---------------------------------------------------------------------------


def test_simulated_read_connector_exposes_material_master() -> None:
    sap = SimulatedSAPConnector()
    materials = sap.list_materials()
    assert len(materials) == 5
    assert all(isinstance(item, SAPMaterial) for item in materials)
    item = sap.get_material(material_id="MAT-ELEC-003")
    assert item is not None
    assert item.base_unit == "EA"
    assert item.provenance.is_mock is True
    assert sap.get_material(material_id="MAT-UNKNOWN") is None


def test_live_read_connector_uses_the_selected_profile_path() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "material_id": "MAT-1",
                        "description": "Widget",
                        "material_type": "Finished good",
                        "base_unit": "EA",
                        "category": "Test",
                    }
                ]
            },
        )

    connector = HttpSAPConnector(
        _blank(SAP_BASE_URL="https://sap.test"),
        client=_client(handler),
        profile=get_sap_profile("btp"),
    )
    materials = connector.list_materials()

    assert paths == ["/btp/s4/materials"]
    assert materials[0].material_id == "MAT-1"
    assert materials[0].provenance.is_mock is False


def test_live_read_connector_returns_none_for_missing_material() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    connector = HttpSAPConnector(
        _blank(SAP_BASE_URL="https://sap.test"),
        client=_client(handler),
        profile=get_sap_profile("s4hana"),
    )
    assert connector.get_material(material_id="MAT-404") is None


@pytest.mark.parametrize(
    "operation",
    (
        "apply_shipment_plan",
        "request_inventory_transfer",
        "record_operational_change",
        "write",
        "execute",
    ),
)
def test_read_connector_still_exposes_no_write_operations(operation: str) -> None:
    assert not hasattr(SimulatedSAPConnector(), operation)
    assert not hasattr(HttpSAPConnector, operation)


def test_read_factory_still_returns_the_simulated_connector_under_mock() -> None:
    connector = get_sap_connector(_blank(SAP_USE_MOCK=True))
    assert isinstance(connector, SimulatedSAPConnector)


# ---------------------------------------------------------------------------
# Write-request validation
# ---------------------------------------------------------------------------


def test_shipment_plan_update_requires_identifiers() -> None:
    with pytest.raises(ValidationError):
        SAPShipmentPlanUpdate(request_id="", shipment_id="SH001")
    with pytest.raises(ValidationError):
        SAPShipmentPlanUpdate(request_id="req-1", shipment_id="")


def test_inventory_transfer_requires_positive_units_and_distinct_plants() -> None:
    with pytest.raises(ValidationError):
        SAPInventoryTransferRequest(
            request_id="req-2",
            material_id="MAT-ELEC-003",
            source_plant="Singapore DC",
            target_plant="Rotterdam DC",
            units=0,
        )
    with pytest.raises(ValidationError, match="must be different"):
        SAPInventoryTransferRequest(
            request_id="req-2",
            material_id="MAT-ELEC-003",
            source_plant="Rotterdam DC",
            target_plant="Rotterdam DC",
            units=10,
        )


def test_operational_change_requires_a_description() -> None:
    with pytest.raises(ValidationError):
        SAPOperationalChange(request_id="req-3", change_type="reroute", description="")


# ---------------------------------------------------------------------------
# Approval evidence is mandatory
# ---------------------------------------------------------------------------


def test_approval_evidence_from_an_approved_decision() -> None:
    evidence = _evidence()
    assert evidence.approver_id == "mgr-1"
    assert evidence.thread_id == "thread-1"
    assert evidence.proposal_version == "abc123def456"
    assert evidence.action is ApprovalAction.APPROVE


@pytest.mark.parametrize(
    "action", (ApprovalAction.REJECT, ApprovalAction.REQUEST_MODIFICATIONS)
)
def test_only_an_approve_decision_can_produce_evidence(action: ApprovalAction) -> None:
    with pytest.raises(SAPWriteNotAuthorizedError, match="does not authorise"):
        approval_evidence_from_decision(_decision(action=action), thread_id="thread-1")


def test_evidence_requires_the_workflow_thread() -> None:
    with pytest.raises(SAPWriteNotAuthorizedError, match="workflow thread"):
        approval_evidence_from_decision(_decision(), thread_id="  ")


def test_write_requires_keyword_approval_evidence() -> None:
    writer = SimulatedSAPWriteConnector()
    with pytest.raises(TypeError):
        writer.apply_shipment_plan(_shipment_request())  # type: ignore[call-arg]
    with pytest.raises(SAPWriteNotAuthorizedError):
        writer.apply_shipment_plan(_shipment_request(), approval=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Simulated writes
# ---------------------------------------------------------------------------


def test_simulated_write_is_labelled_deterministic_and_covers_all_operations() -> None:
    writer = SimulatedSAPWriteConnector()
    evidence = _evidence()

    shipment = writer.apply_shipment_plan(_shipment_request(), approval=evidence)
    transfer = writer.request_inventory_transfer(
        SAPInventoryTransferRequest(
            request_id="req-2",
            material_id="MAT-ELEC-003",
            source_plant="Singapore DC",
            target_plant="Rotterdam DC",
            units=250,
        ),
        approval=evidence,
    )
    change = writer.record_operational_change(
        SAPOperationalChange(
            request_id="req-3",
            change_type="carrier_change",
            description="Switch to the approved carrier.",
            event_id="EVT-1",
        ),
        approval=evidence,
    )

    for result in (shipment, transfer, change):
        assert result.status is SAPWriteStatus.SIMULATED
        assert result.is_mock is True
        assert result.provenance.is_mock is True
        assert result.message.startswith("[SIMULATED]")
        assert result.external_reference.startswith("SIM-SAP-")

    repeat = writer.apply_shipment_plan(_shipment_request(), approval=evidence)
    assert repeat.external_reference == shipment.external_reference
    assert repeat.idempotency_key == shipment.idempotency_key


def test_idempotency_key_binds_the_approval_version_and_request() -> None:
    evidence = _evidence()
    request = _shipment_request()
    key = sap_idempotency_key(evidence, request)
    assert key == (
        "sap:thread-1:abc123def456:shipment_plan_update:req-1"
    )


# ---------------------------------------------------------------------------
# Separate write permission and the factory
# ---------------------------------------------------------------------------


def test_write_access_is_disabled_by_default() -> None:
    assert _blank().SAP_WRITE_ENABLED is False
    with pytest.raises(SAPWritePermissionError, match="SAP_WRITE_ENABLED"):
        get_sap_write_connector(_blank())


def test_enabled_mock_mode_returns_the_simulated_writer() -> None:
    writer = get_sap_write_connector(_blank(SAP_WRITE_ENABLED=True, SAP_USE_MOCK=True))
    assert isinstance(writer, SimulatedSAPWriteConnector)
    assert writer.is_mock is True


def test_enabled_live_mode_requires_credentials() -> None:
    with pytest.raises(IntegrationNotConfiguredError):
        get_sap_write_connector(_blank(SAP_WRITE_ENABLED=True, SAP_USE_MOCK=False))


def test_enabled_live_mode_returns_a_profile_bound_writer() -> None:
    settings = _blank(
        SAP_WRITE_ENABLED=True,
        SAP_USE_MOCK=False,
        SAP_API_FAMILY="integration_suite",
        SAP_BASE_URL="https://sap.test",
        SAP_CLIENT_ID="client-1",
        SAP_CLIENT_SECRET="s3cr3t",
    )
    writer = get_sap_write_connector(settings)
    assert isinstance(writer, HttpSAPWriteConnector)
    assert writer.profile.family is SAPApiFamily.INTEGRATION_SUITE


def test_read_access_does_not_imply_write_access() -> None:
    settings = _blank(
        SAP_USE_MOCK=False,
        SAP_BASE_URL="https://sap.test",
        SAP_CLIENT_ID="client-1",
        SAP_CLIENT_SECRET="s3cr3t",
    )
    assert get_sap_connector(settings).is_mock is False
    with pytest.raises(SAPWritePermissionError):
        get_sap_write_connector(settings)


# ---------------------------------------------------------------------------
# Live writes
# ---------------------------------------------------------------------------


def test_live_write_posts_a_validated_payload_with_bearer_and_idempotency() -> None:
    captured: list[httpx.Request] = []
    bodies: list[dict] = []

    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tok-write", "expires_in": 3600})

    def api_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"d": {"documentNumber": "DOC-1"}})

    tokens = SAPOAuthTokenProvider(
        token_url="https://auth.test/token",
        client_id="client-1",
        client_secret="s3cr3t",
        scope="sap.write",
        client=httpx.Client(transport=httpx.MockTransport(token_handler)),
    )
    api_client = SAPHttpClient(
        connector_name="sap-write",
        base_url="https://sap.test",
        client=httpx.Client(transport=httpx.MockTransport(api_handler)),
        tokens=tokens,
    )
    writer = HttpSAPWriteConnector(
        _blank(SAP_CLIENT_ID="client-1", SAP_CLIENT_SECRET="s3cr3t"),
        client=api_client,
        profile=get_sap_profile("s4hana"),
    )

    evidence = _evidence()
    result = writer.apply_shipment_plan(_shipment_request(), approval=evidence)

    assert result.status is SAPWriteStatus.ACCEPTED
    assert result.is_mock is False
    assert result.external_reference == "DOC-1"
    assert captured[0].method == "POST"
    assert captured[0].url.path == "/sap/opu/odata/sap/API_SHIPMENT_SRV/PlanUpdates"
    assert captured[0].headers["authorization"] == "Bearer tok-write"
    assert captured[0].headers["idempotency-key"] == sap_idempotency_key(evidence, _shipment_request())
    assert bodies[0]["request"]["shipment_id"] == "SH001"
    assert bodies[0]["approval"]["proposal_version"] == "abc123def456"
    assert bodies[0]["approval"]["approver_id"] == "mgr-1"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    ((400, SAPWriteStatus.REJECTED), (503, SAPWriteStatus.FAILED)),
)
def test_live_write_classifies_sap_rejections_and_failures(
    status_code: int, expected: SAPWriteStatus
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "nope"})

    writer = HttpSAPWriteConnector(
        _blank(SAP_CLIENT_ID="client-1", SAP_CLIENT_SECRET="s3cr3t"),
        client=_client(handler, max_attempts=1),
        profile=get_sap_profile("s4hana"),
    )

    result = writer.apply_shipment_plan(_shipment_request(), approval=_evidence())

    assert result.status is expected
    assert result.is_mock is False


def test_retry_after_header_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.integrations.base.time.sleep", sleeps.append)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, max_attempts=3, backoff_seconds=5.0)
    assert client.get_json("/anything") == {"ok": True}
    assert sleeps == [0.0]


# ---------------------------------------------------------------------------
# End-to-end: approved decision -> SAP write
# ---------------------------------------------------------------------------


def test_approved_decision_can_be_written_but_a_rejection_cannot() -> None:
    writer = SimulatedSAPWriteConnector()

    approved = approval_evidence_from_decision(_decision(), thread_id="thread-9")
    result = writer.record_operational_change(
        SAPOperationalChange(
            request_id="req-9",
            change_type="reroute",
            description="Apply the approved recovery plan.",
            event_id="EVT-9",
            cost_usd=150000.0,
        ),
        approval=approved,
    )
    assert result.status is SAPWriteStatus.SIMULATED
    assert "thread-9" in result.idempotency_key

    with pytest.raises(SAPWriteNotAuthorizedError):
        approval_evidence_from_decision(
            _decision(action=ApprovalAction.REJECT), thread_id="thread-9"
        )
