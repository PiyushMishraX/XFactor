"""Structured input/output models for the Rerouting & Logistics Agent (Step 3).

Two layers are kept separate, exactly as in Step 1:

* ``ReroutingRequest``  — the move that must be re-planned, plus the disruption
  context the caller already knows.
* ``ReroutingAnalysis`` — the agent's validated answer. Every number in it
  (``total_cost_usd``, ``total_days``, ``risk_score``, ``weighted_score``) is
  produced by the deterministic engines in :mod:`app.tools`; the LLM only
  contributes ``explanation``, ``route_risks``, ``confidence`` and the list of
  information it could not establish.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.disruption_schemas import EvidenceItem


class ReroutingRequest(BaseModel):
    """The lane movement to be re-planned, and the disruption affecting it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    disruption_id: str = Field(min_length=1, description="Links the analysis to an event.")
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    cargo_value_usd: float = Field(gt=0)
    container_count: float = Field(default=1.0, gt=0)
    current_carrier: str = Field(
        default="", description="Incumbent carrier, used to mark the 'continue as-is' option."
    )
    current_mode: str = Field(default="Sea", description="Transport mode currently in use.")
    congestion_days: float = Field(default=0.0, ge=0)
    weather_delay_days: float = Field(default=0.0, ge=0)
    tariff_rate_percent: float = Field(default=0.0, ge=0)
    risk_factors: List[str] = Field(
        default_factory=list,
        description="Risk factor value strings carried over from the disruption assessment.",
    )
    candidate_modes: List[str] = Field(
        default_factory=list,
        description="Restrict the search to these transport modes. Empty means 'all modes'.",
    )


class ReroutingOption(BaseModel):
    """One deterministically scored logistics alternative."""

    route_id: str
    carrier: str
    transport_mode: str
    distance_km: float
    total_cost_usd: float
    total_days: float
    risk_score: int
    carrier_reliability: float
    weighted_score: float = Field(description="0..1 scorecard total, higher is better.")
    rank: int = Field(description="1-based position from the deterministic ranking.")
    is_current_route: bool = Field(
        description="True when this option matches the incumbent carrier and mode."
    )
    congestion_days: float = 0.0
    weather_delay_days: float = 0.0


class ReroutingAnalysis(BaseModel):
    """Validated rerouting analysis — the Step 3 deliverable for Agent 3."""

    disruption_id: str
    origin: str
    destination: str
    lane_distance_km: float
    lane_is_estimated: bool = Field(
        description="True when the mapping layer derived the lane rather than knowing it."
    )
    ranked_routes: List[ReroutingOption] = Field(default_factory=list)
    recommended_route_id: Optional[str] = Field(
        default=None, description="Top-ranked option, chosen by the ranking engine."
    )
    current_route_rank: Optional[int] = Field(
        default=None, description="Rank of the incumbent option, or None when unknown."
    )

    # --- LLM-contributed narrative --------------------------------------
    explanation: str = Field(description="Why the deterministic ranking came out this way.")
    route_risks: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    # --- Provenance and data quality ------------------------------------
    evidence: List[EvidenceItem] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)

    @field_validator("route_risks", "missing_information")
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
