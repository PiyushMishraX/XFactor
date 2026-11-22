"""Structured input/output models for the Inventory Rebalancing Agent (Step 3).

The numeric core of the answer — shortage, safety stock, transferable surplus and
the post-transfer availability — is produced by the deterministic engines in
:mod:`app.tools`. Gemini contributes only ``explanation``, ``confidence`` and the
list of information it could not establish.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.disruption_schemas import EvidenceItem


class RebalancingRequest(BaseModel):
    """The material/location whose inventory position must be rebalanced."""

    model_config = ConfigDict(str_strip_whitespace=True)

    material_id: str = Field(min_length=1)
    target_plant: str = Field(
        default="",
        description="Plant to rebalance. When blank, the plant holding the largest stock is used.",
    )
    demand_forecast: float = Field(default=0.0, ge=0, description="Units the plant must cover.")
    committed: float = Field(
        default=0.0, ge=0, description="Units already promised to other demand."
    )
    in_transit: float = Field(default=0.0, ge=0, description="Replenishment already inbound.")
    average_daily_demand: float = Field(default=0.0, ge=0)
    lead_time_days: float = Field(default=0.0, ge=0)
    demand_std_dev: float = Field(default=0.0, ge=0)
    lead_time_std_dev: float = Field(default=0.0, ge=0)
    service_level_percent: float = Field(default=95.0, gt=0)


class WarehousePosition(BaseModel):
    """One plant's stock position for the material being rebalanced."""

    plant: str
    on_hand_units: float
    safety_stock_units: float
    transferable_units: float = Field(
        description="Surplus above the safety stock; the only stock this agent may move."
    )
    is_target: bool


class TransferRecommendation(BaseModel):
    """A single recommended stock transfer."""

    from_plant: str
    to_plant: str
    units: float
    source_on_hand_before: float
    source_on_hand_after: float
    preserves_safety_stock: bool = Field(
        description="Always true: the deterministic allocation never eats into safety stock."
    )


class RejectedTransfer(BaseModel):
    """A transfer that was considered and refused, with the reason."""

    from_plant: str
    units_requested: float
    reason: str


class RebalancingPlan(BaseModel):
    """Validated rebalancing plan — the Step 3 deliverable for Agent 4."""

    material_id: str
    target_plant: str
    shortage_before: float = Field(description="Shortage at the target plant, in units.")
    safety_stock_requirement: int = Field(
        description="Safety stock the plan protects, in whole units."
    )
    required_units: float
    available_units: float
    inventory_positions: List[WarehousePosition] = Field(default_factory=list)
    transfer_recommendations: List[TransferRecommendation] = Field(default_factory=list)
    rejected_transfers: List[RejectedTransfer] = Field(default_factory=list)
    total_transferred_units: float
    shortage_after: float
    availability_improvement_percent: float = Field(
        description="Share of the original shortage closed by the recommended transfers."
    )

    # --- LLM-contributed narrative --------------------------------------
    explanation: str = Field(description="Why this plan is recommended, citing the arithmetic.")
    confidence: float = Field(ge=0.0, le=1.0)

    # --- Provenance and data quality ------------------------------------
    evidence: List[EvidenceItem] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    @field_validator("missing_information", "assumptions")
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
