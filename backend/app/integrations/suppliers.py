"""Supplier master-data connector (Step 2).

Supplies supplier profiles (identity, risk tier, performance metrics) that the
sensing and recovery agents consume. The live variant calls a configured HTTP
JSON provider; when no provider is configured the factory returns
:class:`SimulatedSupplierConnector`, whose profiles are clearly marked
``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/suppliers?id=<id>`` for a single profile and
  ``GET {base}/suppliers`` for the full list.
* When a live provider is asked for an unknown supplier it returns HTTP 404; that
  is translated into ``None`` rather than an error, so callers can distinguish
  "no such supplier" from "provider broken".
* The sample profiles match the demo masters used by
  :mod:`app.services.reference_data` (SUP001..SUP005) so the connector and the
  seeded PostgreSQL rows describe the same suppliers.
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpConnector,
    HttpJsonClient,
    IntegrationRequestError,
    MockConnector,
    Provenance,
)

logger = logging.getLogger(__name__)


class SupplierProfile(BaseModel):
    """Everything the agents need to know about one supplier."""

    supplier_id: str
    name: str
    country: str
    category: str
    risk_tier: str
    on_time_delivery_rate: float
    quality_score: float
    price_index: float
    capacity_utilisation: float
    lead_time_days: float
    monthly_capacity_units: int
    annual_spend_usd: float
    certifications: List[str] = []
    provenance: Provenance


class SupplierConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_profile(self, *, supplier_id: str) -> Optional[SupplierProfile]:
        """Return the profile for ``supplier_id``, or ``None`` when unknown."""
        ...

    def list_profiles(self) -> List[SupplierProfile]:
        """Return every known supplier profile."""
        ...


#: Sample profiles, keyed by id. Metrics are demo values, not live figures.
_SAMPLE_PROFILES: Sequence[Dict[str, Any]] = (
    {
        "supplier_id": "SUP001",
        "name": "Aurora Pharma Ingredients",
        "country": "India",
        "category": "Pharmaceutical API",
        "risk_tier": "Medium",
        "on_time_delivery_rate": 0.91,
        "quality_score": 0.94,
        "price_index": 1.05,
        "capacity_utilisation": 0.72,
        "lead_time_days": 21.0,
        "monthly_capacity_units": 85000,
        "annual_spend_usd": 4200000.0,
        "certifications": ["GMP", "ISO 9001", "WHO PQ"],
    },
    {
        "supplier_id": "SUP002",
        "name": "Nordwind Chemie GmbH",
        "country": "Germany",
        "category": "Speciality Chemicals",
        "risk_tier": "Low",
        "on_time_delivery_rate": 0.97,
        "quality_score": 0.96,
        "price_index": 1.35,
        "capacity_utilisation": 0.61,
        "lead_time_days": 9.0,
        "monthly_capacity_units": 42000,
        "annual_spend_usd": 3900000.0,
        "certifications": ["ISO 9001", "REACH", "ISO 14001"],
    },
    {
        "supplier_id": "SUP003",
        "name": "Shenzhen Micro Components",
        "country": "China",
        "category": "Electronics",
        "risk_tier": "High",
        "on_time_delivery_rate": 0.83,
        "quality_score": 0.88,
        "price_index": 0.82,
        "capacity_utilisation": 0.93,
        "lead_time_days": 32.0,
        "monthly_capacity_units": 260000,
        "annual_spend_usd": 9800000.0,
        "certifications": ["ISO 9001", "IATF 16949"],
    },
    {
        "supplier_id": "SUP004",
        "name": "Gulf Petro Resins",
        "country": "United Arab Emirates",
        "category": "Polymers",
        "risk_tier": "Medium",
        "on_time_delivery_rate": 0.89,
        "quality_score": 0.9,
        "price_index": 0.95,
        "capacity_utilisation": 0.8,
        "lead_time_days": 16.0,
        "monthly_capacity_units": 140000,
        "annual_spend_usd": 5100000.0,
        "certifications": ["ISO 9001", "ISO 14001"],
    },
    {
        "supplier_id": "SUP005",
        "name": "Baltic Steel Works",
        "country": "Poland",
        "category": "Steel",
        "risk_tier": "Low",
        "on_time_delivery_rate": 0.94,
        "quality_score": 0.92,
        "price_index": 1.12,
        "capacity_utilisation": 0.68,
        "lead_time_days": 24.0,
        "monthly_capacity_units": 60000,
        "annual_spend_usd": 2750000.0,
        "certifications": ["ISO 9001", "EN 10204"],
    },
)

_PROFILES_BY_ID: Mapping[str, Dict[str, Any]] = {
    str(profile["supplier_id"]): profile for profile in _SAMPLE_PROFILES
}


class SimulatedSupplierConnector(MockConnector):
    """Clearly labelled sample supplier master (no live provider configured)."""

    name = "suppliers"
    provider = "X FACTOR simulated supplier master"

    def get_profile(self, *, supplier_id: str) -> Optional[SupplierProfile]:
        key = (supplier_id or "").strip()
        if not key:
            raise ValueError("supplier_id must be a non-empty string")
        sample = _PROFILES_BY_ID.get(key)
        if sample is None:
            return None
        return _build_profile(sample, self.provenance(endpoint="simulated://suppliers"))

    def list_profiles(self) -> List[SupplierProfile]:
        provenance = self.provenance(endpoint="simulated://suppliers")
        return [_build_profile(sample, provenance) for sample in _SAMPLE_PROFILES]


class LiveSupplierConnector(HttpConnector):
    """Live supplier master adapter (requires SUPPLIER_API_BASE_URL)."""

    name = "suppliers"
    provider = "Live supplier API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.SUPPLIER_API_BASE_URL,
                api_key=settings.SUPPLIER_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_profile(self, *, supplier_id: str) -> Optional[SupplierProfile]:
        provenance = self.provenance(endpoint=f"{self.client.base_url}/suppliers")
        try:
            payload = self.client.get_json("/suppliers", params={"id": supplier_id})
        except IntegrationRequestError as exc:
            if "404" in str(exc):
                return None
            raise
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, Mapping):
            return None
        return _build_profile(record, provenance)

    def list_profiles(self) -> List[SupplierProfile]:
        payload = self.client.get_json("/suppliers")
        records = payload.get("suppliers", []) if isinstance(payload, dict) else payload
        provenance = self.provenance(endpoint=f"{self.client.base_url}/suppliers")
        return [_build_profile(record, provenance) for record in records]


def _build_profile(record: Mapping[str, Any], provenance: Provenance) -> SupplierProfile:
    """Map a provider/sample record onto the platform's own model."""
    return SupplierProfile(
        supplier_id=str(record.get("supplier_id") or record.get("id") or ""),
        name=str(record.get("name") or ""),
        country=str(record.get("country") or ""),
        category=str(record.get("category") or ""),
        risk_tier=str(record.get("risk_tier") or "Medium"),
        on_time_delivery_rate=float(record.get("on_time_delivery_rate") or 0.0),
        quality_score=float(record.get("quality_score") or 0.0),
        price_index=float(record.get("price_index") or 1.0),
        capacity_utilisation=float(record.get("capacity_utilisation") or 0.0),
        lead_time_days=float(record.get("lead_time_days") or 0.0),
        monthly_capacity_units=int(record.get("monthly_capacity_units") or 0),
        annual_spend_usd=float(record.get("annual_spend_usd") or 0.0),
        certifications=[str(item) for item in (record.get("certifications") or [])],
        provenance=provenance,
    )


def get_supplier_connector(settings: Optional[Settings] = None) -> SupplierConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveSupplierConnector(settings)
    if live.configured:
        return live
    logger.info("Supplier API not configured — using clearly labelled simulated master.")
    return SimulatedSupplierConnector()
