"""Quota-aware Gemini behaviour: rotate keys, quarantine exhausted ones.

Google's free-tier failure is a *daily* request cap (``RESOURCE_EXHAUSTED`` with
``quotaValue: 20`` and a multi-hour ``retryDelay``). These tests pin the
behaviour that fixes it: no pointless in-process retries, rotate to another key,
and remember which key is out of quota.
"""

from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.config.settings import Settings
from app.orchestration.workflow import _NON_RETRYABLE_ERRORS, build_agents
from app.services.gemini_service import (
    GeminiQuotaExceededError,
    GeminiRequestError,
    GeminiService,
    _KeyCooldown,
    _KeyThrottle,
    _key_fingerprint,
)

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}

DAILY_QUOTA_ID = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


def _settings(**overrides: object) -> Settings:
    defaults: Dict[str, Any] = {
        "GEMINI_MIN_INTERVAL_SECONDS": 0.0,
        "GEMINI_RETRY_BACKOFF_SECONDS": 0.0,
        "GEMINI_QUOTA_RETRY_MAX_SECONDS": 120.0,
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def _envelope() -> Dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}


def _quota_response(
    *,
    retry_delay: str | None = "51075s",
    quota_id: str = DAILY_QUOTA_ID,
    model: str = "gemini-3.6-flash",
) -> httpx.Response:
    details: List[Dict[str, Any]] = [
        {
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [
                {"quotaId": quota_id, "quotaDimensions": {"model": model}}
            ],
        }
    ]
    if retry_delay is not None:
        details.append(
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": retry_delay,
            }
        )
    return httpx.Response(
        429,
        json={
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded",
                "details": details,
            }
        },
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clean_gemini_state() -> None:
    _KeyThrottle._last_call.clear()
    _KeyCooldown.clear()
    yield
    _KeyThrottle._last_call.clear()
    _KeyCooldown.clear()


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    recorded: List[float] = []
    monkeypatch.setattr(
        "app.services.gemini_service.time.sleep", lambda seconds: recorded.append(seconds)
    )
    return recorded


# -- daily quota is terminal, not retried ------------------------------------


def test_daily_quota_failure_is_not_retried_in_process(sleeps: List[float]) -> None:
    calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        return _quota_response()

    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="only-key"), client=_client(handler)
    )

    with pytest.raises(GeminiQuotaExceededError) as excinfo:
        service.generate_structured_json(prompt="x", response_schema=SCHEMA)

    error = excinfo.value
    assert calls == ["only-key"]
    assert sleeps == []
    assert error.quota_id == DAILY_QUOTA_ID
    assert error.model == "gemini-3.6-flash"
    assert error.retry_after_seconds == 51075.0
    message = str(error)
    assert "14.2 h" in message
    assert "GEMINI_API_KEYS" in message
    assert _KeyCooldown.remaining(_key_fingerprint("only-key")) > 0


def test_quota_without_retry_info_is_quarantined_for_a_minute(
    sleeps: List[float],
) -> None:
    calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        return _quota_response(retry_delay=None)

    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="only-key"), client=_client(handler)
    )

    with pytest.raises(GeminiQuotaExceededError):
        service.generate_structured_json(prompt="x", response_schema=SCHEMA)

    assert calls == ["only-key"]
    assert sleeps == []
    remaining = _KeyCooldown.remaining(_key_fingerprint("only-key"))
    assert 55.0 < remaining <= 60.0


# -- rotation ----------------------------------------------------------------


def test_exhausted_primary_rotates_to_the_fallback_key(sleeps: List[float]) -> None:
    calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["x-goog-api-key"]
        calls.append(key)
        if key == "key-one":
            return _quota_response(retry_delay="3600s")
        return httpx.Response(200, json=_envelope())

    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="key-one", GEMINI_API_KEYS="key-two"),
        client=_client(handler),
        api_key="key-one",
        fallback_keys=("key-two",),
    )

    assert service.generate_structured_json(prompt="x", response_schema=SCHEMA) == {
        "ok": True
    }
    assert calls == ["key-one", "key-two"]
    assert sleeps == []
    assert _KeyCooldown.remaining(_key_fingerprint("key-one")) > 0

    # The exhausted key is now skipped immediately, without another request.
    assert service.generate_structured_json(prompt="x", response_schema=SCHEMA) == {
        "ok": True
    }
    assert calls == ["key-one", "key-two", "key-two"]


def test_all_keys_cooling_fails_without_any_http_call() -> None:
    calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        return httpx.Response(200, json=_envelope())

    _KeyCooldown.block(_key_fingerprint("key-one"), 3600)
    _KeyCooldown.block(_key_fingerprint("key-two"), 3600)

    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="key-one", GEMINI_API_KEYS="key-two"),
        client=_client(handler),
        api_key="key-one",
        fallback_keys=("key-two",),
    )

    with pytest.raises(GeminiQuotaExceededError) as excinfo:
        service.generate_structured_json(prompt="x", response_schema=SCHEMA)

    assert calls == []
    assert "cooling down" in str(excinfo.value)
    assert "UTC" in str(excinfo.value)
    assert excinfo.value.retry_after_seconds is not None


# -- short throttle windows --------------------------------------------------


def test_short_quota_retry_delay_is_honoured(sleeps: List[float]) -> None:
    calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        if len(calls) == 1:
            return _quota_response(retry_delay="30s", quota_id="PerMinute")
        return httpx.Response(200, json=_envelope())

    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="only-key"), client=_client(handler)
    )

    assert service.generate_structured_json(prompt="x", response_schema=SCHEMA) == {
        "ok": True
    }
    assert calls == ["only-key", "only-key"]
    assert sleeps == [pytest.approx(30.0)]
    assert _KeyCooldown.remaining(_key_fingerprint("only-key")) == 0


def test_non_quota_429_keeps_the_retry_behaviour(sleeps: List[float]) -> None:
    calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="only-key"), client=_client(handler)
    )

    with pytest.raises(GeminiRequestError) as excinfo:
        service.generate_structured_json(prompt="x", response_schema=SCHEMA)

    assert not isinstance(excinfo.value, GeminiQuotaExceededError)
    assert len(calls) == 3
    assert len(sleeps) == 2


# -- wiring and workflow policy ----------------------------------------------


def test_each_agent_falls_back_to_the_other_keys_in_rotation() -> None:
    settings = _settings(GEMINI_API_KEY="key-one", GEMINI_API_KEYS="key-two")
    agents = build_agents(
        repository=object(),
        sap=object(),
        mapping=object(),
        carriers=object(),
        settings=settings,
    )

    assert agents.sensing._gemini._candidate_keys() == ("key-one", "key-two")
    assert agents.scenario._gemini._candidate_keys() == ("key-two", "key-one")
    assert agents.compliance._gemini._candidate_keys() == ("key-one", "key-two")


def test_quota_exhaustion_is_not_retried_by_the_supervisor() -> None:
    error = GeminiQuotaExceededError("daily quota exhausted")
    assert isinstance(error, _NON_RETRYABLE_ERRORS)
