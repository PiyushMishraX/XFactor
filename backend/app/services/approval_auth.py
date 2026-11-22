"""Approver authentication and authorisation (Step 6).

The approval API must never trust a status submitted by an unauthenticated
frontend. This module is the single gate:

* :class:`ApprovalAuthorizer` maps a bearer token to an :class:`ApproverIdentity`
  using credentials supplied only through ``APPROVER_CREDENTIALS``.
* Tokens are compared with :func:`secrets.compare_digest`, so a wrong token does
  not leak its prefix through timing.
* :meth:`ApprovalAuthorizer.authorize` enforces the role hierarchy: a Manager can
  decide Manager-level proposals, a Director can decide Director-level ones, and
  an Admin can decide any level.

There is no default credential and no anonymous fallback. When the variable is
not configured the API fails loudly with a 503 rather than silently letting
unauthenticated callers through.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.config.settings import Settings, get_settings
from app.schemas.approval_schemas import ApproverIdentity, ApproverRole


class ApprovalConfigurationError(RuntimeError):
    """No approver credentials, or malformed credentials, are configured."""


class ApproverAuthenticationError(RuntimeError):
    """The presented token is missing or does not match any approver."""


class ApproverAuthorizationError(RuntimeError):
    """The authenticated approver's role is below the required level."""


@dataclass(frozen=True)
class _Credential:
    token: str
    identity: ApproverIdentity


def parse_credentials(raw: str) -> List[_Credential]:
    """Parse ``token:approver_id:Role`` entries separated by commas.

    Raises:
        ApprovalConfigurationError: An entry is malformed, has an unknown role,
            or repeats a token.
    """
    entries: List[_Credential] = []
    seen_tokens: set[str] = set()
    for position, chunk in enumerate(raw.split(","), start=1):
        entry = chunk.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            raise ApprovalConfigurationError(
                f"APPROVER_CREDENTIALS entry {position} must be "
                f"'token:approver_id:Role'; tokens may not contain ':'."
            )
        token, approver_id, role_text = (part.strip() for part in parts)
        if not token or not approver_id:
            raise ApprovalConfigurationError(
                f"APPROVER_CREDENTIALS entry {position} has an empty token or approver id."
            )
        try:
            role = ApproverRole(role_text.title())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in ApproverRole)
            raise ApprovalConfigurationError(
                f"APPROVER_CREDENTIALS entry {position} has unknown role {role_text!r}; "
                f"use one of {allowed}."
            ) from exc
        if token in seen_tokens:
            raise ApprovalConfigurationError(
                f"APPROVER_CREDENTIALS entry {position} repeats a token; every approver "
                f"needs a distinct token."
            )
        seen_tokens.add(token)
        entries.append(
            _Credential(
                token=token,
                identity=ApproverIdentity(approver_id=approver_id, role=role),
            )
        )
    if not entries:
        raise ApprovalConfigurationError(
            "No approver credentials are configured. Set APPROVER_CREDENTIALS to a "
            "comma-separated list of 'token:approver_id:Role' entries before using the "
            "approval API."
        )
    return entries


class ApprovalAuthorizer:
    """Authenticate bearer tokens and enforce the approver role hierarchy."""

    def __init__(self, credentials: str = "", *, settings: Optional[Settings] = None) -> None:
        self._raw = (
            credentials if credentials else (settings or get_settings()).APPROVER_CREDENTIALS
        )

    @property
    def configured(self) -> bool:
        return bool(self._raw.strip())

    def authenticate(self, token: Optional[str]) -> ApproverIdentity:
        """Return the approver behind ``token``.

        Raises:
            ApprovalConfigurationError: No credentials are configured.
            ApproverAuthenticationError: The token is missing or unknown.
        """
        entries = parse_credentials(self._raw)
        candidate = (token or "").strip()
        if not candidate:
            raise ApproverAuthenticationError("A bearer token is required.")

        matched: Optional[ApproverIdentity] = None
        # Compare against every entry so a match position is not observable.
        for entry in entries:
            if secrets.compare_digest(candidate, entry.token):
                matched = entry.identity
        if matched is None:
            raise ApproverAuthenticationError("The bearer token is not recognised.")
        return matched

    def authorize(self, identity: ApproverIdentity, approval_level: Optional[str]) -> None:
        """Raise when ``identity`` may not decide at ``approval_level``."""
        if not identity.can_approve(approval_level):
            required = (approval_level or "").strip() or "the required"
            raise ApproverAuthorizationError(
                f"{identity.role.value} '{identity.approver_id}' may not decide a "
                f"{required}-level proposal."
            )


def extract_bearer_token(authorization: Optional[str]) -> str:
    """Return the token from an ``Authorization: Bearer <token>`` header."""
    value = (authorization or "").strip()
    if not value:
        raise ApproverAuthenticationError("The Authorization header is missing.")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApproverAuthenticationError(
            "Use an 'Authorization: Bearer <token>' header."
        )
    return token.strip()


def identity_summary(identity: ApproverIdentity) -> Tuple[str, str]:
    """A display-safe ``(id, role)`` pair for logs and audit rows."""
    return identity.approver_id, identity.role.value


__all__ = [
    "ApprovalAuthorizer",
    "ApprovalConfigurationError",
    "ApproverAuthenticationError",
    "ApproverAuthorizationError",
    "extract_bearer_token",
    "identity_summary",
    "parse_credentials",
]
