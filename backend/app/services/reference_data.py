"""Supply-chain reference data loader.

The dataset below is **demo seed data** for development and the hackathon
walkthrough. It is written to PostgreSQL so that shipment and supplier lookups are
performed against a real database. It is not live SAP master data, and the
platform never presents it as such — Step 7 replaces it with the SAP connector.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Sequence, Tuple

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.models.supply_chain import Shipment, Supplier

logger = logging.getLogger(__name__)

DEMO_SUPPLIERS: Sequence[Dict[str, str]] = (
    {
        "id": "SUP001",
        "name": "Aurora Pharma Ingredients",
        "country": "India",
        "category": "Pharmaceutical API",
        "risk_tier": "Medium",
    },
    {
        "id": "SUP002",
        "name": "Nordwind Chemie GmbH",
        "country": "Germany",
        "category": "Speciality Chemicals",
        "risk_tier": "Low",
    },
    {
        "id": "SUP003",
        "name": "Shenzhen Micro Components",
        "country": "China",
        "category": "Electronics",
        "risk_tier": "High",
    },
    {
        "id": "SUP004",
        "name": "Gulf Petro Resins",
        "country": "United Arab Emirates",
        "category": "Polymers",
        "risk_tier": "Medium",
    },
    {
        "id": "SUP005",
        "name": "Baltic Steel Works",
        "country": "Poland",
        "category": "Steel",
        "risk_tier": "Low",
    },
)

DEMO_SHIPMENTS: Sequence[Dict[str, object]] = (
    {
        "id": "SH001",
        "origin": "Mumbai",
        "destination": "Rotterdam",
        "route": "Mumbai -> Rotterdam via Suez Canal, Red Sea, Bab-el-Mandeb",
        "transport_mode": "Sea",
        "carrier": "Maersk",
        "status": "In Transit",
        "cargo": "Pharmaceutical API",
        "value_usd": Decimal("1250000.00"),
        "supplier_id": "SUP001",
    },
    {
        "id": "SH002",
        "origin": "Mumbai",
        "destination": "Hamburg",
        "route": "Mumbai -> Hamburg via Suez Canal, Red Sea",
        "transport_mode": "Sea",
        "carrier": "MSC",
        "status": "In Transit",
        "cargo": "Oncology drugs",
        "value_usd": Decimal("860000.00"),
        "supplier_id": "SUP001",
    },
    {
        "id": "SH003",
        "origin": "Shanghai",
        "destination": "Hamburg",
        "route": "Shanghai -> Hamburg via Malacca Strait, Suez Canal, Red Sea",
        "transport_mode": "Sea",
        "carrier": "CMA CGM",
        "status": "In Transit",
        "cargo": "Printed circuit board assemblies",
        "value_usd": Decimal("2400000.00"),
        "supplier_id": "SUP003",
    },
    {
        "id": "SH004",
        "origin": "Shanghai",
        "destination": "Los Angeles",
        "route": "Shanghai -> Los Angeles across the Pacific",
        "transport_mode": "Sea",
        "carrier": "COSCO",
        "status": "In Transit",
        "cargo": "Consumer electronics",
        "value_usd": Decimal("1900000.00"),
        "supplier_id": "SUP003",
    },
    {
        "id": "SH005",
        "origin": "Jebel Ali",
        "destination": "Rotterdam",
        "route": "Jebel Ali -> Rotterdam via Suez Canal, Red Sea",
        "transport_mode": "Sea",
        "carrier": "Hapag-Lloyd",
        "status": "Delayed",
        "cargo": "Polymer resin",
        "value_usd": Decimal("640000.00"),
        "supplier_id": "SUP004",
    },
    {
        "id": "SH006",
        "origin": "Gdansk",
        "destination": "Mumbai",
        "route": "Gdansk -> Mumbai via Suez Canal",
        "transport_mode": "Sea",
        "carrier": "Maersk",
        "status": "Scheduled",
        "cargo": "Steel coil",
        "value_usd": Decimal("480000.00"),
        "supplier_id": "SUP005",
    },
    {
        "id": "SH007",
        "origin": "Rotterdam",
        "destination": "Chicago",
        "route": "Rotterdam -> Chicago inland rail",
        "transport_mode": "Rail",
        "carrier": "DB Cargo",
        "status": "In Transit",
        "cargo": "Speciality chemicals",
        "value_usd": Decimal("320000.00"),
        "supplier_id": "SUP002",
    },
    {
        "id": "SH008",
        "origin": "Chennai",
        "destination": "Singapore",
        "route": "Chennai -> Singapore via Malacca Strait",
        "transport_mode": "Sea",
        "carrier": "Ocean Network Express",
        "status": "In Transit",
        "cargo": "Automotive components",
        "value_usd": Decimal("710000.00"),
        "supplier_id": "SUP001",
    },
    {
        "id": "SH009",
        "origin": "Antwerp",
        "destination": "New York",
        "route": "Antwerp -> New York across the Atlantic",
        "transport_mode": "Sea",
        "carrier": "MSC",
        "status": "In Transit",
        "cargo": "Fine chemicals",
        "value_usd": Decimal("540000.00"),
        "supplier_id": "SUP002",
    },
    {
        "id": "SH010",
        "origin": "Shenzhen",
        "destination": "Rotterdam",
        "route": "Shenzhen -> Rotterdam via Malacca Strait, Suez Canal, Red Sea",
        "transport_mode": "Sea",
        "carrier": "Evergreen",
        "status": "In Transit",
        "cargo": "Semiconductor modules",
        "value_usd": Decimal("3100000.00"),
        "supplier_id": "SUP003",
    },
)


def ensure_schema(engine: Engine) -> None:
    """Create any missing tables for the registered ORM models."""
    Base.metadata.create_all(bind=engine)
    logger.info("Ensured ORM schema for tables: %s", sorted(Base.metadata.tables))


def seed_reference_data(session: Session) -> Tuple[int, int]:
    """Insert or update the demo suppliers and shipments.

    Uses primary-key ``merge`` so the operation is idempotent and re-running it
    updates existing rows rather than duplicating them.

    Returns:
        ``(supplier_count, shipment_count)`` written.
    """
    for payload in DEMO_SUPPLIERS:
        session.merge(Supplier(**payload))
    session.flush()

    for payload in DEMO_SHIPMENTS:
        session.merge(Shipment(**payload))

    session.commit()
    return len(DEMO_SUPPLIERS), len(DEMO_SHIPMENTS)


def clear_reference_data(session: Session) -> None:
    """Remove all seeded reference rows (shipments first, for the FK)."""
    session.query(Shipment).delete()
    session.query(Supplier).delete()
    session.commit()


def demo_shipment_ids() -> List[str]:
    """Ids of the demo shipments, for diagnostics and assertions."""
    return [str(row["id"]) for row in DEMO_SHIPMENTS]
