"""Carrier service connector (Step 2).

Lists the carrier services (ocean, rail, road, air) available for a lane, with
reliability and indicative pricing so the route-optimisation engine can score
them. The live variant calls a configured HTTP JSON provider; when no provider is
configured the factory returns :class:`SimulatedCarrierConnector`, whose records
are clearly marked ``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/services?mode=<mode>`` returning a JSON array
  of service objects with the fields mapped in
  :meth:`LiveCarrierConnector.list_services`.
* ``transport_mode`` is an optional filter; ``None`` returns every service.
* The sample services use the same carriers that appear in
  :mod:`app.services.reference_data` (Maersk, MSC, CMA CGM, COSCO, Hapag-Lloyd,
  DB Cargo, Ocean Network Express, Evergreen).
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpConnector,
    HttpJsonClient,
    MockConnector,
    Provenance,
)

logger = logging.getLogger(__name__)


class CarrierService(BaseModel):
    """One bookable carrier service."""

    carrier: str
    service_name: str
    transport_mode: str
    reliability: float
    average_transit_days: float
    base_rate_per_km_usd: float
    coverage_lanes: List[str] = []
    provenance: Provenance


class CarrierConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def list_services(self, *, transport_mode: Optional[str] = None) -> List[CarrierService]:
        """Return carrier services, optionally filtered by ``transport_mode``."""
        ...


_SAMPLE_SERVICES: Sequence[Dict[str, Any]] = (
    {
        "carrier": "Maersk",
        "service_name": "AE7 Asia–Europe",
        "transport_mode": "Sea",
        "reliability": 0.92,
        "average_transit_days": 21.0,
        "base_rate_per_km_usd": 0.33,
        "coverage_lanes": ["Mumbai -> Rotterdam", "Gdansk -> Mumbai"],
    },
    {
        "carrier": "MSC",
        "service_name": "Lion Service",
        "transport_mode": "Sea",
        "reliability": 0.89,
        "average_transit_days": 23.0,
        "base_rate_per_km_usd": 0.31,
        "coverage_lanes": ["Mumbai -> Hamburg", "Antwerp -> New York"],
    },
    {
        "carrier": "CMA CGM",
        "service_name": "FAL Asia–Europe",
        "transport_mode": "Sea",
        "reliability": 0.87,
        "average_transit_days": 24.5,
        "base_rate_per_km_usd": 0.3,
        "coverage_lanes": ["Shanghai -> Hamburg"],
    },
    {
        "carrier": "COSCO",
        "service_name": "Transpacific Express",
        "transport_mode": "Sea",
        "reliability": 0.85,
        "average_transit_days": 18.0,
        "base_rate_per_km_usd": 0.29,
        "coverage_lanes": ["Shanghai -> Los Angeles"],
    },
    {
        "carrier": "Hapag-Lloyd",
        "service_name": "Gulf–Europe Express",
        "transport_mode": "Sea",
        "reliability": 0.9,
        "average_transit_days": 16.0,
        "base_rate_per_km_usd": 0.34,
        "coverage_lanes": ["Jebel Ali -> Rotterdam"],
    },
    {
        "carrier": "Ocean Network Express",
        "service_name": "South-East Asia Feeder",
        "transport_mode": "Sea",
        "reliability": 0.88,
        "average_transit_days": 7.0,
        "base_rate_per_km_usd": 0.36,
        "coverage_lanes": ["Chennai -> Singapore"],
    },
    {
        "carrier": "Evergreen",
        "service_name": "China–Europe Express",
        "transport_mode": "Sea",
        "reliability": 0.86,
        "average_transit_days": 30.0,
        "base_rate_per_km_usd": 0.32,
        "coverage_lanes": ["Shenzhen -> Rotterdam"],
    },
    {
        "carrier": "DB Cargo",
        "service_name": "Rhine–Alpine Rail",
        "transport_mode": "Rail",
        "reliability": 0.93,
        "average_transit_days": 9.0,
        "base_rate_per_km_usd": 0.8,
        "coverage_lanes": ["Rotterdam -> Chicago"],
    },
    {
        "carrier": "DHL Freight",
        "service_name": "Euro Road Network",
        "transport_mode": "Road",
        "reliability": 0.94,
        "average_transit_days": 4.0,
        "base_rate_per_km_usd": 1.6,
        "coverage_lanes": ["Antwerp -> Rotterdam", "Hamburg -> Gdansk"],
    },
    {
        "carrier": "Lufthansa Cargo",
        "service_name": "Air Priority",
        "transport_mode": "Air",
        "reliability": 0.96,
        "average_transit_days": 2.0,
        "base_rate_per_km_usd": 9.0,
        "coverage_lanes": ["Shanghai -> Frankfurt", "Mumbai -> Frankfurt"],
    },
)


class SimulatedCarrierConnector(MockConnector):
    """Clearly labelled sample carrier catalogue (no live provider configured)."""

    name = "carriers"
    provider = "X FACTOR simulated carrier catalogue"

    def list_services(self, *, transport_mode: Optional[str] = None) -> List[CarrierService]:
        provenance = self.provenance(endpoint="simulated://carriers/services")
        wanted = (transport_mode or "").strip().lower()
        return [
            _build_service(sample, provenance)
            for sample in _SAMPLE_SERVICES
            if not wanted or str(sample["transport_mode"]).lower() == wanted
        ]


class LiveCarrierConnector(HttpConnector):
    """Live carrier catalogue adapter (requires CARRIER_API_BASE_URL)."""

    name = "carriers"
    provider = "Live carrier API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.CARRIER_API_BASE_URL,
                api_key=settings.CARRIER_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def list_services(self, *, transport_mode: Optional[str] = None) -> List[CarrierService]:
        params = {"mode": transport_mode} if transport_mode else None
        payload = self.client.get_json("/services", params=params)
        records = payload.get("services", []) if isinstance(payload, dict) else payload
        provenance = self.provenance(endpoint=f"{self.client.base_url}/services")
        return [_build_service(record, provenance) for record in records]


def _build_service(record: Mapping[str, Any], provenance: Provenance) -> CarrierService:
    """Map a provider/sample record onto the platform's own model."""
    return CarrierService(
        carrier=str(record.get("carrier") or "unknown"),
        service_name=str(record.get("service_name") or record.get("service") or ""),
        transport_mode=str(record.get("transport_mode") or record.get("mode") or "Sea"),
        reliability=float(record.get("reliability") or 0.0),
        average_transit_days=float(record.get("average_transit_days") or 0.0),
        base_rate_per_km_usd=float(record.get("base_rate_per_km_usd") or 0.0),
        coverage_lanes=[str(lane) for lane in (record.get("coverage_lanes") or [])],
        provenance=provenance,
    )


def get_carrier_connector(settings: Optional[Settings] = None) -> CarrierConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveCarrierConnector(settings)
    if live.configured:
        return live
    logger.info("Carrier API not configured — using clearly labelled simulated catalogue.")
    return SimulatedCarrierConnector()
