"""Tests for the Step 0 application skeleton and health endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_service_metadata():
    response = client.get("/")
    assert response.status_code == 200

    body = response.json()
    assert body["service"] == "X FACTOR"
    assert body["docs"] == "/docs"
    assert body["health"].endswith("/health")


def test_health_endpoint_returns_status_payload():
    response = client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    # The database may be unavailable in a test environment; the API must still
    # answer and report its status honestly.
    assert body["status"] in {"ok", "degraded"}
    assert body["database"] in {"connected", "unavailable"}
    assert body["service"] == "X FACTOR"
    assert "timestamp" in body


def test_liveness_probe_does_not_require_dependencies():
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_404():
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
