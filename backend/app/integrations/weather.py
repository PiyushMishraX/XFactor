"""Weather API connector (Step 2).

Returns severe-weather alerts for a location. The live variant calls a
configured HTTP JSON provider; when no provider is configured the factory
returns :class:`SimulatedWeatherConnector`, whose records are clearly marked
``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/alerts?location=<name>`` returning a JSON
  array of objects with the fields mapped in :meth:`LiveWeatherConnector.get_alerts`.
* Sample data covers the demo lanes used by the hackathon dataset. For other
  locations the sample is derived deterministically from the location name via
  :func:`stable_seed` — never randomly.
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


class WeatherSeverity(str, Enum):
    """Alert severity, ordered from least to most disruptive."""

    ADVISORY = "Advisory"
    WATCH = "Watch"
    WARNING = "Warning"
    SEVERE = "Severe"


class WeatherAlert(BaseModel):
    """A single severe-weather alert for a location."""

    location: str
    event_type: str
    headline: str
    severity: WeatherSeverity
    effective_from: str
    expires_at: str
    wind_speed_kmh: Optional[float] = None
    precipitation_mm: Optional[float] = None
    provenance: Provenance


class WeatherConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_alerts(self, *, location: str) -> List[WeatherAlert]:
        """Return active alerts for ``location`` (empty when there are none)."""
        ...


# Sample alerts for the demo lanes. Keys are lower-cased location names.
_SAMPLE_ALERTS: Mapping[str, Sequence[Dict[str, Any]]] = {
    "red sea": (
        {
            "event_type": "High winds",
            "headline": "Gale-force winds forecast across the southern Red Sea",
            "severity": WeatherSeverity.SEVERE,
            "wind_speed_kmh": 78.0,
            "precipitation_mm": 4.0,
            "duration_hours": 36,
        },
    ),
    "shanghai": (
        {
            "event_type": "Typhoon",
            "headline": "Typhoon warning issued for the Yangtze river delta",
            "severity": WeatherSeverity.SEVERE,
            "wind_speed_kmh": 140.0,
            "precipitation_mm": 180.0,
            "duration_hours": 48,
        },
    ),
    "mumbai": (
        {
            "event_type": "Monsoon downpour",
            "headline": "Heavy monsoon rain expected over Konkan coast",
            "severity": WeatherSeverity.WARNING,
            "wind_speed_kmh": 45.0,
            "precipitation_mm": 120.0,
            "duration_hours": 24,
        },
    ),
    "rotterdam": (),
    "suez canal": (),
}

_SEVERITY_CYCLE: Sequence[WeatherSeverity] = (
    WeatherSeverity.ADVISORY,
    WeatherSeverity.WATCH,
    WeatherSeverity.WARNING,
    WeatherSeverity.SEVERE,
)


class SimulatedWeatherConnector(MockConnector):
    """Clearly labelled sample weather feed (no live provider configured)."""

    name = "weather"
    provider = "X FACTOR simulated weather feed"

    def get_alerts(self, *, location: str) -> List[WeatherAlert]:
        key = (location or "").strip().lower()
        if not key:
            raise ValueError("location must be a non-empty string")

        provenance = self.provenance(endpoint="simulated://weather/alerts")
        templates = _SAMPLE_ALERTS.get(key)
        if templates is None:
            templates = self._generated_template(key)

        now = utc_now()
        alerts: List[WeatherAlert] = []
        for template in templates:
            duration = int(template.get("duration_hours", 12))
            alerts.append(
                WeatherAlert(
                    location=location,
                    event_type=str(template["event_type"]),
                    headline=str(template["headline"]),
                    severity=WeatherSeverity(template["severity"]),
                    effective_from=now.isoformat(),
                    expires_at=(now + timedelta(hours=duration)).isoformat(),
                    wind_speed_kmh=template.get("wind_speed_kmh"),
                    precipitation_mm=template.get("precipitation_mm"),
                    provenance=provenance,
                )
            )
        return alerts

    @staticmethod
    def _generated_template(location_key: str) -> Sequence[Dict[str, Any]]:
        """Deterministic sample alert for an unknown location.

        The location hashes to a severity band; a few names are calm by design so
        that "no alerts" remains a realistic outcome in tests.
        """
        seed = stable_seed("weather", location_key)
        if seed % 3 == 0:
            return ()
        severity = _SEVERITY_CYCLE[seed % len(_SEVERITY_CYCLE)]
        return (
            {
                "event_type": "Regional weather advisory",
                "headline": f"Simulated regional weather advisory for {location_key.title()}",
                "severity": severity,
                "wind_speed_kmh": float(20 + seed % 90),
                "precipitation_mm": float(seed % 60),
                "duration_hours": 12 + seed % 36,
            },
        )


class LiveWeatherConnector(HttpConnector):
    """Live weather provider adapter (requires WEATHER_API_BASE_URL)."""

    name = "weather"
    provider = "Live weather API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.WEATHER_API_BASE_URL,
                api_key=settings.WEATHER_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_alerts(self, *, location: str) -> List[WeatherAlert]:
        payload = self.client.get_json("/alerts", params={"location": location})
        records = payload.get("alerts", []) if isinstance(payload, dict) else payload
        provenance = self.provenance(endpoint=f"{self.client.base_url}/alerts")
        return [_map_alert(record, location, provenance) for record in records]


def _map_alert(record: Mapping[str, Any], location: str, provenance: Provenance) -> WeatherAlert:
    """Map one provider record onto the platform's own model."""
    return WeatherAlert(
        location=str(record.get("location") or location),
        event_type=str(record.get("event") or record.get("event_type") or "Weather alert"),
        headline=str(record.get("headline") or record.get("description") or "Weather alert"),
        severity=_coerce_severity(record.get("severity")),
        effective_from=str(record.get("effective_from") or record.get("onset") or utc_now().isoformat()),
        expires_at=str(record.get("expires_at") or record.get("expires") or utc_now().isoformat()),
        wind_speed_kmh=_optional_float(record.get("wind_speed_kmh")),
        precipitation_mm=_optional_float(record.get("precipitation_mm")),
        provenance=provenance,
    )


def _coerce_severity(value: Any) -> WeatherSeverity:
    text = str(value or "").strip().lower()
    for severity in WeatherSeverity:
        if severity.value.lower() == text or severity.name.lower() == text:
            return severity
    return WeatherSeverity.ADVISORY


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_weather_connector(settings: Optional[Settings] = None) -> WeatherConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveWeatherConnector(settings)
    if live.configured:
        return live
    logger.info("Weather API not configured — using clearly labelled simulated feed.")
    return SimulatedWeatherConnector()
