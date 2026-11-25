"""Step 6 tests: human approval, proposal versioning and authorized execution.

The properties pinned down here are the ones the roadmap calls out explicitly:

* only an authenticated, sufficiently authorized approver can decide;
* a decision is bound to the exact proposal version the reviewer saw;
* the approver identity and timestamp are recorded, and the decision history is
  preserved across reconsideration rounds;
* a human modification request revises the plan but cannot loop forever;
* execution happens only after an approval, is idempotent, and is clearly
  labelled when simulated;
* the HTTP approval API returns 401 / 403 / 409 / 503 rather than trusting any
  status supplied by an unauthenticated caller.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.approvals as approvals_api
from app.api.approvals import (
    approval_authorizer,
    approval_repository,
    execution_adapter,
)
from app.config.settings import Settings
from app.database.session import get_db
from app.integrations.base import HttpJsonClient, IntegrationNotConfiguredError
from app.main import app
from app.orchestration.approvals import (
    MAX_MODIFICATION_ROUNDS,
    build_modification_revision,
    build_proposal_snapshot,
    build_resume_payload,
    parse_approval_decision,
)
from app.orchestration.state import (
    STATUS_APPROVAL_REJECTED,
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
)
from app.orchestration.workflow import pending_interrupt
from app.schemas.approval_schemas import (
    ApprovalAction,
    ApprovalDecisionRecord,
    ApprovalRequestView,
    ApprovalStatus,
    ApproverIdentity,
    ApproverRole,
    ProposalSnapshot,
)
from app.schemas.execution_schemas import (
    ExecutionAction,
    ExecutionActionStatus,
    ExecutionActionType,
    ExecutionReport,
    ExecutionRunStatus,
)
from app.services.approval_auth import (
    ApprovalAuthorizer,
    ApprovalConfigurationError,
    ApproverAuthenticationError,
    ApproverAuthorizationError,
    extract_bearer_token,
    parse_credentials,
)
from app.services.approval_repository import (
    InMemoryApprovalRepository,
    PostgresApprovalRepository,
    ensure_approval_schema,
)
from app.services.execution import (
    ExecutionNotAuthorizedError,
    ExecutionService,
    HttpExecutionAdapter,
    SimulatedExecutionAdapter,
    build_execution_plan,
    get_execution_adapter,
)
from tests.test_orchestration import build_workflow, make_request

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MANAGER_TOKEN = "manager-token"
DIRECTOR_TOKEN = "director-token"
ADMIN_TOKEN = "admin-token"
CREDENTIALS = (
    f"{MANAGER_TOKEN}:alice:Manager,"
    f"{DIRECTOR_TOKEN}:bob:Director,"
    f"{ADMIN_TOKEN}:root:Admin"
)


def _authorizer(raw: str = CREDENTIALS) -> ApprovalAuthorizer:
    return ApprovalAuthorizer(raw)


def _bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_proposal(**overrides: Any) -> ProposalSnapshot:
    payload: Dict[str, Any] = {
        "thread_id": "t-proposal",
        "event_id": "EV-APPROVAL-1",
        "proposal_id": "EV-APPROVAL-1:SC1",
        "approval_level": "Director",
        "requires_approval": True,
        "verdict": "Approved",
        "is_compliant": True,
        "is_within_budget": True,
        "reasons": ["High-impact reroute"],
        "violations": ["Spend exceeds the delegated limit"],
        "headline": "EV-APPROVAL-1: scenario SC1 recommended via CarrierB",
        "summary": "Recommended scenario SC1 at 420000 USD.",
        "recommended_scenario_id": "SC1",
        "recommended_route_id": None,
        "recommended_carrier": "CarrierB",
        "transport_mode": "Rail",
        "total_cost_usd": 420_000.0,
        "total_days": 9.0,
        "shipment_value_usd": 100_000.0,
        "inventory_transfer_units": 600.0,
        "supplier_id": "SUP-TEST-1",
        "carrier_change_requested": True,
    }
    payload.update(overrides)
    return ProposalSnapshot(**payload).with_version()


def make_view(snapshot: ProposalSnapshot) -> ApprovalRequestView:
    return ApprovalRequestView(
        thread_id=snapshot.thread_id,
        event_id=snapshot.event_id,
        proposal_id=snapshot.proposal_id,
        proposal_version=snapshot.proposal_version,
        approval_level=snapshot.approval_level,
        status=ApprovalStatus.PENDING,
        proposal=snapshot,
    )


def paused_workflow(thread_id: str = "t-api") -> Any:
    """A real supervisor paused at the Director approval gate."""
    workflow = build_workflow()
    paused = workflow.invoke(
        make_request(is_high_impact_reroute=True), thread_id=thread_id
    )
    payload = pending_interrupt(paused)
    assert payload is not None, "the workflow did not pause for approval"
    return workflow, payload, paused


def make_execution_report(
    proposal: ProposalSnapshot, *, status: ExecutionRunStatus = ExecutionRunStatus.COMPLETED
) -> ExecutionReport:
    return ExecutionReport(
        execution_id=f"exec-{proposal.thread_id}-{proposal.proposal_version}",
        thread_id=proposal.thread_id,
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.proposal_version,
        status=status,
        actions=[],
        completed_at=datetime.now(timezone.utc),
    )


class RecordingExecutionStore:
    """Minimal execution store for the service tests."""

    def __init__(self) -> None:
        self.reports: Dict[tuple, ExecutionReport] = {}

    def get_execution(
        self, thread_id: str, proposal_version: str
    ) -> Optional[ExecutionReport]:
        return self.reports.get((thread_id, proposal_version))

    def save_execution(self, thread_id: str, report: ExecutionReport) -> None:
        self.reports[(thread_id, report.proposal_version)] = report


class CountingAdapter:
    """Counts real calls so idempotent replays are observable."""

    name = "counting"
    is_mock = True

    def __init__(self) -> None:
        self._inner = SimulatedExecutionAdapter()
        self.calls = 0

    def execute(self, action: ExecutionAction) -> ExecutionAction:
        self.calls += 1
        return self._inner.execute(action)


class PartialFailureAdapter:
    """Simulates a gateway that rejects only the inventory transfer."""

    name = "partial-gateway"
    is_mock = False

    def execute(self, action: ExecutionAction) -> ExecutionAction:
        if action.action_type is ExecutionActionType.INVENTORY_TRANSFER:
            return action.model_copy(
                update={
                    "status": ExecutionActionStatus.FAILED,
                    "adapter": self.name,
                    "is_mock": False,
                    "message": "The gateway rejected the transfer request.",
                }
            )
        return action.model_copy(
            update={"status": ExecutionActionStatus.EXECUTED, "adapter": self.name, "is_mock": False}
        )


class RaisingAdapter:
    """Every action raises, which the service must record rather than hide."""

    name = "raising-gateway"
    is_mock = False

    def execute(self, action: ExecutionAction) -> ExecutionAction:
        raise RuntimeError("gateway unavailable")


@pytest.fixture
def api():
    """A TestClient with overridable approval dependencies and no lifespan."""
    client = TestClient(app)

    def install(
        *,
        repository: Any,
        authorizer: ApprovalAuthorizer,
        execution: Any = None,
        workflow: Any = None,
        monkeypatch: Any = None,
    ) -> None:
        app.dependency_overrides[approval_repository] = lambda: repository
        app.dependency_overrides[approval_authorizer] = lambda: authorizer
        app.dependency_overrides[execution_adapter] = (
            lambda: execution if execution is not None else SimulatedExecutionAdapter()
        )
        app.dependency_overrides[get_db] = lambda: None
        if workflow is not None:
            assert monkeypatch is not None

            @contextlib.contextmanager
            def runtime(*, session: Any = None, **_: Any):
                yield workflow

            monkeypatch.setattr(approvals_api, "supervisor_runtime", runtime)

    try:
        yield client, install
    finally:
        for dependency in (
            approval_repository,
            approval_authorizer,
            execution_adapter,
            get_db,
        ):
            app.dependency_overrides.pop(dependency, None)


# ---------------------------------------------------------------------------
# Proposal versioning
# ---------------------------------------------------------------------------


def test_proposal_version_is_stable_and_excludes_review_metadata() -> None:
    proposal = make_proposal()
    version = proposal.proposal_version

    assert len(version) == 16
    assert all(character in "0123456789abcdef" for character in version)
    assert proposal.compute_version() == version
    assert proposal.with_version().proposal_version == version

    # Identity, display timestamp and the digest itself are not proposal facts.
    for field, value in {
        "thread_id": "another-thread",
        "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "proposal_version": "ffffffffffffffff",
    }.items():
        assert proposal.model_copy(update={field: value}).compute_version() == version

    # A changed operational fact is a different proposal and must not validate.
    changed = proposal.model_copy(update={"total_cost_usd": proposal.total_cost_usd + 1})
    assert changed.compute_version() != version


def test_graph_and_api_agree_on_the_proposal_version() -> None:
    workflow, payload, paused = paused_workflow("t-version")
    graph_view = build_proposal_snapshot("", paused)
    api_view = build_proposal_snapshot("t-version", paused)

    assert graph_view is not None and api_view is not None
    assert graph_view.proposal_version == api_view.proposal_version
    assert api_view.proposal_version == payload["proposal_version"]
    assert api_view.thread_id == "t-version"
    assert api_view.approval_level == "Director"
    assert api_view.requires_approval is True
    assert "shipment_plan_update" in api_view.actions


# ---------------------------------------------------------------------------
# Approver authentication and authorization
# ---------------------------------------------------------------------------


def test_parse_credentials_reads_every_entry() -> None:
    credentials = parse_credentials(CREDENTIALS)
    assert [
        (entry.identity.approver_id, entry.identity.role) for entry in credentials
    ] == [
        ("alice", ApproverRole.MANAGER),
        ("bob", ApproverRole.DIRECTOR),
        ("root", ApproverRole.ADMIN),
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "token-only",
        "tok:alice:King",
        ":alice:Manager",
        "tok::Manager",
        "same:alice:Manager,same:bob:Director",
    ],
)
def test_malformed_credentials_fail_closed(raw: str) -> None:
    with pytest.raises(ApprovalConfigurationError):
        parse_credentials(raw)


def test_authenticate_maps_tokens_to_identities() -> None:
    authorizer = _authorizer()

    assert authorizer.authenticate(DIRECTOR_TOKEN).approver_id == "bob"
    assert authorizer.authenticate(DIRECTOR_TOKEN).role is ApproverRole.DIRECTOR
    assert authorizer.authenticate(f"  {MANAGER_TOKEN}  ").approver_id == "alice"
    assert authorizer.configured is True
    assert _authorizer(" ").configured is False

    with pytest.raises(ApproverAuthenticationError):
        authorizer.authenticate("")
    with pytest.raises(ApproverAuthenticationError) as unknown:
        authorizer.authenticate("not-a-configured-token")
    assert "before the first colon" in str(unknown.value)

    # Pasting the whole APPROVER_CREDENTIALS entry is the common misconfiguration.
    with pytest.raises(ApproverAuthenticationError) as whole_entry:
        authorizer.authenticate(f"{DIRECTOR_TOKEN}:bob:Director")
    assert "not the whole entry" in str(whole_entry.value)


def test_role_hierarchy_enforces_the_approval_level() -> None:
    authorizer = _authorizer()
    manager = authorizer.authenticate(MANAGER_TOKEN)
    director = authorizer.authenticate(DIRECTOR_TOKEN)
    admin = authorizer.authenticate(ADMIN_TOKEN)

    authorizer.authorize(manager, "Manager")
    authorizer.authorize(manager, "")
    authorizer.authorize(director, "Director")
    authorizer.authorize(admin, "Director")
    authorizer.authorize(admin, "Unrecognised level")

    with pytest.raises(ApproverAuthorizationError):
        authorizer.authorize(manager, "Director")
    with pytest.raises(ApproverAuthorizationError):
        authorizer.authorize(director, "Unrecognised level")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("  Bearer abc  ", "abc"),
    ],
)
def test_extract_bearer_token_reads_the_scheme(header: str, expected: str) -> None:
    assert extract_bearer_token(header) == expected


@pytest.mark.parametrize("header", [None, "", "abc", "Basic abc", "Bearer", "Bearer   "])
def test_extract_bearer_token_rejects_other_schemes(header: Optional[str]) -> None:
    with pytest.raises(ApproverAuthenticationError):
        extract_bearer_token(header)


# ---------------------------------------------------------------------------
# Decision records and modification feedback
# ---------------------------------------------------------------------------


def test_parse_approval_decision_preserves_the_authenticated_record() -> None:
    decided_at = datetime(2026, 11, 22, 10, 30, tzinfo=timezone.utc)
    identity = ApproverIdentity(approver_id="bob", role=ApproverRole.DIRECTOR)
    payload = build_resume_payload(
        action=ApprovalAction.REJECT,
        comment="Margin too thin",
        proposal_version="abc123",
        identity=identity,
        decided_at=decided_at,
    )

    record = parse_approval_decision(payload)
    assert record.action is ApprovalAction.REJECT
    assert record.approver_id == "bob"
    assert record.approver_role == "Director"
    assert record.comment == "Margin too thin"
    assert record.proposal_version == "abc123"
    assert record.decided_at == decided_at
    assert record.status() is ApprovalStatus.REJECTED


def test_parse_approval_decision_accepts_legacy_payloads() -> None:
    approved = parse_approval_decision({"approved": True})
    assert approved.action is ApprovalAction.APPROVE
    assert approved.approver_id == "human"

    rejected = parse_approval_decision({"approved": False, "comment": "No"})
    assert rejected.action is ApprovalAction.REJECT
    assert rejected.comment == "No"
    assert parse_approval_decision("yes").action is ApprovalAction.APPROVE
    assert parse_approval_decision(False).action is ApprovalAction.REJECT


def test_modification_revision_excludes_the_recommended_scenario() -> None:
    state = {
        "scenario_plan": {
            "recommended_scenario_id": "SC2",
            "scenarios": [{"scenario_id": "SC1"}, {"scenario_id": "SC2"}],
        },
        "audit_report": {
            "violations": [{"detail": "Spend exceeds the delegated limit"}],
            "approval": {"reasons": ["High-impact reroute"]},
        },
    }

    revision = build_modification_revision(state, round_number=1, comment="Use rail")
    assert revision.round == 1
    assert revision.rejected_scenario_ids == ["SC2"]
    assert revision.feedback.startswith("Human review requested modifications")
    assert "Use rail" in revision.feedback
    assert revision.rejection_reasons == [
        "Spend exceeds the delegated limit",
        "High-impact reroute",
        "Use rail",
    ]


# ---------------------------------------------------------------------------
# Graph: identity, history and the bounded modification loop
# ---------------------------------------------------------------------------


def test_approval_gate_records_the_authenticated_approver() -> None:
    workflow, payload, _ = paused_workflow("t-graph-approve")
    identity = ApproverIdentity(approver_id="bob", role=ApproverRole.DIRECTOR)

    resumed = workflow.resume(
        build_resume_payload(
            action=ApprovalAction.APPROVE,
            comment="Ship it",
            proposal_version=payload["proposal_version"],
            identity=identity,
        ),
        thread_id="t-graph-approve",
    )

    assert resumed["status"] == STATUS_COMPLETED
    assert resumed["approval"]["approved"] is True
    assert resumed["approval"]["decided_by"] == "bob"
    assert resumed["approval"]["approver_role"] == "Director"
    assert resumed["approval"]["proposal_version"] == payload["proposal_version"]

    history = resumed["recommendation"]["approval_history"]
    assert len(history) == 1
    assert history[0]["action"] == "approve"
    assert history[0]["approver_id"] == "bob"
    assert history[0]["proposal_version"] == payload["proposal_version"]
    assert history[0]["decided_at"]
    assert resumed["recommendation"]["proposal_version"] == payload["proposal_version"]


def test_approval_gate_records_a_rejection_with_identity() -> None:
    workflow, payload, _ = paused_workflow("t-graph-reject")
    identity = ApproverIdentity(approver_id="bob", role=ApproverRole.DIRECTOR)

    resumed = workflow.resume(
        build_resume_payload(
            action=ApprovalAction.REJECT,
            comment="Margin too thin",
            proposal_version=payload["proposal_version"],
            identity=identity,
        ),
        thread_id="t-graph-reject",
    )

    assert resumed["status"] == STATUS_APPROVAL_REJECTED
    assert resumed["approval"]["action"] == "reject"
    assert resumed["approval"]["decided_by"] == "bob"
    assert resumed["recommendation"]["status"] == STATUS_APPROVAL_REJECTED
    assert any("Margin too thin" in error for error in resumed["recommendation"]["errors"])
    assert [entry["action"] for entry in resumed["recommendation"]["approval_history"]] == [
        "reject"
    ]


def test_requesting_modifications_revises_the_plan_and_pauses_again() -> None:
    workflow, payload, _ = paused_workflow("t-graph-modify")
    identity = ApproverIdentity(approver_id="bob", role=ApproverRole.DIRECTOR)

    resumed = workflow.resume(
        build_resume_payload(
            action=ApprovalAction.REQUEST_MODIFICATIONS,
            comment="Prefer the rail alternative",
            proposal_version=payload["proposal_version"],
            identity=identity,
        ),
        thread_id="t-graph-modify",
    )

    assert resumed["status"] == STATUS_AWAITING_APPROVAL
    assert resumed["modification_rounds"] == 1
    revised = pending_interrupt(resumed)
    assert revised is not None
    assert revised["proposal_version"] != payload["proposal_version"]

    history = resumed["approval_history"]
    assert [entry["action"] for entry in history] == ["request_modifications"]
    assert history[0]["approver_id"] == "bob"
    assert history[0]["comment"] == "Prefer the rail alternative"
    assert any(
        "Human review requested modifications" in decision["reason"]
        for decision in resumed["decisions"]
    )


def test_the_modification_loop_is_bounded() -> None:
    workflow, payload, _ = paused_workflow("t-graph-bounded")
    identity = ApproverIdentity(approver_id="bob", role=ApproverRole.DIRECTOR)

    current = payload
    state: Dict[str, Any] = {}
    for round_number in range(1, MAX_MODIFICATION_ROUNDS + 1):
        state = workflow.resume(
            build_resume_payload(
                action=ApprovalAction.REQUEST_MODIFICATIONS,
                comment=f"Try again ({round_number})",
                proposal_version=current["proposal_version"],
                identity=identity,
            ),
            thread_id="t-graph-bounded",
        )
        assert state["status"] == STATUS_AWAITING_APPROVAL
        current = pending_interrupt(state)
        assert current is not None

    # One request beyond the bound is refused and closes the workflow.
    closed = workflow.resume(
        build_resume_payload(
            action=ApprovalAction.REQUEST_MODIFICATIONS,
            comment="One more time",
            proposal_version=current["proposal_version"],
            identity=identity,
        ),
        thread_id="t-graph-bounded",
    )

    assert closed["status"] == STATUS_APPROVAL_REJECTED
    assert pending_interrupt(closed) is None
    assert any("reconsideration round" in error for error in closed["errors"])
    history = closed["recommendation"]["approval_history"]
    assert len(history) == MAX_MODIFICATION_ROUNDS + 1
    assert {entry["action"] for entry in history} == {"request_modifications"}


# ---------------------------------------------------------------------------
# Execution plan and service
# ---------------------------------------------------------------------------


def test_execution_plan_is_ordered_and_keyed_for_idempotency() -> None:
    proposal = make_proposal()
    actions = build_execution_plan(proposal)

    assert [action.action_type for action in actions] == [
        ExecutionActionType.SHIPMENT_PLAN_UPDATE,
        ExecutionActionType.INVENTORY_TRANSFER,
        ExecutionActionType.CARRIER_CHANGE,
        ExecutionActionType.SAP_EXECUTION,
    ]
    expected_prefix = f"{proposal.thread_id}:{proposal.proposal_version}:"
    for action in actions:
        assert action.idempotency_key == f"{expected_prefix}{action.action_type.value}"
        assert action.payload["proposal_version"] == proposal.proposal_version


def test_execution_plan_omits_actions_the_proposal_does_not_need() -> None:
    proposal = make_proposal(
        inventory_transfer_units=0.0,
        carrier_change_requested=False,
        supplier_id="",
    )
    actions = build_execution_plan(proposal)
    assert [action.action_type for action in actions] == [
        ExecutionActionType.SHIPMENT_PLAN_UPDATE
    ]


def test_simulated_execution_is_labelled_and_replayed_idempotently() -> None:
    proposal = make_proposal()
    adapter = CountingAdapter()
    store = RecordingExecutionStore()
    service = ExecutionService(adapter=adapter, store=store)

    first = service.execute(proposal)
    assert first.status is ExecutionRunStatus.COMPLETED
    assert first.idempotent_replay is False
    assert first.proposal_version == proposal.proposal_version
    assert len(first.actions) == 4
    for action in first.actions:
        assert action.status is ExecutionActionStatus.EXECUTED
        assert action.is_mock is True
        assert action.external_reference.startswith("SIM-")
        assert "[SIMULATED]" in action.message

    calls_after_first = adapter.calls
    second = service.execute(proposal)

    assert adapter.calls == calls_after_first
    assert second.idempotent_replay is True
    assert second.execution_id == first.execution_id
    assert [action.external_reference for action in second.actions] == [
        action.external_reference for action in first.actions
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"requires_approval": False},
        {"proposal_version": ""},
        {"thread_id": ""},
    ],
)
def test_execution_is_refused_without_an_approval_binding(
    overrides: Dict[str, Any]
) -> None:
    proposal = make_proposal().model_copy(update=overrides)
    service = ExecutionService(adapter=SimulatedExecutionAdapter(), store=RecordingExecutionStore())

    with pytest.raises(ExecutionNotAuthorizedError):
        service.execute(proposal)


def test_partial_execution_is_reported_honestly() -> None:
    store = RecordingExecutionStore()
    service = ExecutionService(adapter=PartialFailureAdapter(), store=store)

    report = service.execute(make_proposal())

    assert report.status is ExecutionRunStatus.PARTIAL
    failed = [
        action
        for action in report.actions
        if action.status is ExecutionActionStatus.FAILED
    ]
    assert [action.action_type for action in failed] == [
        ExecutionActionType.INVENTORY_TRANSFER
    ]
    assert failed[0].message == "The gateway rejected the transfer request."
    assert store.get_execution(report.thread_id, report.proposal_version) is not None


def test_an_adapter_exception_is_recorded_not_swallowed() -> None:
    service = ExecutionService(
        adapter=RaisingAdapter(), store=RecordingExecutionStore()
    )

    report = service.execute(make_proposal())

    assert report.status is ExecutionRunStatus.FAILED
    assert all(
        action.status is ExecutionActionStatus.FAILED for action in report.actions
    )
    assert all("RuntimeError" in action.message for action in report.actions)


def test_live_execution_posts_each_action_with_an_idempotency_key() -> None:
    seen: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"reference": "GW-42"})

    client = HttpJsonClient(
        connector_name="execution",
        base_url="https://gateway.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings = Settings(
        _env_file=None,
        EXECUTION_BASE_URL="https://gateway.test",
        EXECUTION_CLIENT_ID="client-1",
        EXECUTION_CLIENT_SECRET="secret",
    )
    adapter = HttpExecutionAdapter(settings, client=client)
    action = build_execution_plan(make_proposal())[0]

    result = adapter.execute(action)

    assert result.status is ExecutionActionStatus.EXECUTED
    assert result.is_mock is False
    assert result.external_reference == "GW-42"
    assert seen["method"] == "POST"
    assert seen["path"] == "/shipments/plan"
    assert seen["headers"]["idempotency-key"] == action.idempotency_key
    assert seen["headers"]["x-client-id"] == "client-1"
    assert seen["body"]["idempotency_key"] == action.idempotency_key


def test_live_execution_records_a_gateway_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="unknown shipment")

    client = HttpJsonClient(
        connector_name="execution",
        base_url="https://gateway.test",
        max_attempts=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings = Settings(
        _env_file=None,
        EXECUTION_BASE_URL="https://gateway.test",
        EXECUTION_CLIENT_ID="client-1",
        EXECUTION_CLIENT_SECRET="secret",
    )
    adapter = HttpExecutionAdapter(settings, client=client)

    result = adapter.execute(build_execution_plan(make_proposal())[0])

    assert result.status is ExecutionActionStatus.FAILED
    assert result.is_mock is False
    assert "HTTP 400" in result.message


def test_execution_adapter_factory_requires_live_credentials() -> None:
    assert isinstance(
        get_execution_adapter(Settings(_env_file=None, EXECUTION_USE_MOCK=True)),
        SimulatedExecutionAdapter,
    )

    with pytest.raises(IntegrationNotConfiguredError):
        get_execution_adapter(Settings(_env_file=None, EXECUTION_USE_MOCK=False))

    configured = Settings(
        _env_file=None,
        EXECUTION_USE_MOCK=False,
        EXECUTION_BASE_URL="https://gateway.test",
        EXECUTION_CLIENT_ID="client-1",
        EXECUTION_CLIENT_SECRET="secret",
    )
    assert isinstance(get_execution_adapter(configured), HttpExecutionAdapter)


def test_execution_dependency_maps_missing_configuration_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        approvals_api,
        "get_settings",
        lambda: Settings(_env_file=None, EXECUTION_USE_MOCK=False),
    )

    with pytest.raises(HTTPException) as excinfo:
        execution_adapter()

    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# Approval repository semantics
# ---------------------------------------------------------------------------


def test_in_memory_repository_preserves_history_and_binds_execution_to_a_version() -> None:
    repository = InMemoryApprovalRepository()
    first = make_proposal()
    repository.upsert_pending(make_view(first))

    decision = ApprovalDecisionRecord(
        action=ApprovalAction.APPROVE,
        approver_id="bob",
        approver_role="Director",
        comment="Approved",
        proposal_version=first.proposal_version,
    )
    decided = repository.add_decision(
        first.thread_id, decision, ApprovalStatus.APPROVED, workflow_status="completed"
    )
    assert decided.status is ApprovalStatus.APPROVED
    assert len(decided.decision_history) == 1

    # Re-recording the same decided version refreshes the view but never reopens it.
    same_version = repository.upsert_pending(make_view(first))
    assert same_version.status is ApprovalStatus.APPROVED
    assert len(same_version.decision_history) == 1

    report = make_execution_report(first)
    repository.save_execution(first.thread_id, report)
    assert repository.get_execution(first.thread_id, first.proposal_version) == report
    assert repository.get_execution(first.thread_id, "another-version") is None

    revised = make_proposal(total_cost_usd=430_000.0)
    refreshed = repository.upsert_pending(make_view(revised))
    assert refreshed.status is ApprovalStatus.PENDING
    assert refreshed.proposal_version == revised.proposal_version
    assert len(refreshed.decision_history) == 1
    assert refreshed.execution is None
    assert repository.get_execution(first.thread_id, first.proposal_version) is None
    assert [item.thread_id for item in repository.list_pending()] == [first.thread_id]


def test_postgres_repository_round_trips_through_a_database() -> None:
    engine = create_engine("sqlite://")
    ensure_approval_schema(engine)
    ensure_approval_schema(engine)  # idempotent at startup

    with Session(engine) as session:
        repository = PostgresApprovalRepository(session)
        first = make_proposal()
        repository.upsert_pending(make_view(first))

        stored = repository.get(first.thread_id)
        assert stored is not None
        assert stored.proposal_version == first.proposal_version
        assert stored.proposal.proposal_id == first.proposal_id
        assert stored.status is ApprovalStatus.PENDING
        assert [item.thread_id for item in repository.list_pending()] == [first.thread_id]

        decision = ApprovalDecisionRecord(
            action=ApprovalAction.REQUEST_MODIFICATIONS,
            approver_id="bob",
            approver_role="Director",
            comment="Use rail",
            proposal_version=first.proposal_version,
        )
        decided = repository.add_decision(
            first.thread_id,
            decision,
            ApprovalStatus.MODIFICATIONS_REQUESTED,
            workflow_status="running",
        )
        assert len(decided.decision_history) == 1
        assert decided.decision_history[0].comment == "Use rail"

        repository.save_execution(first.thread_id, make_execution_report(first))
        assert repository.get_execution(first.thread_id, first.proposal_version) is not None

        revised = make_proposal(total_cost_usd=430_000.0)
        refreshed = repository.upsert_pending(make_view(revised))
        assert refreshed.status is ApprovalStatus.PENDING
        assert len(refreshed.decision_history) == 1
        assert refreshed.execution is None
        assert repository.get_execution(first.thread_id, first.proposal_version) is None
        assert repository.get(first.thread_id).proposal_version == revised.proposal_version


# ---------------------------------------------------------------------------
# Secured approval API
# ---------------------------------------------------------------------------


def test_approval_endpoints_require_a_bearer_token(api: Any) -> None:
    client, install = api
    install(repository=InMemoryApprovalRepository(), authorizer=_authorizer())

    missing = client.get("/api/approvals/pending")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    wrong = client.get("/api/approvals/pending", headers=_bearer("not-a-token"))
    assert wrong.status_code == 401
    assert "before the first colon" in wrong.json()["detail"]

    scheme = client.get(
        "/api/approvals/pending", headers={"Authorization": "Basic abc"}
    )
    assert scheme.status_code == 401


def test_approval_api_fails_closed_without_configured_credentials(api: Any) -> None:
    client, install = api
    install(repository=InMemoryApprovalRepository(), authorizer=_authorizer(" "))

    response = client.get("/api/approvals/pending", headers=_bearer("anything"))

    assert response.status_code == 503
    assert "APPROVER_CREDENTIALS" in response.json()["detail"]


def test_pending_queue_returns_the_reviewed_proposal(api: Any) -> None:
    client, install = api
    repository = InMemoryApprovalRepository()
    proposal = make_proposal(thread_id="t-pending")
    repository.upsert_pending(make_view(proposal))
    install(repository=repository, authorizer=_authorizer())

    response = client.get("/api/approvals/pending", headers=_bearer(MANAGER_TOKEN))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["pending"][0]["thread_id"] == "t-pending"
    assert body["pending"][0]["proposal_version"] == proposal.proposal_version
    assert body["pending"][0]["proposal"]["headline"] == proposal.headline


def test_approval_decision_resumes_executes_and_prevents_duplicates(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, install = api
    repository = InMemoryApprovalRepository()
    workflow, payload, _ = paused_workflow("t-api-approve")
    install(
        repository=repository,
        authorizer=_authorizer(),
        execution=SimulatedExecutionAdapter(),
        workflow=workflow,
        monkeypatch=monkeypatch,
    )

    body = {
        "action": "approve",
        "comment": "Approved by the director",
        "proposal_version": payload["proposal_version"],
    }
    response = client.post(
        "/api/approvals/t-api-approve/decision",
        json=body,
        headers=_bearer(DIRECTOR_TOKEN),
    )
    assert response.status_code == 200, response.text
    outcome = response.json()

    assert outcome["workflow_status"] == STATUS_COMPLETED
    assert outcome["approval_status"] == "approved"
    assert outcome["awaiting_approval"] is False
    assert outcome["decision"]["approver_id"] == "bob"
    assert outcome["decision"]["approver_role"] == "Director"
    assert outcome["decision"]["comment"] == "Approved by the director"
    assert outcome["decision"]["proposal_version"] == payload["proposal_version"]
    assert outcome["view"]["status"] == "approved"
    assert len(outcome["view"]["decision_history"]) == 1

    execution = outcome["execution"]
    assert execution["status"] == "completed"
    assert execution["proposal_version"] == payload["proposal_version"]
    assert execution["actions"]
    assert all(action["is_mock"] is True for action in execution["actions"])
    assert all("[SIMULATED]" in action["message"] for action in execution["actions"])
    assert (
        outcome["recommendation"]["approval_history"][0]["approver_id"] == "bob"
    )

    # The workflow is no longer paused, so a replay cannot execute again.
    duplicate = client.post(
        "/api/approvals/t-api-approve/decision",
        json=body,
        headers=_bearer(DIRECTOR_TOKEN),
    )
    assert duplicate.status_code == 409

    report = client.get(
        "/api/approvals/t-api-approve/execution", headers=_bearer(MANAGER_TOKEN)
    )
    assert report.status_code == 200
    assert report.json()["execution_id"] == execution["execution_id"]

    view = client.get("/api/approvals/t-api-approve", headers=_bearer(MANAGER_TOKEN))
    assert view.status_code == 200
    assert view.json()["status"] == "approved"


def test_a_stale_proposal_version_is_rejected(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, install = api
    repository = InMemoryApprovalRepository()
    workflow, _, _ = paused_workflow("t-api-stale")
    install(
        repository=repository,
        authorizer=_authorizer(),
        workflow=workflow,
        monkeypatch=monkeypatch,
    )

    response = client.post(
        "/api/approvals/t-api-stale/decision",
        json={
            "action": "approve",
            "comment": "",
            "proposal_version": "deadbeefdeadbeef",
        },
        headers=_bearer(DIRECTOR_TOKEN),
    )

    assert response.status_code == 409
    assert "version" in response.json()["detail"].lower()


def test_an_insufficient_role_cannot_decide(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, install = api
    workflow, payload, _ = paused_workflow("t-api-role")
    install(
        repository=InMemoryApprovalRepository(),
        authorizer=ApprovalAuthorizer(f"{MANAGER_TOKEN}:alice:Manager"),
        workflow=workflow,
        monkeypatch=monkeypatch,
    )

    response = client.post(
        "/api/approvals/t-api-role/decision",
        json={
            "action": "approve",
            "comment": "",
            "proposal_version": payload["proposal_version"],
        },
        headers=_bearer(MANAGER_TOKEN),
    )

    assert response.status_code == 403
    assert "Manager" in response.json()["detail"]


def test_rejection_closes_the_workflow_without_execution(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, install = api
    repository = InMemoryApprovalRepository()
    workflow, payload, _ = paused_workflow("t-api-reject")
    install(
        repository=repository,
        authorizer=_authorizer(),
        workflow=workflow,
        monkeypatch=monkeypatch,
    )

    response = client.post(
        "/api/approvals/t-api-reject/decision",
        json={
            "action": "reject",
            "comment": "Not acceptable",
            "proposal_version": payload["proposal_version"],
        },
        headers=_bearer(DIRECTOR_TOKEN),
    )
    assert response.status_code == 200, response.text
    outcome = response.json()

    assert outcome["approval_status"] == "rejected"
    assert outcome["workflow_status"] == STATUS_APPROVAL_REJECTED
    assert outcome["execution"] is None
    assert any("Not acceptable" in error for error in outcome["errors"])
    assert outcome["view"]["status"] == "rejected"

    pending = client.get("/api/approvals/pending", headers=_bearer(MANAGER_TOKEN))
    assert pending.json()["count"] == 0


def test_modification_request_creates_a_new_pending_version(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, install = api
    repository = InMemoryApprovalRepository()
    workflow, payload, _ = paused_workflow("t-api-modify")
    install(
        repository=repository,
        authorizer=_authorizer(),
        execution=SimulatedExecutionAdapter(),
        workflow=workflow,
        monkeypatch=monkeypatch,
    )

    first = client.post(
        "/api/approvals/t-api-modify/decision",
        json={
            "action": "request_modifications",
            "comment": "Prefer the rail alternative",
            "proposal_version": payload["proposal_version"],
        },
        headers=_bearer(DIRECTOR_TOKEN),
    )
    assert first.status_code == 200, first.text
    outcome = first.json()

    assert outcome["awaiting_approval"] is True
    assert outcome["approval_status"] == "pending"
    assert outcome["proposal_version"] != payload["proposal_version"]
    assert outcome["view"]["status"] == "pending"
    assert len(outcome["view"]["decision_history"]) == 1
    assert outcome["view"]["decision_history"][0]["action"] == "request_modifications"
    assert outcome["decision"]["approver_id"] == "bob"

    # The revised proposal can then be approved and executed.
    second = client.post(
        "/api/approvals/t-api-modify/decision",
        json={
            "action": "approve",
            "comment": "Revised proposal accepted",
            "proposal_version": outcome["proposal_version"],
        },
        headers=_bearer(DIRECTOR_TOKEN),
    )
    assert second.status_code == 200, second.text
    approved = second.json()

    assert approved["approval_status"] == "approved"
    assert approved["workflow_status"] == STATUS_COMPLETED
    assert approved["execution"]["proposal_version"] == outcome["proposal_version"]
    assert len(approved["view"]["decision_history"]) == 2
    assert approved["view"]["decision_history"][0]["action"] == "request_modifications"
    assert approved["view"]["decision_history"][1]["action"] == "approve"
