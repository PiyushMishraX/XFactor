"""Tariff / duty connector (Step 2).

Returns the applicable import duty and additional levies for a trade lane and
commodity code so the costing engine can price a reroute. The live variant calls
a configured HTTP JSON provider; when no provider is configured the factory
returns :class:`SimulatedTariffConnector`, whose rates are clearly marked
``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/rate?origin=<c>&destination=<c>&hs_code=<code>``
  returning a single JSON object with the fields mapped in
  :meth:`LiveTariffConnector.get_rate`.
* Sample rates cover the demo trade lanes. For any other lane the rate is derived
  deterministically from the origin/destination/HS-code triple via
  :func:`stable_seed` — never randomly.
* Rates are expressed as percentages of customs value; ``total_rate_percent`` is
  the duty plus any additional levy and is what the costing engine consumes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

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


class TariffRate(BaseModel):
    """Applicable duty rates for one trade lane / commodity code."""

    origin_country: str
    destination_country: str
    hs_code: str
    duty_rate_percent: float
    additional_levy_percent: float
    total_rate_percent: float
    currency: str = "USD"
    effective_from: str
    provenance: Provenance


class TariffConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_rate(
        self, *, origin_country: str, destination_country: str, hs_code: str
    ) -> TariffRate:
        """Return the applicable rate for the lane and commodity code."""
        ...


#: Sample lanes keyed by (origin, destination) lower-cased. Customs duty only —
#: the additional levy is derived per HS code so the same lane varies by goods.
_SAMPLE_LANES: Mapping[Tuple[str, str], Dict[str, Any]] = {
    ("india", "netherlands"): {"duty_rate_percent": 0.0, "currency": "EUR"},
    ("china", "germany"): {"duty_rate_percent": 4.7, "currency": "EUR"},
    ("china", "united states"): {"duty_rate_percent": 7.5, "currency": "USD"},
    ("united arab emirates", "netherlands"): {"duty_rate_percent": 2.1, "currency": "EUR"},
    ("india", "singapore"): {"duty_rate_percent": 0.0, "currency": "SGD"},
    ("poland", "india"): {"duty_rate_percent": 12.5, "currency": "INR"},
    ("germany", "united states"): {"duty_rate_percent": 3.3, "currency": "USD"},
    ("china", "netherlands"): {"duty_rate_percent": 4.7, "currency": "EUR"},
}


class SimulatedTariffConnector(MockConnector):
    """Clearly labelled sample tariff feed (no live provider configured)."""

    name = "tariffs"
    provider = "X FACTOR simulated tariff feed"

    def get_rate(
        self, *, origin_country: str, destination_country: str, hs_code: str
    ) -> TariffRate:
        origin = (origin_country or "").strip()
        destination = (destination_country or "").strip()
        code = (hs_code or "").strip()
        if not origin or not destination or not code:
            raise ValueError("origin_country, destination_country and hs_code are required")

        provenance = self.provenance(endpoint="simulated://tariffs/rate")
        sample = _SAMPLE_LANES.get((origin.lower(), destination.lower()))
        if sample is None:
            seed = stable_seed("tariff", origin.lower(), destination.lower())
            duty = round((seed % 1500) / 100.0, 2)
            currency = "USD"
        else:
            duty = float(sample["duty_rate_percent"])
            currency = str(sample["currency"])

        levy = _levy_for_hs_code(code)
        return TariffRate(
            origin_country=origin,
            destination_country=destination,
            hs_code=code,
            duty_rate_percent=duty,
            additional_levy_percent=levy,
            total_rate_percent=round(duty + levy, 3),
            currency=currency,
            effective_from=utc_now().date().isoformat(),
            provenance=provenance,
        )


def _levy_for_hs_code(hs_code: str) -> float:
    """Deterministic additional levy (anti-dumping type) driven by the HS code."""
    seed = stable_seed("levy", hs_code)
    return round((seed % 300) / 100.0, 2)


class LiveTariffConnector(HttpConnector):
    """Live tariff adapter (requires TARIFF_API_BASE_URL)."""

    name = "tariffs"
    provider = "Live tariff API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.TARIFF_API_BASE_URL,
                api_key=settings.TARIFF_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_rate(
        self, *, origin_country: str, destination_country: str, hs_code: str
    ) -> TariffRate:
        payload = self.client.get_json(
            "/rate",
            params={
                "origin": origin_country,
                "destination": destination_country,
                "hs_code": hs_code,
            },
        )
        record = payload if isinstance(payload, Mapping) else {}
        provenance = self.provenance(endpoint=f"{self.client.base_url}/rate")
        return _map_rate(record, origin_country, destination_country, hs_code, provenance)


def _map_rate(
    record: Mapping[str, Any],
    origin_country: str,
    destination_country: str,
    hs_code: str,
    provenance: Provenance,
) -> TariffRate:
    """Map one provider record onto the platform's own model."""
    duty = _optional_float(record.get("duty_rate_percent")) or 0.0
    levy = _optional_float(record.get("additional_levy_percent")) or 0.0
    total = _optional_float(record.get("total_rate_percent"))
    return TariffRate(
        origin_country=str(record.get("origin_country") or origin_country),
        destination_country=str(record.get("destination_country") or destination_country),
        hs_code=str(record.get("hs_code") or hs_code),
        duty_rate_percent=duty,
        additional_levy_percent=levy,
        total_rate_percent=round(total, 3) if total is not None else round(duty + levy, 3),
        currency=str(record.get("currency") or "USD"),
        effective_from=str(record.get("effective_from") or utc_now().date().isoformat()),
        provenance=provenance,
    )


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_tariff_connector(settings: Optional[Settings] = None) -> TariffConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveTariffConnector(settings)
    if live.configured:
        return live
    logger.info("Tariff API not configured — using clearly labelled simulated feed.")
    return SimulatedTariffConnector()
