"""Maritime security / navigation alerts connector (Step 2).

Returns advisory-to-severe maritime alerts (piracy, naval exercises, closures)
for a region so the sensing agent can enrich a disruption report. The live
variant calls a configured HTTP JSON provider; when no provider is configured the
factory returns :class:`SimulatedMaritimeConnector`, whose alerts are clearly
marked ``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/alerts?region=<name>`` returning a JSON array
  of alert objects with the fields mapped in
  :meth:`LiveMaritimeConnector.get_alerts`.
* Sample alerts cover the demo regions (Red Sea, Gulf of Aden, Malacca Strait,
  South China Sea). For any other region the sample is derived deterministically
  from the region name via :func:`stable_seed` — never randomly.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpConnector,
    HttpJsonClient,
    MockConnector,
    Provenance,
    stable_seed,
    utc_now,
)

logger = logging.getLogger(__name__)


class MaritimeSeverity(str, Enum):
    """Maritime alert severity, ordered from least to most disruptive."""

    ADVISORY = "Advisory"
    CAUTION = "Caution"
    WARNING = "Warning"
    CRITICAL = "Critical"


class MaritimeAlert(BaseModel):
    """A single maritime security / navigation alert for a region."""

    region: str
    category: str
    headline: str
    severity: MaritimeSeverity
    reported_at: str
    expires_at: str
    source_authority: Optional[str] = None
    provenance: Provenance


class MaritimeAlertConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_alerts(self, *, region: str) -> List[MaritimeAlert]:
        """Return active alerts for ``region`` (empty when there are none)."""
        ...


_SAMPLE_ALERTS: Mapping[str, Sequence[Dict[str, Any]]] = {
    "red sea": (
        {
            "category": "Security",
            "headline": "Elevated threat to shipping transiting Bab-el-Mandeb",
            "severity": MaritimeSeverity.CRITICAL,
            "source_authority": "UKMTO",
            "duration_hours": 72,
        },
        {
            "category": "Navigation",
            "headline": "Convoy escort schedule published for southern Red Sea",
            "severity": MaritimeSeverity.WARNING,
            "source_authority": "Coalition Naval Force",
            "duration_hours": 48,
        },
    ),
    "gulf of aden": (
        {
            "category": "Security",
            "headline": "Attempted boarding reported in the Gulf of Aden",
            "severity": MaritimeSeverity.WARNING,
            "source_authority": "UKMTO",
            "duration_hours": 36,
        },
    ),
    "malacca strait": (
        {
            "category": "Security",
            "headline": "Increased patrols following a rise in petty theft",
            "severity": MaritimeSeverity.CAUTION,
            "source_authority": "ReCAAP ISC",
            "duration_hours": 72,
        },
    ),
    "south china sea": (
        {
            "category": "Navigation",
            "headline": "Naval exercise area announced in the South China Sea",
            "severity": MaritimeSeverity.ADVISORY,
            "source_authority": "Local Maritime Authority",
            "duration_hours": 24,
        },
    ),
    "suez canal": (),
    "rotterdam": (),
}

_SEVERITY_CYCLE: Sequence[MaritimeSeverity] = (
    MaritimeSeverity.ADVISORY,
    MaritimeSeverity.CAUTION,
    MaritimeSeverity.WARNING,
    MaritimeSeverity.CRITICAL,
)


class SimulatedMaritimeConnector(MockConnector):
    """Clearly labelled sample maritime feed (no live provider configured)."""

    name = "maritime_alerts"
    provider = "X FACTOR simulated maritime alerts feed"

    def get_alerts(self, *, region: str) -> List[MaritimeAlert]:
        key = (region or "").strip().lower()
        if not key:
            raise ValueError("region must be a non-empty string")

        provenance = self.provenance(endpoint="simulated://maritime/alerts")
        templates = _SAMPLE_ALERTS.get(key)
        if templates is None:
            templates = self._generated_template(key)

        now = utc_now()
        alerts: List[MaritimeAlert] = []
        for template in templates:
            duration = int(template.get("duration_hours", 24))
            alerts.append(
                MaritimeAlert(
                    region=region,
                    category=str(template["category"]),
                    headline=str(template["headline"]),
                    severity=MaritimeSeverity(template["severity"]),
                    reported_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=duration)).isoformat(),
                    source_authority=template.get("source_authority"),
                    provenance=provenance,
                )
            )
        return alerts

    @staticmethod
    def _generated_template(region_key: str) -> Sequence[Dict[str, Any]]:
        """Deterministic sample alert for an unknown region (some regions calm)."""
        seed = stable_seed("maritime", region_key)
        if seed % 4 == 0:
            return ()
        severity = _SEVERITY_CYCLE[seed % len(_SEVERITY_CYCLE)]
        return (
            {
                "category": "Security",
                "headline": f"Simulated maritime advisory for {region_key.title()}",
                "severity": severity,
                "source_authority": "X FACTOR sample authority",
                "duration_hours": 12 + seed % 48,
            },
        )


class LiveMaritimeConnector(HttpConnector):
    """Live maritime alerts adapter (requires MARITIME_ALERTS_API_BASE_URL)."""

    name = "maritime_alerts"
    provider = "Live maritime alerts API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.MARITIME_ALERTS_API_BASE_URL,
                api_key=settings.MARITIME_ALERTS_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_alerts(self, *, region: str) -> List[MaritimeAlert]:
        payload = self.client.get_json("/alerts", params={"region": region})
        records = payload.get("alerts", []) if isinstance(payload, dict) else payload
        provenance = self.provenance(endpoint=f"{self.client.base_url}/alerts")
        return [_map_alert(record, region, provenance) for record in records]


def _map_alert(record: Mapping[str, Any], region: str, provenance: Provenance) -> MaritimeAlert:
    """Map one provider record onto the platform's own model."""
    return MaritimeAlert(
        region=str(record.get("region") or region),
        category=str(record.get("category") or record.get("type") or "Navigation"),
        headline=str(record.get("headline") or record.get("description") or "Maritime alert"),
        severity=_coerce_severity(record.get("severity")),
        reported_at=str(record.get("reported_at") or record.get("issued") or utc_now().isoformat()),
        expires_at=str(record.get("expires_at") or record.get("expires") or utc_now().isoformat()),
        source_authority=record.get("source_authority") or record.get("authority"),
        provenance=provenance,
    )


def _coerce_severity(value: Any) -> MaritimeSeverity:
    text = str(value or "").strip().lower()
    for severity in MaritimeSeverity:
        if severity.value.lower() == text or severity.name.lower() == text:
            return severity
    return MaritimeSeverity.ADVISORY


def get_maritime_connector(settings: Optional[Settings] = None) -> MaritimeAlertConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveMaritimeConnector(settings)
    if live.configured:
        return live
    logger.info("Maritime alerts API not configured — using clearly labelled simulated feed.")
    return SimulatedMaritimeConnector()
