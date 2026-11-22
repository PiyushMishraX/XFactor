"""PostgreSQL-backed lookups for shipments and suppliers.

This is the only place where the Disruption Sensing Agent learns which shipment
or supplier identifiers are real. The LLM's mentions are treated as *claims* and
are cross-checked here, never trusted directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Protocol, Sequence, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.supply_chain import Shipment, Supplier

logger = logging.getLogger(__name__)

#: Shortest location string that may be used for a match. Guards against noise
#: such as "US" matching unrelated route text.
MIN_LOCATION_MATCH_LENGTH = 3

#: Upper bound on shipments returned by a single geographic match.
MAX_LOCATION_MATCHES = 50


@dataclass(frozen=True)
class ShipmentRef:
    """A shipment row reduced to what the agent needs."""

    id: str
    origin: str
    destination: str
    route: str
    transport_mode: str
    carrier: str
    status: str
    cargo: str
    value_usd: float
    supplier_id: str


@dataclass(frozen=True)
class SupplierRef:
    """A supplier row reduced to what the agent needs."""

    id: str
    name: str
    country: str
    category: str
    risk_tier: str


@dataclass(frozen=True)
class SupplyChainSnapshot:
    """Validated supply-chain context for one disruption assessment."""

    shipments_by_reference: Tuple[ShipmentRef, ...] = ()
    shipments_by_location: Tuple[ShipmentRef, ...] = ()
    shipments_by_supplier: Tuple[ShipmentRef, ...] = ()
    suppliers_by_reference: Tuple[SupplierRef, ...] = ()
    suppliers_by_location: Tuple[SupplierRef, ...] = ()
    unknown_shipment_ids: Tuple[str, ...] = ()
    unknown_supplier_ids: Tuple[str, ...] = ()

    @property
    def shipments(self) -> Tuple[ShipmentRef, ...]:
        """All exposed shipments, de-duplicated by id, most direct evidence first."""
        return _merge_unique(
            self.shipments_by_reference,
            self.shipments_by_location,
            self.shipments_by_supplier,
            key=lambda item: item.id,
        )

    @property
    def suppliers(self) -> Tuple[SupplierRef, ...]:
        """Referenced and geographically matched suppliers, de-duplicated by id."""
        return _merge_unique(
            self.suppliers_by_reference, self.suppliers_by_location, key=lambda item: item.id
        )

    @property
    def shipment_ids(self) -> List[str]:
        return [shipment.id for shipment in self.shipments]

    @property
    def supplier_ids(self) -> List[str]:
        return [supplier.id for supplier in self.suppliers]


class SupplyChainRepository(Protocol):
    """The lookup interface the Disruption Sensing Agent depends on."""

    def snapshot(
        self,
        *,
        shipment_ids: Sequence[str],
        supplier_ids: Sequence[str],
        locations: Sequence[str],
    ) -> SupplyChainSnapshot:
        """Return validated supply-chain context for the given claims."""
        ...


class PostgresSupplyChainRepository:
    """Concrete repository reading the ``shipments`` and ``suppliers`` tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def snapshot(
        self,
        *,
        shipment_ids: Sequence[str],
        supplier_ids: Sequence[str],
        locations: Sequence[str],
    ) -> SupplyChainSnapshot:
        wanted_shipments = normalise_reference_ids(shipment_ids)
        wanted_suppliers = normalise_reference_ids(supplier_ids)

        shipments_by_reference = self._shipments_by_ids(wanted_shipments)
        suppliers_by_reference = self._suppliers_by_ids(wanted_suppliers)
        suppliers_by_location = self._suppliers_in(locations)

        found_shipment_ids = {shipment.id for shipment in shipments_by_reference}
        found_supplier_ids = {supplier.id for supplier in suppliers_by_reference}

        unknown_shipments = tuple(
            sorted(ref for ref in wanted_shipments if ref not in found_shipment_ids)
        )
        unknown_suppliers = tuple(
            sorted(ref for ref in wanted_suppliers if ref not in found_supplier_ids)
        )
        if unknown_shipments or unknown_suppliers:
            logger.warning(
                "Assessment referenced records absent from PostgreSQL (shipments=%s, suppliers=%s)",
                list(unknown_shipments),
                list(unknown_suppliers),
            )

        exposed_supplier_ids = sorted(
            {supplier.id for supplier in (*suppliers_by_reference, *suppliers_by_location)}
        )

        return SupplyChainSnapshot(
            shipments_by_reference=tuple(shipments_by_reference),
            shipments_by_location=tuple(self._shipments_touching(locations)),
            shipments_by_supplier=tuple(self._shipments_of_suppliers(exposed_supplier_ids)),
            suppliers_by_reference=tuple(suppliers_by_reference),
            suppliers_by_location=tuple(suppliers_by_location),
            unknown_shipment_ids=unknown_shipments,
            unknown_supplier_ids=unknown_suppliers,
        )

    # -- queries ---------------------------------------------------------

    def _shipments_by_ids(self, shipment_ids: Sequence[str]) -> List[ShipmentRef]:
        if not shipment_ids:
            return []
        statement = (
            select(Shipment).where(Shipment.id.in_(shipment_ids)).order_by(Shipment.id)
        )
        return [_to_shipment_ref(row) for row in self._session.execute(statement).scalars()]

    def _suppliers_by_ids(self, supplier_ids: Sequence[str]) -> List[SupplierRef]:
        if not supplier_ids:
            return []
        statement = select(Supplier).where(Supplier.id.in_(supplier_ids)).order_by(Supplier.id)
        return [_to_supplier_ref(row) for row in self._session.execute(statement).scalars()]

    def _shipments_touching(self, locations: Sequence[str]) -> List[ShipmentRef]:
        patterns = location_patterns(locations)
        if not patterns:
            return []
        condition = or_(
            *[
                clause
                for pattern in patterns
                for clause in (
                    Shipment.origin.ilike(pattern),
                    Shipment.destination.ilike(pattern),
                    Shipment.route.ilike(pattern),
                )
            ]
        )
        statement = (
            select(Shipment)
            .where(condition)
            .order_by(Shipment.id)
            .limit(MAX_LOCATION_MATCHES)
        )
        return [_to_shipment_ref(row) for row in self._session.execute(statement).scalars()]

    def _suppliers_in(self, locations: Sequence[str]) -> List[SupplierRef]:
        patterns = location_patterns(locations)
        if not patterns:
            return []
        condition = or_(*[Supplier.country.ilike(pattern) for pattern in patterns])
        statement = select(Supplier).where(condition).order_by(Supplier.id)
        return [_to_supplier_ref(row) for row in self._session.execute(statement).scalars()]

    def _shipments_of_suppliers(self, supplier_ids: Sequence[str]) -> List[ShipmentRef]:
        """Shipments belonging to an exposed supplier.

        A supplier failure puts every shipment that supplier fulfils at risk, even
        when the shipment's own lane is nowhere near the disruption.
        """
        if not supplier_ids:
            return []
        statement = (
            select(Shipment)
            .where(Shipment.supplier_id.in_(supplier_ids))
            .order_by(Shipment.id)
        )
        return [_to_shipment_ref(row) for row in self._session.execute(statement).scalars()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalise_reference_ids(reference_ids: Iterable[str]) -> List[str]:
    """Upper-case, trim, drop blanks and remove duplicates while keeping order."""
    seen: set[str] = set()
    normalised: List[str] = []
    for raw in reference_ids:
        candidate = str(raw).strip().upper()
        if candidate and candidate not in seen:
            seen.add(candidate)
            normalised.append(candidate)
    return normalised


def location_patterns(locations: Iterable[str]) -> List[str]:
    """Turn free-text locations into SQL ``ILIKE`` patterns.

    Locations shorter than :data:`MIN_LOCATION_MATCH_LENGTH` are skipped because a
    substring match on one or two characters would match unrelated rows.
    """
    patterns: List[str] = []
    for raw in locations:
        cleaned = str(raw).strip()
        if len(cleaned) >= MIN_LOCATION_MATCH_LENGTH:
            patterns.append(f"%{cleaned}%")
    return patterns


def _merge_unique(*sequences: Sequence, key) -> Tuple:
    """Concatenate sequences, keeping the first occurrence of each ``key`` value."""
    merged: List = []
    seen: set = set()
    for sequence in sequences:
        for item in sequence:
            identity = key(item)
            if identity not in seen:
                seen.add(identity)
                merged.append(item)
    return tuple(merged)


def _to_shipment_ref(row: Shipment) -> ShipmentRef:
    return ShipmentRef(
        id=row.id,
        origin=row.origin,
        destination=row.destination,
        route=row.route,
        transport_mode=row.transport_mode,
        carrier=row.carrier,
        status=row.status,
        cargo=row.cargo,
        value_usd=float(row.value_usd) if isinstance(row.value_usd, Decimal) else row.value_usd,
        supplier_id=row.supplier_id,
    )


def _to_supplier_ref(row: Supplier) -> SupplierRef:
    return SupplierRef(
        id=row.id,
        name=row.name,
        country=row.country,
        category=row.category,
        risk_tier=row.risk_tier,
    )
