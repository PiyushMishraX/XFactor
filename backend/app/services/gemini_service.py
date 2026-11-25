"""Thin, dependency-light client for the Google Gemini REST API (Step 1).

Responsibilities are deliberately narrow: send a prompt, ask for JSON shaped by a
response schema, return the parsed dict. It knows nothing about supply chains and
contains no business rules.

The client never fabricates a result. When no API key is configured it raises
:class:`GeminiNotConfiguredError` so callers fail loudly instead of silently
falling back to mock reasoning.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

import httpx

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: HTTP statuses worth retrying: rate limits and transient upstream capacity.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3


class _KeyThrottle:
    """Enforce a minimum gap between requests that share one API key.

    State is process-wide and keyed by a SHA-256 fingerprint, so two agents
    holding the same key also space their calls. ``clock``/``sleeper`` are class
    attributes so tests can replace them deterministically.
    """

    clock = staticmethod(time.monotonic)
    sleeper = staticmethod(time.sleep)
    _guard = threading.Lock()
    _locks: Dict[str, threading.Lock] = {}
    _last_call: Dict[str, float] = {}

    @classmethod
    def _lock_for(cls, fingerprint: str) -> threading.Lock:
        with cls._guard:
            return cls._locks.setdefault(fingerprint, threading.Lock())

    @classmethod
    def wait(cls, fingerprint: str, min_interval: float) -> None:
        if min_interval <= 0:
            return
        lock = cls._lock_for(fingerprint)
        with lock:
            now = cls.clock()
            remaining = min_interval - (now - cls._last_call.get(fingerprint, 0.0))
            if remaining > 0:
                logger.debug(
                    "Pacing Gemini request on key %s for %.1fs.", fingerprint, remaining
                )
                cls.sleeper(remaining)
                now = cls.clock()
            cls._last_call[fingerprint] = now


def _key_fingerprint(api_key: str) -> str:
    """Short, non-reversible identifier for logs and pacing state."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


class GeminiError(RuntimeError):
    """Base class for all Gemini failures."""


class GeminiNotConfiguredError(GeminiError):
    """Raised when ``GEMINI_API_KEY`` is missing."""


class GeminiRequestError(GeminiError):
    """Raised when Gemini is unreachable, rejects the request or returns junk."""


class GeminiQuotaExceededError(GeminiRequestError):
    """Raised when a key has no quota left for the window Google reports.

    Carries the quota identifiers so the workflow and dashboard can explain the
    limit honestly instead of implying the request shape was wrong.
    """

    def __init__(
        self,
        message: str,
        *,
        quota_id: str = "",
        model: str = "",
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.quota_id = quota_id
        self.model = model
        self.retry_after_seconds = retry_after_seconds


def _format_retry_hint(retry_after: Optional[float]) -> str:
    if retry_after is None:
        return "Google did not say when the quota resets."
    reset_at = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
    hours = retry_after / 3600.0
    return (
        f"Quota resets in {hours:.1f} h (around {reset_at.strftime('%Y-%m-%d %H:%M UTC')})."
    )


def parse_quota_failure(response: httpx.Response) -> Optional[Tuple[str, str, Optional[float]]]:
    """Extract ``(quota_id, model, retry_after)`` from a quota 429 body.

    Returns ``None`` for 429s that are not quota failures (for example a
    per-minute throttle without quota details), which stay retryable.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") or {}
    quota_id = ""
    model = ""
    retry_after: Optional[float] = None
    for detail in error.get("details") or []:
        kind = str(detail.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            for violation in detail.get("violations") or []:
                quota_id = violation.get("quotaId") or quota_id
                dimensions = violation.get("quotaDimensions") or {}
                model = dimensions.get("model") or model
        elif kind.endswith("RetryInfo"):
            raw = str(detail.get("retryDelay", "")).strip()
            if raw.endswith("s"):
                try:
                    retry_after = float(raw[:-1])
                except ValueError:
                    pass
    if error.get("status") == "RESOURCE_EXHAUSTED" or quota_id:
        return quota_id, model, retry_after
    return None


class _KeyCooldown:
    """Remember exhausted keys so later calls skip them immediately.

    State is process-wide and keyed by the SHA-256 fingerprint. ``clock`` is a
    class attribute so tests can advance time without sleeping.
    """

    clock = staticmethod(time.time)
    _guard = threading.Lock()
    _until: Dict[str, float] = {}

    @classmethod
    def block(cls, fingerprint: str, seconds: float) -> None:
        available_at = cls.clock() + max(seconds, 0.0)
        with cls._guard:
            previous = cls._until.get(fingerprint, 0.0)
            cls._until[fingerprint] = max(previous, available_at)

    @classmethod
    def remaining(cls, fingerprint: str) -> float:
        with cls._guard:
            return max(0.0, cls._until.get(fingerprint, 0.0) - cls.clock())

    @classmethod
    def clear(cls) -> None:
        with cls._guard:
            cls._until.clear()


class GeminiService:
    """Minimal Gemini ``generateContent`` wrapper with structured JSON output."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.Client] = None,
        *,
        api_key: Optional[str] = None,
        agent_name: Optional[str] = None,
        min_interval_seconds: Optional[float] = None,
        fallback_keys: Optional[Sequence[str]] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._api_key = (api_key or "").strip() or None
        self._agent_name = agent_name
        self._min_interval = min_interval_seconds
        self._fallback_keys = tuple(
            key.strip() for key in (fallback_keys or ()) if key and key.strip()
        )

    # -- public API ------------------------------------------------------

    def generate_structured_json(
        self,
        *,
        prompt: str,
        response_schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        thinking_budget: int = 0,
    ) -> Dict[str, Any]:
        """Run one structured generation and return the parsed JSON object.

        Args:
            prompt: The user-turn text.
            response_schema: OpenAPI-subset schema for the expected JSON object.
            system_instruction: Optional system-turn instructions.
            temperature: Sampling temperature; 0.0 keeps analysis repeatable.
            thinking_budget: Reasoning token budget. 0 disables thinking, which
                is appropriate for extraction/classification tasks.

        Raises:
            GeminiNotConfiguredError: No API key is configured.
            GeminiRequestError: The API failed or returned unusable output.
        """
        settings = self._settings
        candidate_keys = self._candidate_keys()
        if not candidate_keys:
            raise GeminiNotConfiguredError(
                "No Gemini API key is configured, so the agent cannot perform LLM "
                "reasoning. Set GEMINI_API_KEY and/or GEMINI_API_KEYS in backend/.env "
                "(see backend/.env.example) and restart the service. No mock "
                "reasoning fallback is applied."
            )
        if self._agent_name:
            logger.debug(
                "Gemini call for agent %s starting on key %s (%s candidate(s)).",
                self._agent_name,
                _key_fingerprint(candidate_keys[0]),
                len(candidate_keys),
            )

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": settings.GEMINI_MAX_OUTPUT_TOKENS,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
                "thinkingConfig": {"thinkingBudget": thinking_budget},
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        response = self._post(payload=payload)
        return self._extract_json(response)

    def close(self) -> None:
        """Close the underlying HTTP client if this service created it."""
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "GeminiService":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- internals -------------------------------------------------------

    def _resolve_api_key(self) -> str:
        """An explicitly assigned key wins; otherwise the process key."""
        return (self._api_key or self._settings.GEMINI_API_KEY).strip()

    def _candidate_keys(self) -> Tuple[str, ...]:
        """Keys to try in order: assigned key first, then fallbacks, then config."""
        ordered: list[str] = []
        primary = self._resolve_api_key()
        if primary:
            ordered.append(primary)
        for key in (*self._fallback_keys, *self._settings.gemini_api_keys):
            if key and key not in ordered:
                ordered.append(key)
        return tuple(ordered)

    def _wait_for_slot(self, api_key: str) -> None:
        interval = (
            self._min_interval
            if self._min_interval is not None
            else self._settings.GEMINI_MIN_INTERVAL_SECONDS
        )
        _KeyThrottle.wait(_key_fingerprint(api_key), float(interval))

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._settings.GEMINI_TIMEOUT_SECONDS)
        return self._client

    def _post(self, *, payload: Dict[str, Any]) -> httpx.Response:
        """POST, rotating across keys when one has no quota left.

        A key that reports a long quota reset is quarantined for the rest of the
        process so later agents skip it immediately. Other failures keep the
        previous retry behaviour and are not hidden by rotation.
        """
        candidates = self._candidate_keys()
        if not candidates:
            raise GeminiNotConfiguredError(
                "No Gemini API key is configured, so the agent cannot perform LLM "
                "reasoning. Set GEMINI_API_KEY and/or GEMINI_API_KEYS in backend/.env."
            )

        last_quota: Optional[GeminiQuotaExceededError] = None
        earliest_reset: Optional[float] = None
        for api_key in candidates:
            fingerprint = _key_fingerprint(api_key)
            cooling = _KeyCooldown.remaining(fingerprint)
            if cooling > 0:
                earliest_reset = (
                    cooling if earliest_reset is None else min(earliest_reset, cooling)
                )
                logger.warning(
                    "Skipping Gemini key %s: quota cooldown %.0f s remaining.",
                    fingerprint,
                    cooling,
                )
                continue
            try:
                return self._post_one(api_key, payload)
            except GeminiQuotaExceededError as exc:
                last_quota = exc
                logger.warning(
                    "Gemini key %s has no quota left (%s); trying the next key.",
                    fingerprint,
                    exc.quota_id or "quota",
                )

        if last_quota is not None:
            raise last_quota
        raise GeminiQuotaExceededError(
            "Every configured Gemini key is cooling down after a quota error. "
            + _format_retry_hint(earliest_reset),
            retry_after_seconds=earliest_reset,
        )

    def _post_one(self, api_key: str, payload: Dict[str, Any]) -> httpx.Response:
        """Send one request on one key, retrying only recoverable failures."""
        url = (
            f"{self._settings.GEMINI_API_BASE.rstrip('/')}"
            f"/models/{self._settings.GEMINI_MODEL}:generateContent"
        )
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

        last_error: Optional[GeminiRequestError] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._wait_for_slot(api_key)
            try:
                response = self._http_client().post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = GeminiRequestError(f"Could not reach the Gemini API: {exc}")
            else:
                if response.status_code == 200:
                    return response
                detail = _truncate(response.text)
                if response.status_code == 429:
                    quota = parse_quota_failure(response)
                    if quota is not None:
                        quota_id, model, retry_after = quota
                        honor_limit = self._settings.GEMINI_QUOTA_RETRY_MAX_SECONDS
                        if (
                            retry_after is not None
                            and 0 < retry_after <= honor_limit
                            and attempt < _MAX_ATTEMPTS
                        ):
                            logger.warning(
                                "Gemini quota window is short (%.0f s); waiting as advised.",
                                retry_after,
                            )
                            time.sleep(retry_after)
                            continue
                        cooldown = retry_after if retry_after and retry_after > 0 else 60.0
                        _KeyCooldown.block(_key_fingerprint(api_key), cooldown)
                        raise GeminiQuotaExceededError(
                            "Gemini quota exhausted for model "
                            f"'{model or self._settings.GEMINI_MODEL}' "
                            f"({quota_id or 'quota'}). {_format_retry_hint(retry_after)} "
                            "Add another key to GEMINI_API_KEYS or enable billing for "
                            f"the project. Upstream: {detail}",
                            quota_id=quota_id,
                            model=model,
                            retry_after_seconds=retry_after,
                        )
                last_error = GeminiRequestError(
                    f"Gemini API returned HTTP {response.status_code}: {detail}"
                )
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise last_error

            if attempt < _MAX_ATTEMPTS:
                delay = self._settings.GEMINI_RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "Gemini request failed (attempt %s/%s); retrying in %.1fs",
                    attempt,
                    _MAX_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)

        assert last_error is not None  # loop always sets it before exiting
        raise last_error

    @staticmethod
    def _extract_json(response: httpx.Response) -> Dict[str, Any]:
        """Pull the generated JSON object out of a ``generateContent`` response."""
        try:
            body = response.json()
        except ValueError as exc:
            raise GeminiRequestError(f"Gemini returned a non-JSON envelope: {exc}") from exc

        candidates = body.get("candidates") or []
        if not candidates:
            feedback = body.get("promptFeedback") or {}
            reason = feedback.get("blockReason", "no candidates returned")
            raise GeminiRequestError(f"Gemini produced no output (reason: {reason}).")

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            finish_reason = candidate.get("finishReason", "unknown")
            raise GeminiRequestError(
                f"Gemini returned an empty response (finishReason: {finish_reason})."
            )

        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise GeminiRequestError(
                f"Gemini returned output that is not valid JSON: {exc}. "
                f"Raw output started with: {_truncate(text, 200)}"
            ) from exc

        if not isinstance(parsed, dict):
            raise GeminiRequestError(
                f"Expected a JSON object from Gemini but received {type(parsed).__name__}."
            )
        return parsed


def _truncate(text: str, limit: int = 400) -> str:
    """Keep error messages readable without dumping an entire response body."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[:limit]}..."
