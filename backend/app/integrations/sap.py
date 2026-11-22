"""SAP connector (Steps 2 and 7) — **read-only**.

Exposes SAP master and transactional data (shipments, suppliers, inventory
positions, purchase orders and material master data) to the agents. Only read
operations are defined here: this connector can never create, change or delete
anything in SAP. Authorized writes live in :mod:`app.integrations.sap_write` and
require recorded human approval.

Three adapters are provided:

* :class:`SimulatedSAPConnector` — clearly labelled sample data (``is_mock=True``)
  used while ``SAP_USE_MOCK`` is true, which is the default. Its shipments and
  suppliers mirror :mod:`app.services.reference_data` so the connector and the
  seeded PostgreSQL rows describe the same records.
* :class:`HttpSAPConnector` — a live read-only adapter used when SAP credentials
  are configured and ``SAP_USE_MOCK`` is false. The relative paths come from the
  prepared profile selected by ``SAP_API_FAMILY`` (see
  :mod:`app.integrations.sap_profiles`).
* Authentication is OAuth2 client credentials when ``SAP_AUTH_URL`` is
  configured (read scope only), otherwise the gateway ``x-api-key`` convention.

Assumptions
-----------
* The live adapter reaches SAP through an API gateway that presents the
  OData/REST endpoints of the selected profile. The profile paths are prepared
  defaults and must be confirmed against the tenant's service catalogue.
* Every returned record carries :class:`~app.integrations.base.Provenance`, so
  simulated SAP data can never be mistaken for a live SAP system.
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpConnector,
    HttpJsonClient,
    IntegrationNotConfiguredError,
    IntegrationRequestError,
    MockConnector,
    Provenance,
)
from app.integrations.sap_auth import SAPHttpClient, sap_token_provider
from app.integrations.sap_profiles import SAPApiProfile, resolve_sap_profile
from app.services.reference_data import DEMO_SHIPMENTS, DEMO_SUPPLIERS

logger = logging.getLogger(__name__)


class SAPShipment(BaseModel):
    """A shipment as SAP holds it."""

    shipment_id: str
    origin: str
    destination: str
    transport_mode: str
    carrier: str
    status: str
    value_usd: float
    supplier_id: str
    provenance: Provenance


class SAPSupplier(BaseModel):
    """A supplier master record as SAP holds it."""

    supplier_id: str
    name: str
    country: str
    category: str
    risk_tier: str
    provenance: Provenance


class SAPInventoryItem(BaseModel):
    """An inventory position for one material at one plant."""

    material_id: str
    description: str
    plant: str
    on_hand_units: float
    safety_stock_units: float
    reorder_point_units: float
    provenance: Provenance


class SAPMaterial(BaseModel):
    """Material master data as SAP holds it."""

    material_id: str
    description: str
    material_type: str
    base_unit: str
    category: str
    provenance: Provenance


class SAPPurchaseOrder(BaseModel):
    """An open purchase order."""

    po_number: str
    supplier_id: str
    material_id: str
    quantity: float
    value_usd: float
    status: str
    expected_delivery: str
    provenance: Provenance


class SAPConnector(Protocol):
    """**Read-only** SAP access used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_shipment(self, *, shipment_id: str) -> Optional[SAPShipment]: ...

    def list_shipments(self) -> List[SAPShipment]: ...

    def get_supplier(self, *, supplier_id: str) -> Optional[SAPSupplier]: ...

    def list_suppliers(self) -> List[SAPSupplier]: ...

    def get_inventory_item(self, *, material_id: str) -> Optional[SAPInventoryItem]: ...

    def list_inventory(self) -> List[SAPInventoryItem]: ...

    def get_material(self, *, material_id: str) -> Optional[SAPMaterial]: ...

    def list_materials(self) -> List[SAPMaterial]: ...

    def list_purchase_orders(self, *, supplier_id: Optional[str] = None) -> List[SAPPurchaseOrder]: ...


#: Sample inventory positions (not part of the Step 1 reference data set).
_SAMPLE_INVENTORY: Sequence[Dict[str, Any]] = (
    {
        "material_id": "MAT-PHARMA-001",
        "description": "Paracetamol API",
        "plant": "Mumbai DC",
        "on_hand_units": 42000.0,
        "safety_stock_units": 12000.0,
        "reorder_point_units": 20000.0,
    },
    {
        "material_id": "MAT-PHARMA-001",
        "description": "Paracetamol API",
        "plant": "Hamburg DC",
        "on_hand_units": 16000.0,
        "safety_stock_units": 5000.0,
        "reorder_point_units": 9000.0,
    },
    {
        "material_id": "MAT-CHEM-002",
        "description": "Speciality polymer additive",
        "plant": "Hamburg DC",
        "on_hand_units": 8600.0,
        "safety_stock_units": 3000.0,
        "reorder_point_units": 5500.0,
    },
    {
        "material_id": "MAT-ELEC-003",
        "description": "PCB assembly (8-layer)",
        "plant": "Rotterdam DC",
        "on_hand_units": 1500.0,
        "safety_stock_units": 4000.0,
        "reorder_point_units": 7000.0,
    },
    {
        "material_id": "MAT-ELEC-003",
        "description": "PCB assembly (8-layer)",
        "plant": "Singapore DC",
        "on_hand_units": 12000.0,
        "safety_stock_units": 3000.0,
        "reorder_point_units": 6000.0,
    },
    {
        "material_id": "MAT-POLY-004",
        "description": "PET resin grade A",
        "plant": "Rotterdam DC",
        "on_hand_units": 26000.0,
        "safety_stock_units": 9000.0,
        "reorder_point_units": 15000.0,
    },
    {
        "material_id": "MAT-STEEL-005",
        "description": "Cold-rolled steel coil",
        "plant": "Mumbai DC",
        "on_hand_units": 5400.0,
        "safety_stock_units": 2000.0,
        "reorder_point_units": 4000.0,
    },
)

#: Sample material master records matching the inventory sample.
_SAMPLE_MATERIALS: Sequence[Dict[str, Any]] = (
    {
        "material_id": "MAT-PHARMA-001",
        "description": "Paracetamol API",
        "material_type": "Raw material",
        "base_unit": "KG",
        "category": "Pharmaceutical",
    },
    {
        "material_id": "MAT-CHEM-002",
        "description": "Speciality polymer additive",
        "material_type": "Raw material",
        "base_unit": "KG",
        "category": "Chemicals",
    },
    {
        "material_id": "MAT-ELEC-003",
        "description": "PCB assembly (8-layer)",
        "material_type": "Finished good",
        "base_unit": "EA",
        "category": "Electronics",
    },
    {
        "material_id": "MAT-POLY-004",
        "description": "PET resin grade A",
        "material_type": "Raw material",
        "base_unit": "KG",
        "category": "Polymers",
    },
    {
        "material_id": "MAT-STEEL-005",
        "description": "Cold-rolled steel coil",
        "material_type": "Raw material",
        "base_unit": "KG",
        "category": "Metals",
    },
)

#: Sample purchase orders.
_SAMPLE_PURCHASE_ORDERS: Sequence[Dict[str, Any]] = (
    {
        "po_number": "PO-450001",
        "supplier_id": "SUP001",
        "material_id": "MAT-PHARMA-001",
        "quantity": 25000.0,
        "value_usd": 480000.0,
        "status": "Open",
        "expected_delivery": "2026-12-18",
    },
    {
        "po_number": "PO-450002",
        "supplier_id": "SUP003",
        "material_id": "MAT-ELEC-003",
        "quantity": 6000.0,
        "value_usd": 1350000.0,
        "status": "Open",
        "expected_delivery": "2027-01-09",
    },
    {
        "po_number": "PO-450003",
        "supplier_id": "SUP004",
        "material_id": "MAT-POLY-004",
        "quantity": 18000.0,
        "value_usd": 320000.0,
        "status": "Open",
        "expected_delivery": "2026-12-29",
    },
    {
        "po_number": "PO-450004",
        "supplier_id": "SUP005",
        "material_id": "MAT-STEEL-005",
        "quantity": 4000.0,
        "value_usd": 210000.0,
        "status": "Partially Delivered",
        "expected_delivery": "2026-12-05",
    },
)


class SimulatedSAPConnector(MockConnector):
    """Clearly labelled sample SAP data (``SAP_USE_MOCK`` is true by default)."""

    name = "sap"
    provider = "X FACTOR simulated SAP connector (read-only)"

    def _prov(self) -> Provenance:
        return self.provenance(endpoint="simulated://sap")

    def list_shipments(self) -> List[SAPShipment]:
        provenance = self._prov()
        return [_shipment_from(row, provenance) for row in DEMO_SHIPMENTS]

    def get_shipment(self, *, shipment_id: str) -> Optional[SAPShipment]:
        key = (shipment_id or "").strip()
        if not key:
            raise ValueError("shipment_id must be a non-empty string")
        provenance = self._prov()
        for row in DEMO_SHIPMENTS:
            if str(row["id"]) == key:
                return _shipment_from(row, provenance)
        return None

    def list_suppliers(self) -> List[SAPSupplier]:
        provenance = self._prov()
        return [_supplier_from(row, provenance) for row in DEMO_SUPPLIERS]

    def get_supplier(self, *, supplier_id: str) -> Optional[SAPSupplier]:
        key = (supplier_id or "").strip()
        if not key:
            raise ValueError("supplier_id must be a non-empty string")
        provenance = self._prov()
        for row in DEMO_SUPPLIERS:
            if str(row["id"]) == key:
                return _supplier_from(row, provenance)
        return None

    def list_inventory(self) -> List[SAPInventoryItem]:
        provenance = self._prov()
        return [_inventory_from(row, provenance) for row in _SAMPLE_INVENTORY]

    def get_inventory_item(self, *, material_id: str) -> Optional[SAPInventoryItem]:
        key = (material_id or "").strip()
        if not key:
            raise ValueError("material_id must be a non-empty string")
        provenance = self._prov()
        for row in _SAMPLE_INVENTORY:
            if str(row["material_id"]) == key:
                return _inventory_from(row, provenance)
        return None

    def list_materials(self) -> List[SAPMaterial]:
        provenance = self._prov()
        return [_material_from(row, provenance) for row in _SAMPLE_MATERIALS]

    def get_material(self, *, material_id: str) -> Optional[SAPMaterial]:
        key = (material_id or "").strip()
        if not key:
            raise ValueError("material_id must be a non-empty string")
        provenance = self._prov()
        for row in _SAMPLE_MATERIALS:
            if str(row["material_id"]) == key:
                return _material_from(row, provenance)
        return None

    def list_purchase_orders(self, *, supplier_id: Optional[str] = None) -> List[SAPPurchaseOrder]:
        provenance = self._prov()
        key = (supplier_id or "").strip()
        return [
            _purchase_order_from(row, provenance)
            for row in _SAMPLE_PURCHASE_ORDERS
            if not key or str(row["supplier_id"]) == key
        ]


class HttpSAPConnector(HttpConnector):
    """Live **read-only** SAP adapter (requires SAP_BASE_URL and credentials)."""

    name = "sap"
    provider = "Live SAP system (read-only)"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[HttpJsonClient] = None,
        *,
        profile: Optional[SAPApiProfile] = None,
    ) -> None:
        settings = settings or get_settings()
        self._profile = profile or resolve_sap_profile(settings)
        if client is None:
            tokens = sap_token_provider(settings, scope=settings.SAP_READ_SCOPE)
            if tokens is not None:
                client = SAPHttpClient(
                    connector_name=self.name,
                    base_url=settings.SAP_BASE_URL,
                    timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                    max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
                    tokens=tokens,
                )
            else:
                client = HttpJsonClient(
                    connector_name=self.name,
                    base_url=settings.SAP_BASE_URL,
                    api_key=settings.SAP_CLIENT_SECRET,
                    timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                    max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
                )
        super().__init__(client)

    @property
    def profile(self) -> SAPApiProfile:
        """The prepared SAP API profile this connector is bound to."""
        return self._profile

    def _prov(self, path: str) -> Provenance:
        return self.provenance(endpoint=f"{self.client.base_url}{path}")

    def list_shipments(self) -> List[SAPShipment]:
        path = self._profile.read_path("shipments")
        payload = self.client.get_json(path)
        records = payload.get("value", payload) if isinstance(payload, dict) else payload
        provenance = self._prov(path)
        return [_shipment_from(record, provenance, live=True) for record in records]

    def get_shipment(self, *, shipment_id: str) -> Optional[SAPShipment]:
        path = f"{self._profile.read_path('shipments')}/{shipment_id}"
        try:
            payload = self.client.get_json(path)
        except IntegrationRequestError as exc:
            if _is_not_found(exc):
                return None
            raise
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, Mapping):
            return None
        return _shipment_from(record, self._prov(path), live=True)

    def list_suppliers(self) -> List[SAPSupplier]:
        path = self._profile.read_path("suppliers")
        payload = self.client.get_json(path)
        records = payload.get("value", payload) if isinstance(payload, dict) else payload
        provenance = self._prov(path)
        return [_supplier_from(record, provenance, live=True) for record in records]

    def get_supplier(self, *, supplier_id: str) -> Optional[SAPSupplier]:
        path = f"{self._profile.read_path('suppliers')}/{supplier_id}"
        try:
            payload = self.client.get_json(path)
        except IntegrationRequestError as exc:
            if _is_not_found(exc):
                return None
            raise
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, Mapping):
            return None
        return _supplier_from(record, self._prov(path), live=True)

    def list_inventory(self) -> List[SAPInventoryItem]:
        path = self._profile.read_path("inventory")
        payload = self.client.get_json(path)
        records = payload.get("value", payload) if isinstance(payload, dict) else payload
        provenance = self._prov(path)
        return [_inventory_from(record, provenance, live=True) for record in records]

    def get_inventory_item(self, *, material_id: str) -> Optional[SAPInventoryItem]:
        path = f"{self._profile.read_path('inventory')}/{material_id}"
        try:
            payload = self.client.get_json(path)
        except IntegrationRequestError as exc:
            if _is_not_found(exc):
                return None
            raise
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, Mapping):
            return None
        return _inventory_from(record, self._prov(path), live=True)

    def list_materials(self) -> List[SAPMaterial]:
        path = self._profile.read_path("materials")
        payload = self.client.get_json(path)
        records = payload.get("value", payload) if isinstance(payload, dict) else payload
        provenance = self._prov(path)
        return [_material_from(record, provenance, live=True) for record in records]

    def get_material(self, *, material_id: str) -> Optional[SAPMaterial]:
        path = f"{self._profile.read_path('materials')}/{material_id}"
        try:
            payload = self.client.get_json(path)
        except IntegrationRequestError as exc:
            if _is_not_found(exc):
                return None
            raise
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, Mapping):
            return None
        return _material_from(record, self._prov(path), live=True)

    def list_purchase_orders(self, *, supplier_id: Optional[str] = None) -> List[SAPPurchaseOrder]:
        path = self._profile.read_path("purchase_orders")
        params = {"supplier_id": supplier_id} if supplier_id else None
        payload = self.client.get_json(path, params=params)
        records = payload.get("value", payload) if isinstance(payload, dict) else payload
        provenance = self._prov(path)
        return [_purchase_order_from(record, provenance, live=True) for record in records]


def _shipment_from(row: Mapping[str, Any], provenance: Provenance, *, live: bool = False) -> SAPShipment:
    """Map a SAP record onto the platform's own model (sample or live shape)."""
    return SAPShipment(
        shipment_id=str(row.get("shipment_id") or row.get("id") or ""),
        origin=str(row.get("origin") or ""),
        destination=str(row.get("destination") or ""),
        transport_mode=str(row.get("transport_mode") or ""),
        carrier=str(row.get("carrier") or ""),
        status=str(row.get("status") or ""),
        value_usd=float(row.get("value_usd") or 0.0),
        supplier_id=str(row.get("supplier_id") or ""),
        provenance=provenance,
    )


def _supplier_from(row: Mapping[str, Any], provenance: Provenance, *, live: bool = False) -> SAPSupplier:
    """Map a SAP supplier record onto the platform's own model."""
    return SAPSupplier(
        supplier_id=str(row.get("supplier_id") or row.get("id") or ""),
        name=str(row.get("name") or ""),
        country=str(row.get("country") or ""),
        category=str(row.get("category") or ""),
        risk_tier=str(row.get("risk_tier") or ""),
        provenance=provenance,
    )


def _inventory_from(row: Mapping[str, Any], provenance: Provenance, *, live: bool = False) -> SAPInventoryItem:
    """Map a SAP inventory record onto the platform's own model."""
    return SAPInventoryItem(
        material_id=str(row.get("material_id") or ""),
        description=str(row.get("description") or ""),
        plant=str(row.get("plant") or ""),
        on_hand_units=float(row.get("on_hand_units") or 0.0),
        safety_stock_units=float(row.get("safety_stock_units") or 0.0),
        reorder_point_units=float(row.get("reorder_point_units") or 0.0),
        provenance=provenance,
    )


def _purchase_order_from(
    row: Mapping[str, Any], provenance: Provenance, *, live: bool = False
) -> SAPPurchaseOrder:
    """Map a SAP purchase-order record onto the platform's own model."""
    return SAPPurchaseOrder(
        po_number=str(row.get("po_number") or ""),
        supplier_id=str(row.get("supplier_id") or ""),
        material_id=str(row.get("material_id") or ""),
        quantity=float(row.get("quantity") or 0.0),
        value_usd=float(row.get("value_usd") or 0.0),
        status=str(row.get("status") or ""),
        expected_delivery=str(row.get("expected_delivery") or ""),
        provenance=provenance,
    )


def _material_from(
    row: Mapping[str, Any], provenance: Provenance, *, live: bool = False
) -> SAPMaterial:
    """Map a SAP material-master record onto the platform's own model."""
    return SAPMaterial(
        material_id=str(row.get("material_id") or row.get("id") or ""),
        description=str(row.get("description") or ""),
        material_type=str(row.get("material_type") or ""),
        base_unit=str(row.get("base_unit") or ""),
        category=str(row.get("category") or ""),
        provenance=provenance,
    )


def _is_not_found(exc: IntegrationRequestError) -> bool:
    """True when a read failure means "this record does not exist"."""
    return exc.status_code == 404 or "HTTP 404" in str(exc)


def get_sap_connector(settings: Optional[Settings] = None) -> SAPConnector:
    """Return the SAP connector appropriate for the current configuration.

    Returns the simulated read-only connector while ``SAP_USE_MOCK`` is true (the
    default), and the live read-only adapter when SAP credentials are configured
    and mocks are disabled. The live adapter is bound to the prepared profile
    selected by ``SAP_API_FAMILY``.

    Raises:
        IntegrationNotConfiguredError: Mock mode is off but no SAP credentials
            are configured, or ``SAP_API_FAMILY`` names an unknown profile.
    """
    settings = settings or get_settings()
    if settings.SAP_USE_MOCK:
        logger.info("SAP_USE_MOCK is enabled — using clearly labelled simulated SAP data.")
        return SimulatedSAPConnector()
    if not settings.sap_configured:
        raise IntegrationNotConfiguredError(
            "SAP mock mode is disabled but SAP_BASE_URL / SAP_CLIENT_ID / "
            "SAP_CLIENT_SECRET are not all configured. Configure them or set "
            "SAP_USE_MOCK=true."
        )
    profile = resolve_sap_profile(settings)
    logger.info("SAP read connector using the %s profile.", profile.display_name)
    return HttpSAPConnector(settings, profile=profile)
