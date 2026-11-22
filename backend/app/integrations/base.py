"""Shared foundation for the external-data connectors (Step 2).

Every connector in this package follows the same contract so the agents can use
them interchangeably:

* it declares a ``name`` and an ``is_mock`` flag;
* it returns small Pydantic models that each carry a :class:`Provenance` record,
  so a simulated value can never be mistaken for a live one;
* it is configured from environment variables (base URL + API key) plus a
  shared timeout and retry policy;
* the live variant raises :class:`IntegrationNotConfiguredError` instead of
  quietly returning sample data.

Assumptions
-----------
* Managed providers are reached over HTTPS and authenticated with an
  ``x-api-key`` header (the most common shape for the weather / news / maritime /
  congestion / tariff / mapping providers this layer targets).
* Provider payload shapes differ, so each connector maps the raw JSON into its
  own model rather than exposing provider JSON to the rest of the platform.
* All connectors are synchronous: the agents that use them run inside FastAPI
  request handlers and short background jobs, not inside an async event loop.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

#: Status codes worth retrying: rate limiting and transient upstream failures.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IntegrationError(RuntimeError):
    """Base class for every connector failure."""


class IntegrationNotConfiguredError(IntegrationError):
    """The connector needs a base URL or credentials that are not configured."""


class IntegrationRequestError(IntegrationError):
    """The provider was unreachable or returned an unusable response.

    ``status_code`` is the HTTP status when one was received, so callers can
    distinguish a rejected request (4xx) from a transport/upstream failure.
    """

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Timezone-aware current time, so provenance timestamps are unambiguous."""
    return datetime.now(timezone.utc)


def stable_seed(*parts: object) -> int:
    """Deterministic non-negative integer derived from the given parts.

    Simulated adapters use this so that the same query always produces the same
    sample value — tests stay repeatable and nothing looks randomised.
    """
    joined = "|".join(str(part) for part in parts)
    return int(hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8], 16)


class Provenance(BaseModel):
    """Where a piece of external data came from, and whether it is real.

    ``is_mock`` is the single source of truth for "this is simulated data" and
    travels with every record a connector returns.
    """

    model_config = ConfigDict(frozen=True)

    source: str = Field(description="Human-readable provider or feed name.")
    is_mock: bool = Field(description="True when the value is simulated sample data.")
    retrieved_at: datetime = Field(default_factory=utc_now)
    endpoint: Optional[str] = Field(default=None, description="URL or DB table queried.")

    @property
    def label(self) -> str:
        """Display label that makes simulated data obvious in logs and the UI."""
        return f"{self.source} [SIMULATED]" if self.is_mock else self.source


@runtime_checkable
class Connector(Protocol):
    """Minimal contract every external connector satisfies."""

    name: str

    @property
    def is_mock(self) -> bool:
        """True when this connector returns simulated sample data."""
        ...


# ---------------------------------------------------------------------------
# Live transport
# ---------------------------------------------------------------------------


class HttpJsonClient:
    """Small synchronous JSON client with retries, used by live connectors."""

    def __init__(
        self,
        *,
        connector_name: str,
        base_url: str = "",
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._connector_name = connector_name
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = (api_key or "").strip()
        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)
        self._backoff_seconds = backoff_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        """True when a base URL is present, i.e. the live path is usable."""
        return bool(self._base_url)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def get_json(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> Any:
        """GET ``path`` and return the decoded JSON body.

        Raises:
            IntegrationNotConfiguredError: No base URL is configured.
            IntegrationRequestError: The provider failed after every retry, or
                returned a body that is not valid JSON.
        """
        return self._send("GET", path, params=params)

    def post_json(
        self,
        path: str,
        *,
        payload: Mapping[str, Any],
        idempotency_key: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """POST ``payload`` to ``path`` and return the decoded JSON body.

        ``idempotency_key`` is sent as the standard ``Idempotency-Key`` header so
        a retried operational action is not executed twice by the target system.
        """
        extra = dict(headers or {})
        if idempotency_key:
            extra["Idempotency-Key"] = idempotency_key
        return self._send("POST", path, json_body=dict(payload), headers=extra)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        if not self.configured:
            raise IntegrationNotConfiguredError(
                f"The {self._connector_name} connector has no base URL configured. "
                f"Set the matching *_API_BASE_URL environment variable, or use the "
                f"simulated connector explicitly."
            )

        url = f"{self._base_url}/{path.lstrip('/')}"
        last_error: Optional[str] = None

        for attempt in range(1, self._max_attempts + 1):
            retry_after: Optional[float] = None
            try:
                response = self._request(
                    url, params, method=method, json_body=json_body, headers=headers
                )
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "%s request to %s failed (attempt %s/%s): %s",
                    self._connector_name,
                    url,
                    attempt,
                    self._max_attempts,
                    last_error,
                )
            else:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP {response.status_code}: {_truncate(response.text)}"
                    retry_after = _retry_after_seconds(response)
                    logger.warning(
                        "%s returned a retryable status (attempt %s/%s): %s",
                        self._connector_name,
                        attempt,
                        self._max_attempts,
                        last_error,
                    )
                elif response.status_code >= 400:
                    raise IntegrationRequestError(
                        f"{self._connector_name} returned HTTP {response.status_code} for "
                        f"{url}: {_truncate(response.text)}",
                        status_code=response.status_code,
                    )
                else:
                    return self._decode(response, url)

            if attempt < self._max_attempts:
                time.sleep(
                    retry_after if retry_after is not None else self._backoff_seconds * attempt
                )

        raise IntegrationRequestError(
            f"{self._connector_name} failed after {self._max_attempts} attempts for {url}. "
            f"Last error: {last_error}"
        )

    def _request(
        self,
        url: str,
        params: Optional[Mapping[str, Any]],
        *,
        method: str = "GET",
        json_body: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        merged = self._headers()
        merged.update(dict(headers or {}))
        if json_body is not None:
            merged.setdefault("Content-Type", "application/json")
        if self._client is not None:
            return self._client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=merged,
                timeout=self._timeout,
            )
        with httpx.Client(timeout=self._timeout) as client:
            return client.request(
                method, url, params=params, json=json_body, headers=merged
            )

    def _decode(self, response: httpx.Response, url: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationRequestError(
                f"{self._connector_name} returned a non-JSON body for {url}: "
                f"{_truncate(response.text)}"
            ) from exc


def _truncate(text: str, limit: int = 300) -> str:
    """Keep error messages readable when a provider returns a large body."""
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[:limit]}..."


#: A hostile or mistaken ``Retry-After`` must never stall the process for long.
MAX_RETRY_AFTER_SECONDS = 30.0


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Parse a numeric ``Retry-After`` header, clamped to a safe maximum.

    HTTP-date values are not parsed; the caller then falls back to the normal
    back-off. Returning ``None`` means "no usable hint".
    """
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


# ---------------------------------------------------------------------------
# Connector base classes
# ---------------------------------------------------------------------------


class BaseConnector:
    """Common identity + provenance for connectors."""

    #: Short machine name, e.g. ``"weather"``.
    name: str = "connector"
    #: Human-readable provider name used in provenance records.
    provider: str = "Unknown provider"
    #: Overridden to True by simulated adapters.
    is_mock: bool = False

    def provenance(self, *, endpoint: Optional[str] = None) -> Provenance:
        """Build a provenance record stamped with this connector's identity."""
        return Provenance(source=self.provider, is_mock=self.is_mock, endpoint=endpoint)


class MockConnector(BaseConnector):
    """Base class for connectors that return clearly labelled sample data."""

    is_mock = True

    def __init__(self, *, provider: Optional[str] = None) -> None:
        if provider:
            self.provider = provider


class HttpConnector(BaseConnector):
    """Base class for connectors backed by a live HTTP JSON provider."""

    is_mock = False

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    @property
    def configured(self) -> bool:
        return self._client.configured

    @property
    def client(self) -> HttpJsonClient:
        return self._client
