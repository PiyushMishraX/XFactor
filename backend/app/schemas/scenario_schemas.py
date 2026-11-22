"""Structured input/output models for the Scenario Planning Agent (Step 3).

The agent composes Agent 3 (rerouting) and Agent 4 (inventory rebalancing) and then
scores every recovery alternative with the same deterministic engine Agent 3 uses.
Gemini contributes only the narrative: ``recommendation_rationale``, the per-scenario
assessments, ``confidence`` and the list of information it could not establish.
``rank`` and ``weighted_score`` are never model output.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.disruption_schemas import EvidenceItem
from app.schemas.rebalancing_schemas import RebalancingRequest


class ScenarioFeasibility(str, Enum):
    """Affordability of a scenario against the caller's available budget."""

    FEASIBLE = "Feasible"
    FEASIBLE_WITH_APPROVAL = "Feasible subject to finance approval"
    UNKNOWN = "Affordability unknown"


class ScenarioRevision(BaseModel):
    """Structured feedback asking the Scenario Planning Agent for a revised plan.

    Step 5 uses this as the task payload when deterministic evaluation (or the
    Compliance & Audit Agent) rejects an alternative: the rejected scenario ids
    and carriers are excluded before the remaining alternatives are re-scored,
    so the revision is driven by real validation results rather than a prompt.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    round: int = Field(ge=1, description="1-based revision round.")
    rejected_scenario_ids: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    excluded_carriers: List[str] = Field(default_factory=list)
    feedback: str = Field(default="", description="Human-readable reason for the revision.")


class ScenarioRequest(BaseModel):
    """The disruption, the affected lane, and the analyses the agent should request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1)
    disruption_type: str = Field(min_length=1)
    location: str = ""
    severity: str = ""
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    cargo_value_usd: float = Field(gt=0)
    container_count: float = Field(default=1.0, gt=0)
    transport_mode: str = "Sea"
    current_carrier: str = ""
    available_budget_usd: float = Field(default=0.0, ge=0)
    congestion_days: float = Field(default=0.0, ge=0)
    weather_delay_days: float = Field(default=0.0, ge=0)
    tariff_rate_percent: float = Field(default=0.0, ge=0)
    risk_factors: List[str] = Field(default_factory=list)
    inventory: Optional[RebalancingRequest] = Field(
        default=None,
        description="When supplied, the agent requests a full inventory impact analysis.",
    )


class ScenarioComparison(BaseModel):
    """One recovery alternative, scored and ranked deterministically."""

    scenario_id: str
    name: str
    approach: str = Field(
        description="Continue existing route / change transport mode / change carrier."
    )
    carrier: str
    transport_mode: str
    distance_km: float
    total_cost_usd: float
    total_days: float
    risk_score: int
    carrier_reliability: float
    weighted_score: float = Field(description="0..1 scorecard total, higher is better.")
    feasibility: ScenarioFeasibility
    rank: int = Field(description="1-based position after feasibility tiering.")
    notes: List[str] = Field(default_factory=list)


class ScenarioPlan(BaseModel):
    """Validated scenario plan — the Step 3 deliverable for Agent 2."""

    event_id: str
    disruption_type: str
    severity: str
    scenarios: List[ScenarioComparison] = Field(default_factory=list)
    recommended_scenario_id: Optional[str] = Field(
        default=None, description="Top-ranked feasible scenario, or None when none could be built."
    )

    # --- LLM-contributed narrative --------------------------------------
    recommendation_rationale: str = Field(
        description="Why the recommended scenario is preferable, citing the deterministic numbers."
    )
    confidence: float = Field(ge=0.0, le=1.0)

    # --- Requested analyses (Agents 3 and 4) -----------------------------
    logistics_summary: str = ""
    inventory_impact: str = ""
    inventory_shortage_after: Optional[float] = None
    inventory_can_cover_disruption: bool = False

    # --- Deltas of the recommendation against the incumbent option -------
    cost_delta_vs_current_usd: Optional[float] = None
    days_delta_vs_current: Optional[float] = None

    # --- Revision provenance (Step 5) -----------------------------------
    revision_round: int = Field(
        default=0, ge=0, description="0 for a first plan, N for the N-th revision."
    )
    rejected_scenario_ids: List[str] = Field(
        default_factory=list, description="Alternatives a revision excluded from this plan."
    )

    # --- Provenance and data quality ------------------------------------
    evidence: List[EvidenceItem] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)

    @field_validator("missing_information")
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
