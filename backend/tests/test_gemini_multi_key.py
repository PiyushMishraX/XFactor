"""Multi-key assignment and per-key pacing for the Gemini client."""

from __future__ import annotations

import httpx
import pytest

from app.config.settings import Settings
from app.orchestration.workflow import build_agents
from app.services.gemini_keys import (
    AGENT_ORDER,
    parse_key_slots,
    resolve_agent_keys,
)
from app.services.gemini_service import (
    GeminiNotConfiguredError,
    GeminiService,
    _KeyThrottle,
)

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def _client(captured: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers["x-goog-api-key"])
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok": true}'}]}}
                ]
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clean_throttle() -> None:
    _KeyThrottle._last_call.clear()
    yield
    _KeyThrottle._last_call.clear()


# -- assignment --------------------------------------------------------------


def test_two_keys_are_distributed_round_robin() -> None:
    keys = resolve_agent_keys(
        _settings(GEMINI_API_KEY="key-one", GEMINI_API_KEYS="key-two")
    )
    assert keys == {
        "disruption_sensing": "key-one",
        "scenario_planning": "key-two",
        "rerouting_logistics": "key-one",
        "inventory_rebalancing": "key-two",
        "compliance_audit": "key-one",
    }


def test_duplicate_key_is_collapsed() -> None:
    settings = _settings(GEMINI_API_KEY="key-one", GEMINI_API_KEYS="key-one,key-two")
    assert settings.gemini_api_keys == ("key-one", "key-two")
    assert resolve_agent_keys(settings)["scenario_planning"] == "key-two"


def test_slots_override_assignment() -> None:
    keys = resolve_agent_keys(
        _settings(
            GEMINI_API_KEY="key-one",
            GEMINI_API_KEYS="key-two",
            GEMINI_KEY_SLOTS="disruption_sensing=1,scenario_planning=0",
        )
    )
    assert keys["disruption_sensing"] == "key-two"
    assert keys["scenario_planning"] == "key-one"
    # Unlisted agents keep the round-robin defaults.
    assert keys["rerouting_logistics"] == "key-one"


def test_slot_beyond_configured_keys_is_rejected() -> None:
    with pytest.raises(ValueError, match="only 2 key"):
        resolve_agent_keys(
            _settings(
                GEMINI_API_KEY="key-one",
                GEMINI_API_KEYS="key-two",
                GEMINI_KEY_SLOTS="compliance_audit=5",
            )
        )


def test_unknown_agent_and_malformed_entries_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        parse_key_slots("audit_agent=0")
    with pytest.raises(ValueError, match="expected 'agent=index'"):
        parse_key_slots("disruption_sensing")
    with pytest.raises(ValueError, match="zero-based integer"):
        parse_key_slots("disruption_sensing=first")


def test_no_keys_resolves_to_empty_mapping() -> None:
    assert resolve_agent_keys(_settings()) == {}


# -- wiring ------------------------------------------------------------------


def test_each_agent_is_wired_to_its_assigned_key() -> None:
    settings = _settings(
        GEMINI_API_KEY="key-one",
        GEMINI_API_KEYS="key-two",
        GEMINI_MIN_INTERVAL_SECONDS=0,
    )
    agents = build_agents(
        repository=object(),
        sap=object(),
        mapping=object(),
        carriers=object(),
        settings=settings,
    )
    wired = {
        "disruption_sensing": agents.sensing._gemini._api_key,
        "scenario_planning": agents.scenario._gemini._api_key,
        "rerouting_logistics": agents.rerouting._gemini._api_key,
        "inventory_rebalancing": agents.rebalancing._gemini._api_key,
        "compliance_audit": agents.compliance._gemini._api_key,
    }
    assert wired == {
        "disruption_sensing": "key-one",
        "scenario_planning": "key-two",
        "rerouting_logistics": "key-one",
        "inventory_rebalancing": "key-two",
        "compliance_audit": "key-one",
    }
    assert set(wired) == set(AGENT_ORDER)


def test_shared_service_is_kept_when_explicitly_supplied() -> None:
    shared = GeminiService(settings=_settings(GEMINI_API_KEY="key-one"), api_key="key-one")
    agents = build_agents(
        gemini=shared,
        repository=object(),
        sap=object(),
        mapping=object(),
        carriers=object(),
    )
    assert agents.sensing._gemini is shared
    assert agents.compliance._gemini is shared


# -- request key -------------------------------------------------------------


def test_assigned_key_is_sent_in_the_request() -> None:
    captured: list[str] = []
    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="process-key", GEMINI_MIN_INTERVAL_SECONDS=0),
        client=_client(captured),
        api_key="assigned-key",
    )
    service.generate_structured_json(prompt="x", response_schema=SCHEMA)
    assert captured == ["assigned-key"]


def test_process_key_is_used_when_no_assignment_exists() -> None:
    captured: list[str] = []
    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="process-key", GEMINI_MIN_INTERVAL_SECONDS=0),
        client=_client(captured),
    )
    service.generate_structured_json(prompt="x", response_schema=SCHEMA)
    assert captured == ["process-key"]


def test_missing_key_fails_loudly_and_names_both_variables() -> None:
    service = GeminiService(
        settings=_settings(GEMINI_MIN_INTERVAL_SECONDS=0), client=_client([])
    )
    with pytest.raises(GeminiNotConfiguredError, match="GEMINI_API_KEYS"):
        service.generate_structured_json(prompt="x", response_schema=SCHEMA)


# -- pacing ------------------------------------------------------------------


def test_throttle_spaces_repeated_calls_on_one_key(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([100.0, 100.0, 101.0])
    slept: list[float] = []
    monkeypatch.setattr(_KeyThrottle, "clock", staticmethod(lambda: next(ticks)))
    monkeypatch.setattr(
        _KeyThrottle, "sleeper", staticmethod(lambda seconds: slept.append(seconds))
    )

    _KeyThrottle.wait("fp-a", 5.0)
    _KeyThrottle.wait("fp-a", 5.0)

    assert slept == [pytest.approx(5.0)]


def test_throttle_is_disabled_at_zero_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        _KeyThrottle, "sleeper", staticmethod(lambda seconds: slept.append(seconds))
    )
    _KeyThrottle.wait("fp-a", 0.0)
    _KeyThrottle.wait("fp-a", 0.0)
    assert slept == []


def test_service_waits_before_each_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GeminiService(
        settings=_settings(GEMINI_API_KEY="key-one", GEMINI_MIN_INTERVAL_SECONDS=0),
        client=_client([]),
    )
    waits: list[str] = []
    monkeypatch.setattr(service, "_wait_for_slot", lambda api_key: waits.append(api_key))

    service.generate_structured_json(prompt="x", response_schema=SCHEMA)
    assert waits == ["key-one"]
