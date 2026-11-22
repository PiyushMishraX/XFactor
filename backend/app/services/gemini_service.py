"""Thin, dependency-light client for the Google Gemini REST API (Step 1).

Responsibilities are deliberately narrow: send a prompt, ask for JSON shaped by a
response schema, return the parsed dict. It knows nothing about supply chains and
contains no business rules.

The client never fabricates a result. When no API key is configured it raises
:class:`GeminiNotConfiguredError` so callers fail loudly instead of silently
falling back to mock reasoning.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: HTTP statuses worth retrying: rate limits and transient upstream capacity.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 2.0


class GeminiError(RuntimeError):
    """Base class for all Gemini failures."""


class GeminiNotConfiguredError(GeminiError):
    """Raised when ``GEMINI_API_KEY`` is missing."""


class GeminiRequestError(GeminiError):
    """Raised when Gemini is unreachable, rejects the request or returns junk."""


class GeminiService:
    """Minimal Gemini ``generateContent`` wrapper with structured JSON output."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

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
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            raise GeminiNotConfiguredError(
                "GEMINI_API_KEY is not configured, so the Disruption Sensing Agent "
                "cannot perform LLM reasoning. Set GEMINI_API_KEY in backend/.env "
                "(see backend/.env.example) and restart the service. No mock "
                "reasoning fallback is applied."
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

        response = self._post(api_key=api_key, payload=payload)
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

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._settings.GEMINI_TIMEOUT_SECONDS)
        return self._client

    def _post(self, *, api_key: str, payload: Dict[str, Any]) -> httpx.Response:
        """POST to ``generateContent``, retrying transient upstream failures."""
        url = (
            f"{self._settings.GEMINI_API_BASE.rstrip('/')}"
            f"/models/{self._settings.GEMINI_MODEL}:generateContent"
        )
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

        last_error: Optional[GeminiRequestError] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._http_client().post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = GeminiRequestError(f"Could not reach the Gemini API: {exc}")
            else:
                if response.status_code == 200:
                    return response
                detail = _truncate(response.text)
                last_error = GeminiRequestError(
                    f"Gemini API returned HTTP {response.status_code}: {detail}"
                )
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise last_error

            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_SECONDS * attempt
                logger.warning(
                    "Gemini request failed (attempt %s/%s); retrying in %.0fs",
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
