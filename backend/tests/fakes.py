"""Test doubles for the agents.

These stand in for external dependencies so the required scenarios can be asserted
deterministically. They mirror the real behaviour closely:

* :class:`StubGeminiService` replays a fixed LLM response (or raises a fixed error).
* :class:`InMemorySupplyChainRepository` performs the same reference/location
  matching as the PostgreSQL repository, but over the demo dataset in memory.
* the Step 3 doubles (:class:`FakeMappingConnector`, :class:`FakeCarrierConnector`,
  :class:`FakeSAPConnector`) return fixed, clearly labelled records so the four new
  agents can be tested without a provider.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.integrations.base import Provenance
from app.integrations.carriers import CarrierService
from app.integrations.mapping import RouteDistance
from app.integrations.sap import SAPInventoryItem
from app.services.reference_data import DEMO_SHIPMENTS, DEMO_SUPPLIERS
from app.services.supply_chain_repository import (
    MIN_LOCATION_MATCH_LENGTH,
    ShipmentRef,
    SupplierRef,
    SupplyChainSnapshot,
    normalise_reference_ids,
)


class StubGeminiService:
    """Returns a canned structured response without touching the network."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: List[Dict[str, Any]] = []

    def generate_structured_json(
        self,
        *,
        prompt: str,
        response_schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        thinking_budget: int = 0,
    ) -> Any:
        self.calls.append(
            {
                "prompt": prompt,
                "response_schema": response_schema,
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
        )
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class InMemorySupplyChainRepository:
    """In-memory equivalent of :class:`PostgresSupplyChainRepository`."""

    def __init__(
        self,
        shipments: Sequence[Dict[str, Any]] = DEMO_SHIPMENTS,
        suppliers: Sequence[Dict[str, Any]] = DEMO_SUPPLIERS,
    ) -> None:
        self._shipments = list(shipments)
        self._suppliers = list(suppliers)

    def snapshot(
        self,
        *,
        shipment_ids: Sequence[str],
        supplier_ids: Sequence[str],
        locations: Sequence[str],
    ) -> SupplyChainSnapshot:
        wanted_shipments = normalise_reference_ids(shipment_ids)
        wanted_suppliers = normalise_reference_ids(supplier_ids)
        patterns = [
            location.strip().lower()
            for location in locations
            if len(location.strip()) >= MIN_LOCATION_MATCH_LENGTH
        ]

        by_reference = [
            self._to_shipment(row)
            for row in self._shipments
            if str(row["id"]).upper() in wanted_shipments
        ]
        by_location = [
            self._to_shipment(row)
            for row in self._shipments
            if any(
                pattern in " ".join(
                    [str(row["origin"]), str(row["destination"]), str(row["route"])]
                ).lower()
                for pattern in patterns
            )
        ]

        suppliers_by_reference = [
            self._to_supplier(row)
            for row in self._suppliers
            if str(row["id"]).upper() in wanted_suppliers
        ]
        suppliers_by_location = [
            self._to_supplier(row)
            for row in self._suppliers
            if any(pattern in str(row["country"]).lower() for pattern in patterns)
        ]

        exposed_supplier_ids = {
            supplier.id for supplier in (*suppliers_by_reference, *suppliers_by_location)
        }
        by_supplier = [
            self._to_shipment(row)
            for row in self._shipments
            if str(row["supplier_id"]) in exposed_supplier_ids
        ]

        found_shipments = {shipment.id for shipment in by_reference}
        found_suppliers = {supplier.id for supplier in suppliers_by_reference}

        return SupplyChainSnapshot(
            shipments_by_reference=tuple(by_reference),
            shipments_by_location=tuple(by_location),
            shipments_by_supplier=tuple(by_supplier),
            suppliers_by_reference=tuple(suppliers_by_reference),
            suppliers_by_location=tuple(suppliers_by_location),
            unknown_shipment_ids=tuple(
                sorted(ref for ref in wanted_shipments if ref not in found_shipments)
            ),
            unknown_supplier_ids=tuple(
                sorted(ref for ref in wanted_suppliers if ref not in found_suppliers)
            ),
        )

    @staticmethod
    def _to_shipment(row: Dict[str, Any]) -> ShipmentRef:
        return ShipmentRef(
            id=str(row["id"]),
            origin=str(row["origin"]),
            destination=str(row["destination"]),
            route=str(row["route"]),
            transport_mode=str(row["transport_mode"]),
            carrier=str(row["carrier"]),
            status=str(row["status"]),
            cargo=str(row["cargo"]),
            value_usd=float(row["value_usd"]),
            supplier_id=str(row["supplier_id"]),
        )

    @staticmethod
    def _to_supplier(row: Dict[str, Any]) -> SupplierRef:
        return SupplierRef(
            id=str(row["id"]),
            name=str(row["name"]),
            country=str(row["country"]),
            category=str(row["category"]),
            risk_tier=str(row["risk_tier"]),
        )


# ---------------------------------------------------------------------------
# Step 3 connector doubles
# ---------------------------------------------------------------------------


def make_provenance(
    source: str = "Test connector", *, is_mock: bool = True
) -> Provenance:
    """A provenance record for a hand-built fixture row."""
    return Provenance(source=source, is_mock=is_mock)


class FakeMappingConnector:
    """Returns one fixed lane distance without touching any provider."""

    name = "mapping"
    is_mock = True

    def __init__(
        self,
        *,
        distance_km: float = 1000.0,
        is_estimated: bool = False,
        transit_days_sea: float = 10.0,
        source: str = "Simulated route mapping",
    ) -> None:
        self._distance_km = distance_km
        self._is_estimated = is_estimated
        self._transit_days_sea = transit_days_sea
        self._source = source

    def get_route(self, *, origin: str, destination: str) -> RouteDistance:
        return RouteDistance(
            origin=origin,
            destination=destination,
            distance_km=self._distance_km,
            transit_days_sea=self._transit_days_sea,
            is_estimated=self._is_estimated,
            provenance=make_provenance(self._source),
        )


def make_carrier_service(
    carrier: str,
    transport_mode: str,
    *,
    reliability: float = 0.9,
    service_name: Optional[str] = None,
    average_transit_days: float = 10.0,
    base_rate_per_km_usd: float = 0.33,
    source: str = "Simulated carrier catalogue",
) -> CarrierService:
    """One hand-built carrier service record."""
    return CarrierService(
        carrier=carrier,
        service_name=service_name or f"{carrier} Service",
        transport_mode=transport_mode,
        reliability=reliability,
        average_transit_days=average_transit_days,
        base_rate_per_km_usd=base_rate_per_km_usd,
        provenance=make_provenance(source),
    )


class FakeCarrierConnector:
    """Returns a fixed carrier catalogue, optionally filtered by mode."""

    name = "carriers"
    is_mock = True

    def __init__(self, services: Sequence[CarrierService]) -> None:
        self._services = list(services)

    def list_services(self, *, transport_mode: Optional[str] = None) -> List[CarrierService]:
        wanted = (transport_mode or "").strip().lower()
        return [
            service
            for service in self._services
            if not wanted or service.transport_mode.strip().lower() == wanted
        ]


def make_inventory_item(
    material_id: str,
    plant: str,
    *,
    on_hand: float,
    safety_stock: float,
    description: Optional[str] = None,
    reorder_point: float = 0.0,
    source: str = "Simulated SAP inventory",
) -> SAPInventoryItem:
    """One hand-built SAP inventory position."""
    return SAPInventoryItem(
        material_id=material_id,
        description=description or material_id,
        plant=plant,
        on_hand_units=on_hand,
        safety_stock_units=safety_stock,
        reorder_point_units=reorder_point,
        provenance=make_provenance(source),
    )


class FakeSAPConnector:
    """Read-only SAP double that exposes inventory positions only.

    The Inventory Rebalancing Agent only reads inventory, so the remaining read
    methods return empty results rather than raising.
    """

    name = "sap"
    is_mock = True

    def __init__(self, inventory: Sequence[SAPInventoryItem]) -> None:
        self._inventory = list(inventory)

    def list_inventory(self) -> List[SAPInventoryItem]:
        return list(self._inventory)

    def get_inventory_item(self, *, material_id: str) -> Optional[SAPInventoryItem]:
        key = (material_id or "").strip()
        for item in self._inventory:
            if item.material_id == key:
                return item
        return None

    def list_shipments(self) -> List[Any]:
        return []

    def get_shipment(self, *, shipment_id: str) -> None:
        return None

    def list_suppliers(self) -> List[Any]:
        return []

    def get_supplier(self, *, supplier_id: str) -> None:
        return None

    def list_purchase_orders(self, *, supplier_id: Optional[str] = None) -> List[Any]:
        return []
