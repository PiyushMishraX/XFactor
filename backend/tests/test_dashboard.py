"""Step 8 tests: workflow history and control-tower read API.

The dashboard must show what actually happened. These tests use a real workflow
state produced by the supervisor's own scripted agents, then verify that:

* history rows are summaries of that state, not fabricated activity;
* a second record updates the same run instead of duplicating it;
* the read API serves overview, runs, disruptions, shipments and inventory;
* a missing run is a real 404 and an unavailable database is a 503;
* simulated SAP inventory stays labelled as simulated.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.orchestration as orchestration_api
from app.api.dashboard import sap_connector
from app.database.base import Base
from app.database.session import get_db
from app.integrations.sap import SimulatedSAPConnector
from app.main import app
from app.models.supply_chain import Shipment, Supplier
from app.models.workflow_runs import WorkflowRunRow
from app.services.workflow_history import (
    ensure_workflow_run_schema,
    get_workflow_run,
    json_safe,
    list_disruptions,
    list_workflow_runs,
    record_workflow_run,
)
from tests.test_orchestration import build_workflow, make_request


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Supplier.__table__, Shipment.__table__])
    ensure_workflow_run_schema(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture(scope="module")
def completed_state() -> Dict[str, Any]:
    workflow = build_workflow()
    state = workflow.invoke(make_request(), thread_id="t-dashboard")
    return json.loads(json.dumps(state))


def _seed_shipments(session: Session) -> None:
    session.add(
        Supplier(
            id="SUP001",
            name="Aurora Pharma Ingredients",
            country="India",
            category="Pharmaceutical API",
            risk_tier="Medium",
        )
    )
    session.add(
        Shipment(
            id="SH001",
            origin="Mumbai",
            destination="Rotterdam",
            route="Mumbai -> Rotterdam via Suez Canal, Red Sea",
            transport_mode="Sea",
            carrier="Maersk",
            status="In Transit",
            cargo="Pharmaceutical API",
            value_usd=1_250_000,
            supplier_id="SUP001",
        )
    )
    session.commit()


def _client(session: Session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[sap_connector] = lambda: SimulatedSAPConnector()
    return TestClient(app)


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    client = _client(session)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(sap_connector, None)


def test_recorded_run_summarises_the_real_workflow_state(
    session: Session, completed_state: Dict[str, Any]
) -> None:
    summary = record_workflow_run(session, "t-dashboard", completed_state)

    assert summary is not None
    stored = get_workflow_run(session, "t-dashboard")
    assert stored["status"] == completed_state["status"]
    assert stored["event_id"] == "EV-ORCH-1"
    assert stored["disruption_type"] == "Port Congestion"
    assert stored["origin"] == "Mumbai"
    assert stored["destination"] == "Rotterdam"
    assert stored["severity"]
    assert stored["risk_score"] is not None
    assert stored["execution_count"] == len(completed_state["agent_executions"])
    assert stored["state"]["recommendation"]["headline"]
    assert stored["state"]["scenario_plan"]["scenarios"]


def test_recording_twice_updates_one_row_and_keeps_created_at(
    session: Session, completed_state: Dict[str, Any]
) -> None:
    first = record_workflow_run(session, "t-update", completed_state)
    assert first is not None
    created = session.get(WorkflowRunRow, "t-update").created_at

    changed = {**completed_state, "status": "failed", "errors": ["simulated failure"]}
    record_workflow_run(session, "t-update", changed)

    runs = list_workflow_runs(session)
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_count"] == 1
    assert session.get(WorkflowRunRow, "t-update").created_at == created


def test_listing_runs_orders_newest_first_and_filters_status(
    session: Session, completed_state: Dict[str, Any]
) -> None:
    record_workflow_run(session, "t-a", completed_state)
    record_workflow_run(session, "t-b", {**completed_state, "status": "awaiting_approval"})

    runs = list_workflow_runs(session)
    assert {run["thread_id"] for run in runs} == {"t-a", "t-b"}

    pending = list_workflow_runs(session, status="awaiting_approval")
    assert [run["thread_id"] for run in pending] == ["t-b"]


def test_disruptions_include_assessment_and_supervisor_decision(
    session: Session, completed_state: Dict[str, Any]
) -> None:
    record_workflow_run(session, "t-disruption", completed_state)
    items = list_disruptions(session)

    assert len(items) == 1
    item = items[0]
    assert item["event_id"] == "EV-ORCH-1"
    assert item["reported_headline"]
    assert item["affected_shipments"] == completed_state["assessment"]["affected_shipments"]
    assert item["supervisor_decision"]["action"]
    assert item["risk_breakdown"] == completed_state["assessment"]["risk_breakdown"]


def test_json_safe_drops_langgraph_interrupt_and_unknown_objects() -> None:
    payload = json_safe(
        {
            "status": "completed",
            "__interrupt__": [object()],
            "nested": {"__private__": object(), "value": (1, 2)},
        }
    )
    assert payload == {"status": "completed", "nested": {"value": [1, 2]}}
    json.dumps(payload)


def test_overview_serves_real_counts_and_latest_runs(
    client: TestClient, session: Session, completed_state: Dict[str, Any]
) -> None:
    _seed_shipments(session)
    record_workflow_run(session, "t-overview", completed_state)

    response = client.get("/api/dashboard/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["runs"] == 1
    assert body["counts"]["shipments"] == 1
    assert body["counts"]["suppliers"] == 1
    assert body["counts"]["agent_executions"] == len(completed_state["agent_executions"])
    assert body["latest_runs"][0]["thread_id"] == "t-overview"


def test_runs_and_detail_endpoints(
    client: TestClient, session: Session, completed_state: Dict[str, Any]
) -> None:
    record_workflow_run(session, "t-api", completed_state)

    listing = client.get("/api/dashboard/runs?limit=5")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["runs"][0]["thread_id"] == "t-api"
    assert "state" not in listing.json()["runs"][0]

    detail = client.get("/api/dashboard/runs/t-api")
    assert detail.status_code == 200
    assert detail.json()["state"]["decisions"]
    assert detail.json()["state"]["agent_executions"]

    missing = client.get("/api/dashboard/runs/does-not-exist")
    assert missing.status_code == 404


def test_disruptions_endpoint(
    client: TestClient, session: Session, completed_state: Dict[str, Any]
) -> None:
    record_workflow_run(session, "t-disruption-api", completed_state)
    response = client.get("/api/dashboard/disruptions")
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["disruptions"][0]["event_id"] == "EV-ORCH-1"


def test_shipments_endpoint_returns_supplier_joined_rows(
    client: TestClient, session: Session
) -> None:
    _seed_shipments(session)
    response = client.get("/api/dashboard/shipments")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    shipment = body["shipments"][0]
    assert shipment["id"] == "SH001"
    assert shipment["supplier"]["name"] == "Aurora Pharma Ingredients"
    assert shipment["value_usd"] == 1_250_000.0


def test_inventory_endpoint_is_labelled_simulated(client: TestClient) -> None:
    response = client.get("/api/dashboard/inventory")
    assert response.status_code == 200
    body = response.json()
    assert body["is_mock"] is True
    assert "[SIMULATED]" in body["source"]
    assert body["count"] > 0
    assert body["material_count"] > 0
    assert all(item["provenance"]["is_mock"] for item in body["items"])


def test_starting_a_workflow_records_the_run(
    session: Session,
    completed_state: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWorkflow:
        def invoke(self, request: Any, *, thread_id: str) -> Dict[str, Any]:
            return completed_state

    @contextlib.contextmanager
    def fake_runtime(**_: Any):
        yield FakeWorkflow()

    monkeypatch.setattr(orchestration_api, "supervisor_runtime", fake_runtime)
    client = _client(session)
    try:
        response = client.post(
            "/api/orchestration/workflows",
            json={"request": make_request().model_dump(mode="json"), "thread_id": "t-http"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["thread_id"] == "t-http"

        run = client.get("/api/dashboard/runs/t-http")
        assert run.status_code == 200
        assert run.json()["status"] == completed_state["status"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(sap_connector, None)


def test_dashboard_routes_are_mounted() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/api/dashboard/overview",
        "/api/dashboard/runs",
        "/api/dashboard/runs/{thread_id}",
        "/api/dashboard/disruptions",
        "/api/dashboard/shipments",
        "/api/dashboard/inventory",
    ):
        assert path in paths
