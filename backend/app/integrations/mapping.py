"""Route / distance mapping connector (Step 2).

Returns the distance and reference transit time for a lane so the costing and
lead-time engines have real inputs. The live variant calls a configured HTTP JSON
provider; when no provider is configured the factory returns
:class:`SimulatedMappingConnector`, whose values are clearly marked
``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/route?origin=<a>&destination=<b>`` returning a
  single JSON object with the fields mapped in
  :meth:`LiveMappingConnector.get_route`.
* ``is_estimated`` distinguishes a **known** lane (a value taken from the demo
  lane table, ``False``) from a **derived** one (the reverse of a known lane, or
  a lane computed deterministically from the endpoints via :func:`stable_seed`,
  ``True``). Callers can therefore tell measured lanes from inferred ones.
* ``transit_days_sea`` is a sea reference time; other modes are estimated by the
  lead-time engine, which owns that conversion.
* Distances are indicative straight-line-plus-canal estimates for the demo lanes,
  not survey-grade routing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpConnector,
    HttpJsonClient,
    MockConnector,
    Provenance,
    stable_seed,
)

logger = logging.getLogger(__name__)


class RouteDistance(BaseModel):
    """Distance and reference transit time for one lane."""

    origin: str
    destination: str
    distance_km: float
    transit_days_sea: float
    transport_mode: str = "Sea"
    is_estimated: bool
    provenance: Provenance


class MappingConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_route(self, *, origin: str, destination: str) -> RouteDistance:
        """Return the distance record for the ``origin`` → ``destination`` lane."""
        ...


#: Known demo lanes keyed by (origin, destination) lower-cased: (km, sea days).
_SAMPLE_LANES: Mapping[Tuple[str, str], Tuple[float, float]] = {
    ("mumbai", "rotterdam"): (11000.0, 21.0),
    ("mumbai", "hamburg"): (11500.0, 22.0),
    ("shanghai", "hamburg"): (19500.0, 32.0),
    ("shanghai", "los angeles"): (10500.0, 18.0),
    ("jebel ali", "rotterdam"): (8500.0, 16.0),
    ("gdansk", "mumbai"): (11500.0, 24.0),
    ("rotterdam", "chicago"): (7200.0, 9.0),
    ("chennai", "singapore"): (3200.0, 7.0),
    ("antwerp", "new york"): (6200.0, 12.0),
    ("shenzhen", "rotterdam"): (17500.0, 30.0),
}


class SimulatedMappingConnector(MockConnector):
    """Clearly labelled sample route mapping (no live provider configured)."""

    name = "mapping"
    provider = "X FACTOR simulated route mapping"

    def get_route(self, *, origin: str, destination: str) -> RouteDistance:
        start = (origin or "").strip()
        end = (destination or "").strip()
        if not start or not end:
            raise ValueError("origin and destination must be non-empty strings")

        provenance = self.provenance(endpoint="simulated://mapping/route")
        key = (start.lower(), end.lower())
        known = _SAMPLE_LANES.get(key)
        if known is not None:
            distance_km, transit_days = known
            is_estimated = False
        else:
            distance_km, transit_days = self._derive(key)
            is_estimated = True

        return RouteDistance(
            origin=start,
            destination=end,
            distance_km=distance_km,
            transit_days_sea=transit_days,
            is_estimated=is_estimated,
            provenance=provenance,
        )

    @staticmethod
    def _derive(key: Tuple[str, str]) -> Tuple[float, float]:
        """Derive a lane from its reverse, else deterministically from the pair."""
        reverse = _SAMPLE_LANES.get((key[1], key[0]))
        if reverse is not None:
            return reverse
        seed = stable_seed("mapping", key[0], key[1])
        distance_km = float(2000 + seed % 18000)
        transit_days = round(distance_km / 650.0, 1)
        return distance_km, transit_days


class LiveMappingConnector(HttpConnector):
    """Live route mapping adapter (requires MAPPING_API_BASE_URL)."""

    name = "mapping"
    provider = "Live route mapping API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.MAPPING_API_BASE_URL,
                api_key=settings.MAPPING_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_route(self, *, origin: str, destination: str) -> RouteDistance:
        payload = self.client.get_json(
            "/route", params={"origin": origin, "destination": destination}
        )
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, Mapping):
            record = {}
        provenance = self.provenance(endpoint=f"{self.client.base_url}/route")
        return _map_route(record, origin, destination, provenance)


def _map_route(
    record: Mapping[str, Any], origin: str, destination: str, provenance: Provenance
) -> RouteDistance:
    """Map one provider record onto the platform's own model.

    A live provider's value is treated as measured (``is_estimated=False``)
    unless it explicitly flags the value as estimated.
    """
    return RouteDistance(
        origin=str(record.get("origin") or origin),
        destination=str(record.get("destination") or destination),
        distance_km=float(record.get("distance_km") or 0.0),
        transit_days_sea=float(record.get("transit_days_sea") or record.get("transit_days") or 0.0),
        transport_mode=str(record.get("transport_mode") or "Sea"),
        is_estimated=bool(record.get("is_estimated", False)),
        provenance=provenance,
    )


def get_mapping_connector(settings: Optional[Settings] = None) -> MappingConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveMappingConnector(settings)
    if live.configured:
        return live
    logger.info("Route mapping API not configured — using clearly labelled simulated mapping.")
    return SimulatedMappingConnector()
