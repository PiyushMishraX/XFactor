"""Environment-based SAP authentication (Step 7).

SAP tenants normally authenticate with OAuth2 client credentials. The connector
therefore requests a token from ``SAP_AUTH_URL`` and sends it as a bearer token.
When no token endpoint is configured it falls back to the gateway ``x-api-key``
convention already used by the Step 2 connectors.

Security properties
-------------------
* Credentials come only from environment variables; nothing is hard-coded.
* Tokens are cached in memory until shortly before they expire, so a page of
  reads does not trigger a token request each time.
* The read and write permissions request **different scopes**
  (``SAP_READ_SCOPE`` / ``SAP_WRITE_SCOPE``), so a write-capable token is never
  issued to a read-only code path.
* Tokens and secrets are never logged, and :func:`redact_headers` masks
  credential-bearing headers if a caller ever needs to log a request.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Mapping, Optional

import httpx

from app.integrations.base import (
    RETRYABLE_STATUS_CODES,
    HttpJsonClient,
    IntegrationNotConfiguredError,
    IntegrationRequestError,
)
from app.config.settings import Settings

logger = logging.getLogger(__name__)

#: Refresh the token this many seconds before the provider says it expires.
_TOKEN_REFRESH_MARGIN_SECONDS = 30.0

#: Default lifetime when a token response omits ``expires_in``.
_DEFAULT_TOKEN_LIFETIME_SECONDS = 300.0

#: Headers that must be masked before any diagnostic logging.
_SECRET_HEADERS = frozenset({"authorization", "x-api-key", "cookie", "set-cookie"})


def redact_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """Return a copy of ``headers`` with credential-bearing values masked."""
    return {
        name: "***" if name.lower() in _SECRET_HEADERS else value
        for name, value in headers.items()
    }


class SAPOAuthTokenProvider:
    """OAuth2 client-credentials token source with an in-memory cache."""

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str,
        timeout: float = 10.0,
        max_attempts: int = 2,
        backoff_seconds: float = 0.5,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._token_url = (token_url or "").strip()
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._scope = (scope or "").strip()
        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)
        self._backoff_seconds = backoff_seconds
        self._client = client
        self._token: str = ""
        self._expires_at: float = 0.0

    @property
    def scope(self) -> str:
        return self._scope

    def access_token(self) -> str:
        """Return a cached bearer token, fetching a new one when needed.

        Raises:
            IntegrationNotConfiguredError: The token endpoint or client
                credentials are not configured.
            IntegrationRequestError: The token endpoint failed or returned no
                usable ``access_token``.
        """
        if not (self._token_url and self._client_id and self._client_secret):
            raise IntegrationNotConfiguredError(
                "SAP OAuth requires SAP_AUTH_URL, SAP_CLIENT_ID and SAP_CLIENT_SECRET."
            )
        if self._token and time.monotonic() < self._expires_at:
            return self._token

        token, expires_in = self._fetch_token()
        self._token = token
        lifetime = max(0.0, expires_in - _TOKEN_REFRESH_MARGIN_SECONDS)
        self._expires_at = time.monotonic() + lifetime
        logger.info(
            "SAP OAuth token acquired (scope=%r, expires_in=%ss).", self._scope, int(expires_in)
        )
        return self._token

    def invalidate(self) -> None:
        """Drop the cached token (used after an authentication failure)."""
        self._token = ""
        self._expires_at = 0.0

    def _fetch_token(self) -> "tuple[str, float]":
        form = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scope:
            form["scope"] = self._scope

        last_error: Optional[str] = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._post(form)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    # Never echo the response body: token endpoints may reflect
                    # request parameters, which include the client secret.
                    raise IntegrationRequestError(
                        "SAP token endpoint rejected the client credentials "
                        f"(HTTP {response.status_code}).",
                        status_code=response.status_code,
                    )
                else:
                    return self._parse_token(response)

            logger.warning(
                "SAP token request failed (attempt %s/%s): %s",
                attempt,
                self._max_attempts,
                last_error,
            )
            if attempt < self._max_attempts:
                time.sleep(self._backoff_seconds * attempt)

        raise IntegrationRequestError(
            f"SAP token request failed after {self._max_attempts} attempts. "
            f"Last error: {last_error}"
        )

    def _post(self, form: Mapping[str, str]) -> httpx.Response:
        if self._client is not None:
            return self._client.post(
                self._token_url,
                data=dict(form),
                headers={"Accept": "application/json"},
                timeout=self._timeout,
            )
        with httpx.Client(timeout=self._timeout) as client:
            return client.post(
                self._token_url,
                data=dict(form),
                headers={"Accept": "application/json"},
            )

    @staticmethod
    def _parse_token(response: httpx.Response) -> "tuple[str, float]":
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationRequestError(
                "SAP token endpoint returned a non-JSON body."
            ) from exc
        token = str((payload or {}).get("access_token") or "").strip()
        if not token:
            raise IntegrationRequestError(
                "SAP token endpoint returned no access_token."
            )
        try:
            expires_in = float((payload or {}).get("expires_in") or _DEFAULT_TOKEN_LIFETIME_SECONDS)
        except (TypeError, ValueError):
            expires_in = _DEFAULT_TOKEN_LIFETIME_SECONDS
        return token, max(0.0, expires_in)


class SAPHttpClient(HttpJsonClient):
    """JSON client that authenticates every request with a cached OAuth token."""

    def __init__(self, *, tokens: SAPOAuthTokenProvider, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._tokens = tokens

    def _headers(self) -> Dict[str, str]:
        headers = super()._headers()
        headers.pop("x-api-key", None)
        headers["Authorization"] = f"Bearer {self._tokens.access_token()}"
        return headers

    def get_json(self, path: str, **kwargs: object):  # type: ignore[override]
        payload = super().get_json(path, **kwargs)  # type: ignore[arg-type]
        logger.info("SAP read %s succeeded.", path)
        return payload

    def post_json(
        self,
        path: str,
        *,
        payload: Mapping[str, object],
        idempotency_key: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
    ):
        response = super().post_json(
            path, payload=payload, idempotency_key=idempotency_key, headers=headers
        )
        logger.info("SAP write %s succeeded.", path)
        return response


__all__ = [
    "SAPHttpClient",
    "SAPOAuthTokenProvider",
    "redact_headers",
    "sap_token_provider",
]


def sap_token_provider(
    settings: Settings, *, scope: str
) -> Optional[SAPOAuthTokenProvider]:
    """Build a token provider for ``scope`` when OAuth is configured, else None.

    Returning ``None`` tells the caller to use the gateway ``x-api-key``
    convention instead. The scope is passed explicitly so the read connector can
    never request write access and vice versa.
    """
    if not settings.sap_oauth_configured:
        return None
    return SAPOAuthTokenProvider(
        token_url=settings.SAP_AUTH_URL,
        client_id=settings.SAP_CLIENT_ID,
        client_secret=settings.SAP_CLIENT_SECRET,
        scope=scope,
        timeout=float(settings.INTEGRATION_TIMEOUT_SECONDS),
        max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
    )
