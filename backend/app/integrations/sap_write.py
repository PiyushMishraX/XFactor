"""Authorized SAP write operations (Step 7).

This module is the **only** place X FACTOR can change SAP. Every method requires
:class:`SAPApprovalEvidence`, which can only be produced from an approved human
decision (see :func:`approval_evidence_from_decision`). A write therefore cannot
be issued by an agent, an LLM or an unauthenticated caller:

* the read connector in :mod:`app.integrations.sap` stays read-only;
* write access is disabled by default (``SAP_WRITE_ENABLED=false``) and is a
  separate permission from reading;
* live writes request the ``SAP_WRITE_SCOPE`` token scope and send an
  ``Idempotency-Key`` so a retried request is not applied twice;
* the mock adapter is used while ``SAP_USE_MOCK`` is true and is labelled
  ``[SIMULATED]`` on every result.

Request validation happens in the Pydantic models below, before any network call.
Transport failures and SAP rejections are returned as typed
:class:`SAPWriteResult` values (``rejected`` / ``failed``) rather than raised, so
the caller always records what happened.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpJsonClient,
    IntegrationError,
    IntegrationNotConfiguredError,
    IntegrationRequestError,
    MockConnector,
    Provenance,
    stable_seed,
)
from app.integrations.sap_auth import SAPHttpClient, sap_token_provider
from app.integrations.sap_profiles import SAPApiProfile, resolve_sap_profile
from app.schemas.approval_schemas import ApprovalAction, ApprovalDecisionRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SAPWriteError(IntegrationError):
    """Base class for SAP write failures."""


class SAPWritePermissionError(SAPWriteError):
    """Write operations are not permitted by configuration or by the profile."""


class SAPWriteNotAuthorizedError(SAPWriteError):
    """A write was requested without evidence of a human approval."""


# ---------------------------------------------------------------------------
# Approval evidence
# ---------------------------------------------------------------------------


class SAPApprovalEvidence(BaseModel):
    """Proof that an authenticated human approved the proposal being written.

    The evidence is built from an :class:`ApprovalDecisionRecord`; it is never
    accepted from a request body. ``proposal_version`` ties the write to the exact
    proposal that was reviewed, so an approval of an older plan cannot be used.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    approval_id: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    approver_role: str = ""
    thread_id: str = Field(min_length=1)
    proposal_version: str = Field(min_length=1)
    decided_at: datetime
    action: ApprovalAction = ApprovalAction.APPROVE

    @model_validator(mode="after")
    def _must_be_an_approval(self) -> "SAPApprovalEvidence":
        if self.action is not ApprovalAction.APPROVE:
            raise ValueError("SAP writes require an approve decision.")
        return self


def approval_evidence_from_decision(
    decision: ApprovalDecisionRecord,
    *,
    thread_id: str,
    approval_id: str = "",
) -> SAPApprovalEvidence:
    """Build write evidence from an authenticated approval decision.

    Raises:
        SAPWriteNotAuthorizedError: The decision was a rejection or a request for
            modifications, so no write is authorised.
    """
    if not decision.approved:
        raise SAPWriteNotAuthorizedError(
            f"Decision {decision.action.value!r} does not authorise a SAP write; "
            f"only an approve decision may be written."
        )
    thread = (thread_id or "").strip()
    if not thread:
        raise SAPWriteNotAuthorizedError(
            "SAP write evidence must be bound to the workflow thread that was approved."
        )
    return SAPApprovalEvidence(
        approval_id=approval_id or f"{thread}:{decision.proposal_version}",
        approver_id=decision.approver_id,
        approver_role=decision.approver_role,
        thread_id=thread,
        proposal_version=decision.proposal_version,
        decided_at=decision.decided_at,
        action=decision.action,
    )


# ---------------------------------------------------------------------------
# Validated write requests
# ---------------------------------------------------------------------------


class SAPWriteType(str, Enum):
    """The SAP operations this connector can perform where the tenant supports it."""

    SHIPMENT_PLAN_UPDATE = "shipment_plan_update"
    INVENTORY_TRANSFER = "inventory_transfer"
    OPERATIONAL_CHANGE = "operational_change"


class _WriteRequest(BaseModel):
    """Shared validation for every SAP write request."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=128)

    @property
    def request_type(self) -> SAPWriteType:
        raise NotImplementedError

    def to_payload(self) -> Dict[str, Any]:
        """The JSON-safe body sent to SAP (without the approval envelope)."""
        return self.model_dump(mode="json")


class SAPShipmentPlanUpdate(_WriteRequest):
    """Update the shipment plan for one shipment (where SAP supports it)."""

    shipment_id: str = Field(min_length=1, max_length=64)
    origin: str = ""
    destination: str = ""
    carrier: str = ""
    transport_mode: str = ""
    planned_cost_usd: float = Field(default=0.0, ge=0.0)
    planned_days: float = Field(default=0.0, ge=0.0)

    @property
    def request_type(self) -> SAPWriteType:
        return SAPWriteType.SHIPMENT_PLAN_UPDATE


class SAPInventoryTransferRequest(_WriteRequest):
    """Request a stock transfer between two plants."""

    material_id: str = Field(min_length=1, max_length=64)
    source_plant: str = Field(min_length=1, max_length=64)
    target_plant: str = Field(min_length=1, max_length=64)
    units: float = Field(gt=0.0, description="Must be positive; zero-unit transfers are refused.")
    planned_cost_usd: float = Field(default=0.0, ge=0.0)

    @property
    def request_type(self) -> SAPWriteType:
        return SAPWriteType.INVENTORY_TRANSFER

    @model_validator(mode="after")
    def _plants_must_differ(self) -> "SAPInventoryTransferRequest":
        if self.source_plant == self.target_plant:
            raise ValueError("source_plant and target_plant must be different.")
        return self


class SAPOperationalChange(_WriteRequest):
    """Record an approved operational change against a disruption event."""

    change_type: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    event_id: str = ""
    cost_usd: float = Field(default=0.0, ge=0.0)

    @property
    def request_type(self) -> SAPWriteType:
        return SAPWriteType.OPERATIONAL_CHANGE


# ---------------------------------------------------------------------------
# Write results
# ---------------------------------------------------------------------------


class SAPWriteStatus(str, Enum):
    """Outcome of one SAP write request."""

    ACCEPTED = "accepted"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    FAILED = "failed"


class SAPWriteResult(BaseModel):
    """What happened to one SAP write request, with provenance."""

    request_id: str
    request_type: SAPWriteType
    status: SAPWriteStatus
    idempotency_key: str = ""
    external_reference: str = ""
    message: str = ""
    is_mock: bool = True
    provenance: Provenance
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def sap_idempotency_key(evidence: SAPApprovalEvidence, request: _WriteRequest) -> str:
    """Stable key for one approved request; a retry must not apply it twice."""
    return (
        f"sap:{evidence.thread_id}:{evidence.proposal_version}:"
        f"{request.request_type.value}:{request.request_id}"
    )


def _require_approval(approval: Optional[SAPApprovalEvidence]) -> SAPApprovalEvidence:
    """Refuse a write that is not backed by explicit human approval evidence."""
    if approval is None:
        raise SAPWriteNotAuthorizedError(
            "A SAP write requires SAPApprovalEvidence from an authenticated approval."
        )
    if approval.action is not ApprovalAction.APPROVE or not approval.proposal_version:
        raise SAPWriteNotAuthorizedError(
            "SAP write evidence must be an approve decision for a versioned proposal."
        )
    return approval


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


class SAPWriteConnector(Protocol):
    """Authorized SAP write interface; every method requires approval evidence."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def apply_shipment_plan(
        self, request: SAPShipmentPlanUpdate, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult: ...

    def request_inventory_transfer(
        self, request: SAPInventoryTransferRequest, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult: ...

    def record_operational_change(
        self, request: SAPOperationalChange, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult: ...


class SimulatedSAPWriteConnector(MockConnector):
    """Clearly labelled SAP write simulator; changes no SAP system."""

    name = "sap-write"
    provider = "X FACTOR simulated SAP write connector"

    def apply_shipment_plan(
        self, request: SAPShipmentPlanUpdate, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult:
        return self._apply(request, approval)

    def request_inventory_transfer(
        self, request: SAPInventoryTransferRequest, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult:
        return self._apply(request, approval)

    def record_operational_change(
        self, request: SAPOperationalChange, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult:
        return self._apply(request, approval)

    def _apply(self, request: _WriteRequest, approval: SAPApprovalEvidence) -> SAPWriteResult:
        evidence = _require_approval(approval)
        key = sap_idempotency_key(evidence, request)
        reference = (
            f"SIM-SAP-{request.request_type.value.upper()}-{stable_seed(key):08X}"
        )
        logger.info("Simulated SAP write %s (%s).", request.request_id, reference)
        return SAPWriteResult(
            request_id=request.request_id,
            request_type=request.request_type,
            status=SAPWriteStatus.SIMULATED,
            idempotency_key=key,
            external_reference=reference,
            message=(
                "[SIMULATED] Request accepted by the simulated SAP adapter; no SAP "
                "system was changed."
            ),
            is_mock=True,
            provenance=self.provenance(endpoint="simulated://sap/write"),
        )


class HttpSAPWriteConnector:
    """Live authorized SAP writes through the selected prepared profile."""

    name = "sap-write"
    is_mock = False
    provider = "Live SAP write API"

    #: Statuses that mean SAP refused the request, as opposed to failing.
    _REJECTED_STATUSES = frozenset({400, 409, 422})

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[HttpJsonClient] = None,
        *,
        profile: Optional[SAPApiProfile] = None,
    ) -> None:
        settings = settings or get_settings()
        self._profile = profile or resolve_sap_profile(settings)
        self._client_id = settings.SAP_CLIENT_ID
        if client is None:
            tokens = sap_token_provider(settings, scope=settings.SAP_WRITE_SCOPE)
            if tokens is not None:
                client = SAPHttpClient(
                    connector_name=self.name,
                    base_url=settings.SAP_BASE_URL,
                    timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                    max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
                    tokens=tokens,
                )
            else:
                client = HttpJsonClient(
                    connector_name=self.name,
                    base_url=settings.SAP_BASE_URL,
                    api_key=settings.SAP_CLIENT_SECRET,
                    timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                    max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
                )
        self._client = client

    @property
    def profile(self) -> SAPApiProfile:
        return self._profile

    def apply_shipment_plan(
        self, request: SAPShipmentPlanUpdate, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult:
        return self._apply(request, approval)

    def request_inventory_transfer(
        self, request: SAPInventoryTransferRequest, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult:
        return self._apply(request, approval)

    def record_operational_change(
        self, request: SAPOperationalChange, *, approval: SAPApprovalEvidence
    ) -> SAPWriteResult:
        return self._apply(request, approval)

    def _apply(self, request: _WriteRequest, approval: SAPApprovalEvidence) -> SAPWriteResult:
        evidence = _require_approval(approval)
        key = sap_idempotency_key(evidence, request)
        path = self._profile.write_path(request.request_type.value)
        payload = {
            "request": request.to_payload(),
            "approval": {
                "approval_id": evidence.approval_id,
                "approver_id": evidence.approver_id,
                "approver_role": evidence.approver_role,
                "thread_id": evidence.thread_id,
                "proposal_version": evidence.proposal_version,
                "decided_at": evidence.decided_at.isoformat(),
            },
            "idempotency_key": key,
        }

        logger.info(
            "SAP write %s (%s) -> %s", request.request_id, request.request_type.value, path
        )
        try:
            response = self._client.post_json(
                path,
                payload=payload,
                idempotency_key=key,
                headers={"x-client-id": self._client_id} if self._client_id else None,
            )
        except IntegrationRequestError as exc:
            rejected = exc.status_code in self._REJECTED_STATUSES
            logger.warning(
                "SAP write %s %s (status=%s).",
                request.request_id,
                "rejected" if rejected else "failed",
                exc.status_code,
            )
            return SAPWriteResult(
                request_id=request.request_id,
                request_type=request.request_type,
                status=SAPWriteStatus.REJECTED if rejected else SAPWriteStatus.FAILED,
                idempotency_key=key,
                message=str(exc)[:500],
                is_mock=False,
                provenance=self._provenance(path),
            )

        reference = _extract_reference(response)
        return SAPWriteResult(
            request_id=request.request_id,
            request_type=request.request_type,
            status=SAPWriteStatus.ACCEPTED,
            idempotency_key=key,
            external_reference=reference,
            message="Accepted by the live SAP write API.",
            is_mock=False,
            provenance=self._provenance(path),
        )

    def _provenance(self, path: str) -> Provenance:
        return Provenance(
            source=self.provider,
            is_mock=False,
            endpoint=f"{self._client.base_url}{path}",
        )


_REFERENCE_KEYS = ("reference", "id", "request_id", "documentNumber", "document_number")


def _extract_reference(payload: Any) -> str:
    """Read the document reference from common REST/OData response shapes."""
    if isinstance(payload, Mapping):
        for key in _REFERENCE_KEYS:
            value = payload.get(key)
            if value:
                return str(value)
        for wrapper in ("d", "value"):
            inner = payload.get(wrapper)
            if isinstance(inner, Mapping):
                return _extract_reference(inner)
            if isinstance(inner, list) and inner:
                return _extract_reference(inner[0])
    return ""


def get_sap_write_connector(settings: Optional[Settings] = None) -> SAPWriteConnector:
    """Return the authorized write connector, honouring the write permission.

    Raises:
        SAPWritePermissionError: ``SAP_WRITE_ENABLED`` is false (the default) or
            the selected profile does not support writes.
        IntegrationNotConfiguredError: Mock mode is off but no SAP credentials
            are configured, or ``SAP_API_FAMILY`` is unknown.
    """
    settings = settings or get_settings()
    if not settings.SAP_WRITE_ENABLED:
        raise SAPWritePermissionError(
            "SAP write operations are disabled. Set SAP_WRITE_ENABLED=true only after "
            "read access and the approval workflow have been verified."
        )
    if settings.SAP_USE_MOCK:
        logger.info("SAP_USE_MOCK is enabled — using the simulated SAP write connector.")
        return SimulatedSAPWriteConnector()
    if not settings.sap_configured:
        raise IntegrationNotConfiguredError(
            "SAP write access is enabled but SAP_BASE_URL / SAP_CLIENT_ID / "
            "SAP_CLIENT_SECRET are not all configured."
        )
    profile = resolve_sap_profile(settings)
    if not profile.supports_write:
        raise SAPWritePermissionError(
            f"The {profile.display_name} profile does not support write operations."
        )
    logger.info("SAP write connector using the %s profile.", profile.display_name)
    return HttpSAPWriteConnector(settings, profile=profile)


__all__ = [
    "SAPApprovalEvidence",
    "SAPInventoryTransferRequest",
    "SAPOperationalChange",
    "SAPShipmentPlanUpdate",
    "SAPWriteConnector",
    "SAPWriteError",
    "SAPWriteNotAuthorizedError",
    "SAPWritePermissionError",
    "SAPWriteResult",
    "SAPWriteStatus",
    "SAPWriteType",
    "SimulatedSAPWriteConnector",
    "HttpSAPWriteConnector",
    "approval_evidence_from_decision",
    "get_sap_write_connector",
    "sap_idempotency_key",
]
