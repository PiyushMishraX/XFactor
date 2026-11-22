"""Port congestion connector (Step 2).

Returns the current congestion picture for a named port so the agents can expect
berthing delays. The live variant calls a configured HTTP JSON provider; when no
provider is configured the factory returns :class:`SimulatedPortCongestionConnector`,
whose records are clearly marked ``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/congestion?port=<name>`` returning a single
  JSON object (or a one-element array) with the fields mapped in
  :meth:`LivePortCongestionConnector.get_congestion`.
* ``get_congestion`` always returns **exactly one** record: congestion is a
  point-in-time property of a port, and callers should not have to handle a list.
* The congestion level is a pure function of the reported vessel-wait time:
  ``<= 1`` day is Low, ``<= 3`` Moderate, ``<= 7`` High, above that Severe.
* Sample values cover the demo ports; other ports derive a deterministic wait
  time from the port name via :func:`stable_seed` — never randomly.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol

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


class CongestionLevel(str, Enum):
    """Congestion band, ordered from least to most disruptive."""

    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    SEVERE = "Severe"


class PortCongestion(BaseModel):
    """Congestion snapshot for a single port."""

    port: str
    country: Optional[str] = None
    vessels_waiting: int
    average_wait_days: float
    congestion_level: CongestionLevel
    observed_at: str
    provenance: Provenance


class PortCongestionConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_congestion(self, *, port: str) -> PortCongestion:
        """Return the current congestion snapshot for ``port``."""
        ...


#: Sample ports: (average wait days, vessels waiting, country).
_SAMPLE_PORTS: Mapping[str, Dict[str, Any]] = {
    "shanghai": {"average_wait_days": 4.5, "vessels_waiting": 62, "country": "China"},
    "rotterdam": {"average_wait_days": 0.8, "vessels_waiting": 14, "country": "Netherlands"},
    "singapore": {"average_wait_days": 1.2, "vessels_waiting": 21, "country": "Singapore"},
    "jebel ali": {"average_wait_days": 2.4, "vessels_waiting": 27, "country": "United Arab Emirates"},
    "los angeles": {"average_wait_days": 3.6, "vessels_waiting": 33, "country": "United States"},
    "hamburg": {"average_wait_days": 1.1, "vessels_waiting": 18, "country": "Germany"},
    "mumbai": {"average_wait_days": 2.0, "vessels_waiting": 22, "country": "India"},
    "antwerp": {"average_wait_days": 0.9, "vessels_waiting": 12, "country": "Belgium"},
    "gdansk": {"average_wait_days": 1.6, "vessels_waiting": 9, "country": "Poland"},
    "shenzhen": {"average_wait_days": 5.0, "vessels_waiting": 58, "country": "China"},
    "chennai": {"average_wait_days": 1.4, "vessels_waiting": 16, "country": "India"},
    "new york": {"average_wait_days": 2.8, "vessels_waiting": 24, "country": "United States"},
}

#: Upper bounds (inclusive) for each band, evaluated in order.
_LEVEL_BOUNDS: List[tuple[float, CongestionLevel]] = [
    (1.0, CongestionLevel.LOW),
    (3.0, CongestionLevel.MODERATE),
    (7.0, CongestionLevel.HIGH),
]


def congestion_level_for(wait_days: float) -> CongestionLevel:
    """Map an average vessel-wait time onto a congestion band (deterministic)."""
    for bound, level in _LEVEL_BOUNDS:
        if wait_days <= bound:
            return level
    return CongestionLevel.SEVERE


class SimulatedPortCongestionConnector(MockConnector):
    """Clearly labelled sample congestion feed (no live provider configured)."""

    name = "port_congestion"
    provider = "X FACTOR simulated port congestion feed"

    def get_congestion(self, *, port: str) -> PortCongestion:
        key = (port or "").strip().lower()
        if not key:
            raise ValueError("port must be a non-empty string")

        provenance = self.provenance(endpoint="simulated://port-congestion")
        sample = _SAMPLE_PORTS.get(key)
        if sample is None:
            seed = stable_seed("congestion", key)
            wait_days = round((seed % 900) / 100.0, 2)
            vessels = 5 + seed % 70
            country = None
        else:
            wait_days = float(sample["average_wait_days"])
            vessels = int(sample["vessels_waiting"])
            country = sample.get("country")

        return PortCongestion(
            port=port,
            country=country,
            vessels_waiting=vessels,
            average_wait_days=wait_days,
            congestion_level=congestion_level_for(wait_days),
            observed_at=utc_now().isoformat(),
            provenance=provenance,
        )


class LivePortCongestionConnector(HttpConnector):
    """Live port congestion adapter (requires PORT_CONGESTION_API_BASE_URL)."""

    name = "port_congestion"
    provider = "Live port congestion API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.PORT_CONGESTION_API_BASE_URL,
                api_key=settings.PORT_CONGESTION_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_congestion(self, *, port: str) -> PortCongestion:
        payload = self.client.get_json("/congestion", params={"port": port})
        record = payload[0] if isinstance(payload, list) else payload
        if not isinstance(record, Mapping):
            record = {}
        provenance = self.provenance(endpoint=f"{self.client.base_url}/congestion")
        return _map_congestion(record, port, provenance)


def _map_congestion(record: Mapping[str, Any], port: str, provenance: Provenance) -> PortCongestion:
    """Map one provider record onto the platform's own model."""
    wait_days = _optional_float(record.get("average_wait_days"))
    if wait_days is None:
        wait_days = _optional_float(record.get("wait_days"))
    if wait_days is None:
        wait_days = _optional_float(record.get("waiting_time_days")) or 0.0

    return PortCongestion(
        port=str(record.get("port") or port),
        country=record.get("country"),
        vessels_waiting=int(_optional_float(record.get("vessels_waiting")) or 0),
        average_wait_days=wait_days,
        congestion_level=congestion_level_for(wait_days),
        observed_at=str(record.get("observed_at") or utc_now().isoformat()),
        provenance=provenance,
    )


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_port_congestion_connector(settings: Optional[Settings] = None) -> PortCongestionConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LivePortCongestionConnector(settings)
    if live.configured:
        return live
    logger.info("Port congestion API not configured — using clearly labelled simulated feed.")
    return SimulatedPortCongestionConnector()
