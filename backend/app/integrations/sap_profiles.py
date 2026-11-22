"""Prepared SAP API profiles (Step 7).

X FACTOR talks to SAP through one of four prepared connector profiles. A profile
names the API family, its transport and the relative read/write paths the
connector should use. Selecting a profile is configuration only — the connector
logic is identical for all four.

Profiles
--------
* ``s4hana`` — SAP S/4HANA OData services (the default).
* ``business_accelerator_hub`` — SAP Business Accelerator Hub REST/OData APIs.
* ``btp`` — APIs exposed through SAP Business Technology Platform.
* ``integration_suite`` — SAP Integration Suite / CPI mediated routes.

Honesty
-------
These are *prepared* profiles: the relative paths are gateway defaults that must
be confirmed against the tenant's actual service catalogue. No live SAP tenant is
contacted in this project; ``SAP_USE_MOCK`` stays true and every response is
labelled simulated. A profile never claims that a capability is available in a
specific tenant — ``supports_write`` describes the connector's capability, not a
verified entitlement.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import Settings, get_settings
from app.integrations.base import IntegrationNotConfiguredError


class SAPApiFamily(str, Enum):
    """The four SAP API families prepared in this step."""

    S4HANA = "s4hana"
    BUSINESS_ACCELERATOR_HUB = "business_accelerator_hub"
    BTP = "btp"
    INTEGRATION_SUITE = "integration_suite"


class SAPTransport(str, Enum):
    """How the profile exposes SAP data."""

    ODATA_V2 = "odata_v2"
    ODATA_V4 = "odata_v4"
    REST = "rest"


#: Read capabilities every profile must provide.
READ_CAPABILITIES = (
    "shipments",
    "suppliers",
    "inventory",
    "purchase_orders",
    "materials",
)

#: Write capabilities the connector can perform where the tenant supports them.
WRITE_CAPABILITIES = (
    "shipment_plan_update",
    "inventory_transfer",
    "operational_change",
)


class SAPApiProfile(BaseModel):
    """One prepared SAP API family and its relative service paths."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    family: SAPApiFamily
    display_name: str
    description: str
    transport: SAPTransport
    authentication: str = Field(
        description="How the profile authenticates, in operator terms."
    )
    base_url_env: str = "SAP_BASE_URL"
    read_paths: Dict[str, str] = Field(
        description="Relative path per read capability in READ_CAPABILITIES."
    )
    write_paths: Dict[str, str] = Field(
        description="Relative path per write capability in WRITE_CAPABILITIES."
    )
    supports_write: bool = True
    notes: str = ""

    def read_path(self, capability: str) -> str:
        """Return the relative read path for ``capability``."""
        try:
            return self.read_paths[capability]
        except KeyError as exc:
            raise IntegrationNotConfiguredError(
                f"The {self.family.value} profile does not declare a read path for "
                f"{capability!r}."
            ) from exc

    def write_path(self, capability: str) -> str:
        """Return the relative write path for ``capability``."""
        if not self.supports_write:
            raise IntegrationNotConfiguredError(
                f"The {self.family.value} profile does not support write operations."
            )
        try:
            return self.write_paths[capability]
        except KeyError as exc:
            raise IntegrationNotConfiguredError(
                f"The {self.family.value} profile does not declare a write path for "
                f"{capability!r}."
            ) from exc


_S4HANA = SAPApiProfile(
    family=SAPApiFamily.S4HANA,
    display_name="SAP S/4HANA",
    description=(
        "Read and write supply-chain data through the S/4HANA OData services "
        "published by the tenant."
    ),
    transport=SAPTransport.ODATA_V2,
    authentication="OAuth2 client credentials (SAP_AUTH_URL) or gateway API key",
    read_paths={
        "shipments": "/sap/opu/odata/sap/API_SHIPMENT_SRV/Shipments",
        "suppliers": "/sap/opu/odata/sap/API_BUSINESS_PARTNER/Suppliers",
        "inventory": "/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/Stock",
        "purchase_orders": "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/PurchaseOrders",
        "materials": "/sap/opu/odata/sap/API_PRODUCT_SRV/Products",
    },
    write_paths={
        "shipment_plan_update": "/sap/opu/odata/sap/API_SHIPMENT_SRV/PlanUpdates",
        "inventory_transfer": "/sap/opu/odata/sap/API_INVENTORY_TRANSFER_SRV/TransferRequests",
        "operational_change": "/sap/opu/odata/sap/API_OPERATIONAL_CHANGE_SRV/Changes",
    },
    notes=(
        "Requires the matching OData services to be activated and the OAuth client "
        "to be scoped for the read/write services used."
    ),
)

_BUSINESS_ACCELERATOR_HUB = SAPApiProfile(
    family=SAPApiFamily.BUSINESS_ACCELERATOR_HUB,
    display_name="SAP Business Accelerator Hub",
    description=(
        "Consume published SAP APIs described on the Business Accelerator Hub "
        "through the gateway that fronts them."
    ),
    transport=SAPTransport.REST,
    authentication="OAuth2 client credentials or gateway API key",
    read_paths={
        "shipments": "/api/shipment/v1/shipments",
        "suppliers": "/api/supplier/v1/suppliers",
        "inventory": "/api/inventory/v1/stock",
        "purchase_orders": "/api/purchase-order/v1/orders",
        "materials": "/api/material/v1/materials",
    },
    write_paths={
        "shipment_plan_update": "/api/shipment-plan/v1/plans",
        "inventory_transfer": "/api/inventory/v1/transfers",
        "operational_change": "/api/change/v1/requests",
    },
    notes=(
        "API availability depends on the API sandbox or tenant subscription; the "
        "write APIs must be enabled explicitly for the client."
    ),
)

_BTP = SAPApiProfile(
    family=SAPApiFamily.BTP,
    display_name="SAP Business Technology Platform",
    description=(
        "Reach SAP operational data through a BTP service instance or destination "
        "that brokers the underlying S/4HANA services."
    ),
    transport=SAPTransport.REST,
    authentication="OAuth2 client credentials issued by the BTP service instance",
    read_paths={
        "shipments": "/btp/s4/shipments",
        "suppliers": "/btp/s4/suppliers",
        "inventory": "/btp/s4/inventory",
        "purchase_orders": "/btp/s4/purchase-orders",
        "materials": "/btp/s4/materials",
    },
    write_paths={
        "shipment_plan_update": "/btp/s4/shipment-plans",
        "inventory_transfer": "/btp/s4/inventory-transfers",
        "operational_change": "/btp/s4/operational-changes",
    },
    notes=(
        "The BTP destination determines the effective back-end permissions, so the "
        "read and write scopes must be granted on the destination as well."
    ),
)

_INTEGRATION_SUITE = SAPApiProfile(
    family=SAPApiFamily.INTEGRATION_SUITE,
    display_name="SAP Integration Suite",
    description=(
        "Send and receive SAP data through Integration Suite / CPI mediated routes, "
        "which normalise payloads across back-end systems."
    ),
    transport=SAPTransport.REST,
    authentication="OAuth2 client credentials for the Integration Suite runtime",
    read_paths={
        "shipments": "/cpi/s4/shipments",
        "suppliers": "/cpi/s4/suppliers",
        "inventory": "/cpi/s4/inventory",
        "purchase_orders": "/cpi/s4/purchase-orders",
        "materials": "/cpi/s4/materials",
    },
    write_paths={
        "shipment_plan_update": "/cpi/s4/shipment-plans",
        "inventory_transfer": "/cpi/s4/inventory-transfers",
        "operational_change": "/cpi/s4/operational-changes",
    },
    notes=(
        "The integration flow must expose the routes above and enforce the same "
        "approval evidence the connector sends."
    ),
)

#: Every prepared profile, keyed by its ``SAP_API_FAMILY`` value.
SAP_API_PROFILES: Mapping[str, SAPApiProfile] = {
    profile.family.value: profile
    for profile in (
        _S4HANA,
        _BUSINESS_ACCELERATOR_HUB,
        _BTP,
        _INTEGRATION_SUITE,
    )
}


def get_sap_profile(family: str) -> SAPApiProfile:
    """Return the prepared profile for ``family``.

    Raises:
        IntegrationNotConfiguredError: ``family`` is not one of the prepared
            profiles.
    """
    key = (family or "").strip().lower()
    profile = SAP_API_PROFILES.get(key)
    if profile is None:
        options = ", ".join(sorted(SAP_API_PROFILES))
        raise IntegrationNotConfiguredError(
            f"Unknown SAP API family {family!r}. Set SAP_API_FAMILY to one of: {options}."
        )
    return profile


def resolve_sap_profile(settings: Settings | None = None) -> SAPApiProfile:
    """Return the profile selected by ``SAP_API_FAMILY``."""
    settings = settings or get_settings()
    return get_sap_profile(settings.SAP_API_FAMILY)


__all__ = [
    "READ_CAPABILITIES",
    "SAP_API_PROFILES",
    "WRITE_CAPABILITIES",
    "SAPApiFamily",
    "SAPApiProfile",
    "SAPTransport",
    "get_sap_profile",
    "resolve_sap_profile",
]
