"""Structured input/output models for the Disruption Sensing Agent (Step 1).

Three layers are kept deliberately separate:

* ``DisruptionReport``   — the unstructured input handed to the agent.
* ``LLMAssessment``      — the only fields the LLM is allowed to decide. It
  reports *observable facts*, never a risk score.
* ``DisruptionAssessment`` — the agent's final, validated answer. Numeric fields
  (``risk_score``, ``severity``) are filled in by deterministic code, and
  shipment/supplier references are filled in only after a PostgreSQL lookup.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------


class DisruptionCategory(str, Enum):
    """The eight disruption categories the platform must support."""

    MARITIME_SECURITY_THREAT = "Maritime Security Threat"
    SEVERE_WEATHER = "Severe Weather"
    GEOPOLITICAL_DEVELOPMENT = "Geopolitical Development"
    TARIFF_CHANGE = "Tariff Change"
    PORT_CONGESTION = "Port Congestion"
    SUPPLIER_FAILURE = "Supplier Failure"
    TRANSPORTATION_DELAY = "Transportation Delay"
    INFRASTRUCTURE_DISRUPTION = "Infrastructure Disruption"
    #: Report is not a supply-chain disruption at all.
    UNRELATED = "Unrelated"


#: Every category except ``UNRELATED`` — used to assert coverage in tests.
DISRUPTION_CATEGORIES: tuple[DisruptionCategory, ...] = tuple(
    category for category in DisruptionCategory if category is not DisruptionCategory.UNRELATED
)


class Severity(str, Enum):
    """Severity band. Always derived deterministically from the risk score."""

    NEGLIGIBLE = "Negligible"
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    CRITICAL = "Critical"


class RiskFactor(str, Enum):
    """Evidence-based risk signals the LLM may *observe* in a report.

    The LLM selects which factors are present; the numeric weight of each factor
    lives in ``app.services.risk_scoring`` — never in the prompt.
    """

    ACTIVE_PHYSICAL_THREAT = "Active physical threat to vessels, cargo or personnel"
    ROUTE_CLOSURE_OR_DIVERSION = "Route closure or forced diversion"
    CONFIRMED_DAMAGE_OR_LOSS = "Confirmed damage, casualties or cargo loss"
    CARRIER_SERVICE_SUSPENSION = "Carrier suspended or reduced service"
    PORT_CLOSURE_OR_SEVERE_CONGESTION = "Port closure or severe congestion"
    GOVERNMENT_RESTRICTION = "Government or regulatory restriction in force"
    SUPPLIER_OPERATIONS_HALTED = "Supplier operations halted or insolvent"
    INFRASTRUCTURE_OUTAGE = "Critical infrastructure or utility outage"
    REPORTED_COST_INCREASE = "Reported cost increase"
    REPORTED_SCHEDULE_DELAY = "Reported schedule delay"
    HIGH_VOLUME_TRADE_LANE = "Disruption affects a high-volume trade lane"
    ONGOING_OR_UNRESOLVED = "Disruption is ongoing or unresolved"


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class DisruptionReport(BaseModel):
    """An unstructured disruption report submitted for analysis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: Optional[str] = Field(
        default=None,
        description="Caller-supplied identifier. Derived deterministically when absent.",
    )
    headline: str = Field(min_length=1, description="Short title of the report.")
    description: str = Field(
        default="",
        description="Body text. May be empty for an incomplete report.",
    )
    source: str = Field(
        min_length=1,
        description="Where the report came from, e.g. 'Reuters', 'internal alert feed'.",
    )
    source_url: Optional[str] = None
    reported_at: Optional[datetime] = Field(
        default=None,
        description="When the event was reported. Omitted values are recorded as missing.",
    )
    location_hint: Optional[str] = Field(
        default=None,
        description="Optional caller-supplied geography to help the analyst.",
    )

    @property
    def full_text(self) -> str:
        """Headline and body combined into the single text block given to the LLM."""
        body = self.description.strip()
        return f"{self.headline.strip()}\n\n{body}" if body else self.headline.strip()

    def derive_event_id(self) -> str:
        """Return the caller's ``event_id`` or a stable hash-derived fallback.

        The fallback is deterministic: the same report always yields the same id,
        so workflow state can be keyed on it without inventing data.
        """
        if self.event_id:
            return self.event_id
        seed = f"{self.source}|{self.headline}|{self.reported_at.isoformat() if self.reported_at else ''}"
        return f"EV-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:8].upper()}"


# ---------------------------------------------------------------------------
# LLM output (the only fields the model decides)
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A verifiable pointer back to the source material."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source: str = Field(min_length=1)
    description: str = Field(min_length=1)
    url: Optional[str] = None
    timestamp: Optional[datetime] = None


class LLMAssessment(BaseModel):
    """Structured analysis returned by Gemini.

    Deliberately contains no ``risk_score`` or ``severity``: those are computed
    from ``risk_factors`` and the validated database references by
    ``app.services.risk_scoring``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    is_supply_chain_disruption: bool = Field(
        description="False for news that is not a supply-chain disruption."
    )
    disruption_type: DisruptionCategory
    description: str = Field(min_length=1, description="Neutral one-sentence summary.")
    affected_locations: List[str] = Field(
        default_factory=list,
        description="Regions, countries, ports, canals or straits named or implied.",
    )
    risk_factors: List[RiskFactor] = Field(
        default_factory=list,
        description="Observable signals present in the report.",
    )
    potential_impact: List[str] = Field(default_factory=list)
    mentioned_shipment_ids: List[str] = Field(
        default_factory=list,
        description="Shipment ids referenced by the text. Not trusted until validated.",
    )
    mentioned_supplier_ids: List[str] = Field(default_factory=list)
    recommended_next_action: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)

    @field_validator(
        "affected_locations",
        "potential_impact",
        "mentioned_shipment_ids",
        "mentioned_supplier_ids",
        "missing_information",
        "contradictions",
    )
    @classmethod
    def _drop_blank_entries(cls, values: List[str]) -> List[str]:
        """Drop empty strings while preserving order and removing duplicates."""
        seen: set[str] = set()
        cleaned: List[str] = []
        for value in values:
            item = value.strip()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item)
        return cleaned


# ---------------------------------------------------------------------------
# Agent output
# ---------------------------------------------------------------------------


class DisruptionAssessment(BaseModel):
    """Validated disruption assessment — the Step 1 deliverable.

    ``risk_score``/``severity`` come from deterministic scoring.
    ``affected_shipments``/``affected_suppliers`` contain **only** identifiers
    that exist in PostgreSQL.
    """

    event_id: str
    disruption_type: DisruptionCategory
    description: str
    location: str = Field(
        description="Primary affected location, or 'Unknown' when evidence is insufficient."
    )
    severity: Severity
    risk_score: int = Field(ge=0, le=100)
    affected_shipments: List[str] = Field(default_factory=list)
    affected_suppliers: List[str] = Field(default_factory=list)
    potential_impact: List[str] = Field(default_factory=list)
    recommended_next_action: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[EvidenceItem] = Field(default_factory=list)

    # --- Provenance -----------------------------------------------------
    is_supply_chain_disruption: bool
    source: str
    source_url: Optional[str] = None
    reported_at: Optional[datetime] = None
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Deterministic scoring transparency -----------------------------
    risk_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Points contributed by each weighted risk factor.",
    )
    reference_contributions: Dict[str, int] = Field(
        default_factory=dict,
        description="Points added for validated shipment/supplier exposure.",
    )

    # --- Data-quality handling ------------------------------------------
    affected_locations: List[str] = Field(default_factory=list)
    unvalidated_shipment_references: List[str] = Field(
        default_factory=list,
        description="Ids claimed by the LLM that do not exist in PostgreSQL.",
    )
    unvalidated_supplier_references: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
