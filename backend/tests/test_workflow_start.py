"""Tests for the one-click Start path and its single-flight admission control.

The overload problem came from repeatable start paths: clicks, extra tabs and the
shipment form could each launch a five-agent supervisor run. These tests prove:

* the guard admits one run and refuses a second with the active thread id;
* both start endpoints return ``409`` while a run is in flight;
* the one-shot endpoint runs the bundled scenario under a fresh event id and
  records the run in history;
* the active endpoint reflects the slot for the UI;
* the demo loader fails honestly when the scenario file is missing.

No real agents or Gemini calls are involved: the supervisor runtime is replaced
with a scripted completed state.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.orchestration as orchestration_api
from app.database.session import get_db
from app.main import app
from app.services.workflow_guard import WorkflowBusyError, WorkflowGuard
from app.services.workflow_history import ensure_workflow_run_schema
from tests.test_orchestration import build_workflow, make_request

_EVENT_ID_PATTERN = re.compile(r"^EV-UI-START-\d{8}-\d{6}-[0-9a-f]{6}$")


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_workflow_run_schema(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture(scope="module")
def completed_state() -> Dict[str, Any]:
    state = build_workflow().invoke(make_request(), thread_id="t-start")
    return state


@pytest.fixture(autouse=True)
def guard(monkeypatch: pytest.MonkeyPatch) -> WorkflowGuard:
    """Give every test a fresh slot so no state leaks between tests."""
    fresh = WorkflowGuard()
    monkeypatch.setattr(orchestration_api, "WORKFLOW_GUARD", fresh)
    return fresh


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def fake_runtime(
    monkeypatch: pytest.MonkeyPatch, completed_state: Dict[str, Any]
) -> None:
    """Replace the supervisor runtime: no agents, no Gemini, no checkpointer."""

    class FakeWorkflow:
        def invoke(self, request: Any, *, thread_id: str) -> Dict[str, Any]:
            return completed_state

    @contextlib.contextmanager
    def runtime(**_: Any):
        yield FakeWorkflow()

    monkeypatch.setattr(orchestration_api, "supervisor_runtime", runtime)


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------


def test_guard_admits_one_run_and_reports_its_thread() -> None:
    guard = WorkflowGuard()
    assert guard.active_thread_id is None

    guard.try_begin("t-one")
    assert guard.active_thread_id == "t-one"

    guard.end()
    assert guard.active_thread_id is None


def test_guard_refuses_a_second_run_and_releases_after_end() -> None:
    guard = WorkflowGuard()
    guard.try_begin("t-first")

    with pytest.raises(WorkflowBusyError) as excinfo:
        guard.try_begin("t-second")
    assert excinfo.value.active_thread_id == "t-first"

    guard.end()
    guard.try_begin("t-second")
    assert guard.active_thread_id == "t-second"
    guard.end()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def test_one_shot_start_runs_once_and_records_the_run(
    client: TestClient, guard: WorkflowGuard, completed_state: Dict[str, Any]
) -> None:
    response = client.post("/api/orchestration/workflows/start")

    assert response.status_code == 200, response.text
    body = response.json()
    thread_id = body["thread_id"]
    assert _EVENT_ID_PATTERN.match(thread_id), thread_id
    assert body["status"] == completed_state["status"]
    assert body["awaiting_approval"] is False
    assert guard.active_thread_id is None

    run = client.get(f"/api/dashboard/runs/{thread_id}")
    assert run.status_code == 200, run.text
    assert run.json()["status"] == completed_state["status"]
    assert run.json()["state"]["decisions"]


def test_one_shot_start_is_refused_while_a_run_is_in_flight(
    client: TestClient, guard: WorkflowGuard
) -> None:
    guard.try_begin("t-held")
    try:
        response = client.post("/api/orchestration/workflows/start")
    finally:
        guard.end()

    assert response.status_code == 409
    assert "Only one run is allowed at a time" in response.json()["detail"]
    assert "t-held" in response.json()["detail"]


def test_workflow_endpoint_shares_the_same_single_flight_slot(
    client: TestClient, guard: WorkflowGuard
) -> None:
    payload = {
        "request": make_request().model_dump(mode="json"),
        "thread_id": "t-http",
    }
    guard.try_begin("t-held")
    try:
        blocked = client.post("/api/orchestration/workflows", json=payload)
    finally:
        guard.end()

    assert blocked.status_code == 409

    allowed = client.post("/api/orchestration/workflows", json=payload)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["thread_id"] == "t-http"
    assert guard.active_thread_id is None


def test_active_endpoint_reflects_the_slot(
    client: TestClient, guard: WorkflowGuard
) -> None:
    assert client.get("/api/orchestration/workflows/active").json() == {
        "running": False,
        "thread_id": None,
    }

    guard.try_begin("t-active")
    try:
        assert client.get("/api/orchestration/workflows/active").json() == {
            "running": True,
            "thread_id": "t-active",
        }
    finally:
        guard.end()

    assert client.get("/api/orchestration/workflows/active").json()["running"] is False


def test_one_shot_invocation_uses_a_fresh_event_id_each_time() -> None:
    first_id, first = orchestration_api._one_shot_invocation()
    second_id, second = orchestration_api._one_shot_invocation()

    assert _EVENT_ID_PATTERN.match(first_id), first_id
    assert _EVENT_ID_PATTERN.match(second_id), second_id
    assert first_id != second_id
    assert first.disruption_report.event_id == first_id
    assert first.scenario_request.event_id == first_id
    assert second.scenario_request.event_id == second_id
    # The bundled scenario is the validated Red Sea run.
    assert first.scenario_request.origin == "Mumbai"
    assert first.scenario_request.destination == "Rotterdam"
    assert first.scenario_request.available_budget_usd == 500_000.0


def test_missing_demo_scenario_fails_honestly(
    client: TestClient,
    guard: WorkflowGuard,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(
        orchestration_api, "DEMO_SCENARIO_PATH", tmp_path / "missing.json"
    )

    response = client.post("/api/orchestration/workflows/start")

    assert response.status_code == 500
    assert "bundled demo scenario is unavailable" in response.json()["detail"]
    assert guard.active_thread_id is None


def test_start_routes_are_mounted() -> None:
    paths = app.openapi()["paths"]
    assert "/api/orchestration/workflows/start" in paths
    assert "/api/orchestration/workflows/active" in paths
