"""Tests for the Gemini REST client's contract and failure behaviour.

Uses ``httpx.MockTransport`` so no network call is made and the exact request
payload can be asserted.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import httpx
import pytest

from app.config.settings import Settings
from app.services.gemini_service import (
    GeminiNotConfiguredError,
    GeminiRequestError,
    GeminiService,
)

SIMPLE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def settings_with_key(key: str = "test-key") -> Settings:
    return Settings(GEMINI_API_KEY=key, GEMINI_MODEL="gemini-3.5-flash")


def envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a payload the way ``generateContent`` does."""
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


def build_service(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    key: str = "test-key",
) -> GeminiService:
    return GeminiService(
        settings=settings_with_key(key),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_missing_api_key_raises_an_actionable_configuration_error() -> None:
    service = build_service(lambda request: httpx.Response(200), key="")

    with pytest.raises(GeminiNotConfiguredError) as excinfo:
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    message = str(excinfo.value)
    assert "GEMINI_API_KEY" in message
    assert "backend/.env" in message
    assert "No mock reasoning fallback" in message


def test_successful_call_returns_the_parsed_object_and_sends_the_schema() -> None:
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=envelope({"answer": "42"}))

    service = build_service(handler)
    result = service.generate_structured_json(
        prompt="What is the answer?",
        response_schema=SIMPLE_SCHEMA,
        system_instruction="Be terse.",
    )

    assert result == {"answer": "42"}
    request = captured[0]
    assert request.url.path.endswith("/models/gemini-3.5-flash:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"

    body = json.loads(request.content)
    assert body["generationConfig"]["responseSchema"] == SIMPLE_SCHEMA
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0.0
    assert body["systemInstruction"]["parts"][0]["text"] == "Be terse."
    assert body["contents"][0]["parts"][0]["text"] == "What is the answer?"


def test_client_error_is_not_retried() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400, json={"error": {"message": "bad schema"}})

    service = build_service(handler)
    with pytest.raises(GeminiRequestError) as excinfo:
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert calls["count"] == 1
    assert "HTTP 400" in str(excinfo.value)
    assert "bad schema" in str(excinfo.value)


def test_transient_upstream_failure_is_retried_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, json=envelope({"answer": "recovered"}))

    service = build_service(handler)
    result = service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert result == {"answer": "recovered"}
    assert calls["count"] == 2


def test_persistent_transient_failure_raises_after_retries(monkeypatch) -> None:
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, json={"error": {"message": "high demand"}})

    service = build_service(handler)
    with pytest.raises(GeminiRequestError):
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert calls["count"] == 3


def test_network_failure_is_reported_as_a_request_error(monkeypatch) -> None:
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda _seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    service = build_service(handler)
    with pytest.raises(GeminiRequestError) as excinfo:
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert "Could not reach the Gemini API" in str(excinfo.value)


def test_non_json_model_output_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]},
        )

    service = build_service(handler)
    with pytest.raises(GeminiRequestError) as excinfo:
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert "not valid JSON" in str(excinfo.value)


def test_blocked_prompt_is_reported_with_its_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    service = build_service(handler)
    with pytest.raises(GeminiRequestError) as excinfo:
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert "SAFETY" in str(excinfo.value)


def test_truncated_output_reports_the_finish_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]},
        )

    service = build_service(handler)
    with pytest.raises(GeminiRequestError) as excinfo:
        service.generate_structured_json(prompt="hello", response_schema=SIMPLE_SCHEMA)

    assert "MAX_TOKENS" in str(excinfo.value)
