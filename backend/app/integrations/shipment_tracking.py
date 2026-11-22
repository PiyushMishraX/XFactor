"""Shipment tracking connector (Step 2).

Returns the tracking timeline for a shipment so the agents can see where cargo
actually is. The live variant calls a configured HTTP JSON provider; when no
provider is configured the factory returns
:class:`SimulatedShipmentTrackingConnector`, whose events are clearly marked
``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/tracking?shipment_id=<id>`` returning a JSON
  array of event objects (or an object with an ``events`` array).
* The sample timelines align with the demo shipments in
  :mod:`app.services.reference_data` (SH001..SH010). For an unknown shipment id a
  deterministic timeline is derived from the id via :func:`stable_seed` — never
  randomly.
* Tracking is read-only: this connector never books, reroutes or updates a
  shipment.
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


class TrackingStatus(str, Enum):
    """Lifecycle state of a tracked shipment."""

    SCHEDULED = "Scheduled"
    DEPARTED = "Departed"
    IN_TRANSIT = "In Transit"
    DELAYED = "Delayed"
    CUSTOMS_HOLD = "Customs Hold"
    ARRIVED = "Arrived"


class TrackingEvent(BaseModel):
    """One dated milestone in a shipment's journey."""

    shipment_id: str
    status: TrackingStatus
    location: str
    occurred_at: str
    description: str
    provenance: Provenance


class ShipmentTrackingConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_events(self, *, shipment_id: str) -> List[TrackingEvent]:
        """Return the tracking timeline for ``shipment_id``, newest last."""
        ...


#: Sample timelines for the demo shipments: (origin, last known location, status).
_SAMPLE_TIMELINES: Mapping[str, Dict[str, Any]] = {
    "SH001": {"origin": "Mumbai", "location": "Red Sea", "status": TrackingStatus.IN_TRANSIT},
    "SH002": {"origin": "Mumbai", "location": "Gulf of Aden", "status": TrackingStatus.IN_TRANSIT},
    "SH003": {"origin": "Shanghai", "location": "Malacca Strait", "status": TrackingStatus.IN_TRANSIT},
    "SH004": {"origin": "Shanghai", "location": "Pacific Ocean", "status": TrackingStatus.IN_TRANSIT},
    "SH005": {"origin": "Jebel Ali", "location": "Suez Canal", "status": TrackingStatus.DELAYED},
    "SH006": {"origin": "Gdansk", "location": "Gdansk", "status": TrackingStatus.SCHEDULED},
    "SH007": {"origin": "Rotterdam", "location": "Basel", "status": TrackingStatus.IN_TRANSIT},
    "SH008": {"origin": "Chennai", "location": "Singapore", "status": TrackingStatus.CUSTOMS_HOLD},
    "SH009": {"origin": "Antwerp", "location": "Atlantic Ocean", "status": TrackingStatus.IN_TRANSIT},
    "SH010": {"origin": "Shenzhen", "location": "South China Sea", "status": TrackingStatus.IN_TRANSIT},
}


class SimulatedShipmentTrackingConnector(MockConnector):
    """Clearly labelled sample tracking feed (no live provider configured)."""

    name = "shipment_tracking"
    provider = "X FACTOR simulated shipment tracking feed"

    def get_events(self, *, shipment_id: str) -> List[TrackingEvent]:
        key = (shipment_id or "").strip()
        if not key:
            raise ValueError("shipment_id must be a non-empty string")

        provenance = self.provenance(endpoint="simulated://shipment-tracking")
        timeline = _SAMPLE_TIMELINES.get(key)
        if timeline is None:
            timeline = self._generated_timeline(key)

        now = utc_now()
        origin = str(timeline["origin"])
        current = str(timeline["location"])
        status = TrackingStatus(timeline["status"])

        events = [
            TrackingEvent(
                shipment_id=shipment_id,
                status=TrackingStatus.DEPARTED,
                location=origin,
                occurred_at=(now - timedelta(days=6)).isoformat(),
                description=f"Departed {origin}.",
                provenance=provenance,
            )
        ]
        if current != origin:
            events.append(
                TrackingEvent(
                    shipment_id=shipment_id,
                    status=TrackingStatus.IN_TRANSIT,
                    location=current,
                    occurred_at=(now - timedelta(days=2)).isoformat(),
                    description=f"Reported in transit at {current}.",
                    provenance=provenance,
                )
            )
        if status not in (TrackingStatus.DEPARTED, TrackingStatus.IN_TRANSIT):
            events.append(
                TrackingEvent(
                    shipment_id=shipment_id,
                    status=status,
                    location=current,
                    occurred_at=now.isoformat(),
                    description=f"Latest status: {status.value} at {current}.",
                    provenance=provenance,
                )
            )
        return events

    @staticmethod
    def _generated_timeline(shipment_id: str) -> Dict[str, Any]:
        """Deterministic sample timeline for an unknown shipment id."""
        seed = stable_seed("tracking", shipment_id)
        cycle: Sequence[TrackingStatus] = (
            TrackingStatus.SCHEDULED,
            TrackingStatus.DEPARTED,
            TrackingStatus.IN_TRANSIT,
            TrackingStatus.DELAYED,
            TrackingStatus.CUSTOMS_HOLD,
            TrackingStatus.ARRIVED,
        )
        return {
            "origin": f"Origin {seed % 100:02d}",
            "location": f"Waypoint {seed % 97:02d}",
            "status": cycle[seed % len(cycle)],
        }


class LiveShipmentTrackingConnector(HttpConnector):
    """Live tracking adapter (requires SHIPMENT_TRACKING_API_BASE_URL)."""

    name = "shipment_tracking"
    provider = "Live shipment tracking API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.SHIPMENT_TRACKING_API_BASE_URL,
                api_key=settings.SHIPMENT_TRACKING_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_events(self, *, shipment_id: str) -> List[TrackingEvent]:
        payload = self.client.get_json("/tracking", params={"shipment_id": shipment_id})
        records = payload.get("events", []) if isinstance(payload, dict) else payload
        provenance = self.provenance(endpoint=f"{self.client.base_url}/tracking")
        return [_map_event(record, shipment_id, provenance) for record in records]


def _map_event(record: Mapping[str, Any], shipment_id: str, provenance: Provenance) -> TrackingEvent:
    """Map one provider record onto the platform's own model."""
    return TrackingEvent(
        shipment_id=str(record.get("shipment_id") or shipment_id),
        status=_coerce_status(record.get("status")),
        location=str(record.get("location") or "unknown"),
        occurred_at=str(record.get("occurred_at") or record.get("timestamp") or utc_now().isoformat()),
        description=str(record.get("description") or record.get("status") or ""),
        provenance=provenance,
    )


def _coerce_status(value: Any) -> TrackingStatus:
    text = str(value or "").strip().lower()
    for status in TrackingStatus:
        if status.value.lower() == text or status.name.lower() == text:
            return status
    return TrackingStatus.IN_TRANSIT


def get_shipment_tracking_connector(
    settings: Optional[Settings] = None,
) -> ShipmentTrackingConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveShipmentTrackingConnector(settings)
    if live.configured:
        return live
    logger.info("Shipment tracking API not configured — using clearly labelled simulated feed.")
    return SimulatedShipmentTrackingConnector()
