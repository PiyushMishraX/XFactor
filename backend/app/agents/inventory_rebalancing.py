"""Inventory Rebalancing Agent — AGENT 4 (Step 3).

Design rule enforced here, identical to Step 1: **the LLM explains, deterministic
code decides.**

* the read-only :mod:`app.integrations.sap` connector supplies inventory positions;
* :mod:`app.tools.safety_stock` derives the safety-stock requirement;
* :mod:`app.tools.inventory` computes the shortage and the post-transfer position;
* the transfer allocation itself is plain arithmetic in :meth:`_allocate` and
  **never releases stock below a plant's safety stock**, which is how the roadmap's
  "never transfer unavailable or already committed inventory" rule is enforced —
  not by asking the model to be careful.

The agent recommends only. It never executes a stock transfer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.sap import SAPConnector, SAPInventoryItem
from app.schemas.disruption_schemas import EvidenceItem
from app.schemas.rebalancing_schemas import (
    RebalancingPlan,
    RebalancingRequest,
    RejectedTransfer,
    TransferRecommendation,
    WarehousePosition,
)
from app.services.gemini_service import GeminiService
from app.tools.base import round_units
from app.tools.inventory import InventoryPosition, calculate_inventory_shortage
from app.tools.safety_stock import calculate_safety_stock
from app.utils.tool_recording import call_recorded

logger = logging.getLogger(__name__)


class InventoryRebalancingError(RuntimeError):
    """Raised when the agent cannot produce a usable rebalancing plan."""


SYSTEM_INSTRUCTION = """You are the Inventory Rebalancing Agent inside X FACTOR, an
enterprise supply-chain resilience platform used by a logistics control tower.

You are given ONE material, the deterministic shortage at a plant, the safety stock
the plan must preserve, and the transfers that the deterministic allocator has
already decided are safe.

RULES
1. Explain the plan you are given. Do not invent stock, demand, a plant or a quantity.
2. Quote the supplied numbers exactly. Never propose a transfer that is not in the
   supplied transfer list.
3. Stock below a plant's safety stock is not available to move. Never suggest using it.
4. List everything you could not establish in missing_information. Use an empty list
   when nothing is missing.
5. confidence is your own certainty in this explanation, between 0 and 1.
6. You recommend only. Never state or imply that a transfer has been executed.
"""


#: OpenAPI-subset schema handed to Gemini so the narrative is valid JSON.
LLM_REBALANCING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "Why this rebalancing plan is recommended, citing the numbers.",
        },
        "confidence": {"type": "number", "description": "Certainty between 0 and 1."},
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Facts required for a firmer plan that were not supplied.",
        },
    },
    "required": ["explanation", "confidence", "missing_information"],
}


class LLMRebalancingNarrative(BaseModel):
    """The only fields the model decides for Agent 4."""

    model_config = ConfigDict(str_strip_whitespace=True)

    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_information: List[str] = Field(default_factory=list)


class InventoryRebalancingAgent:
    """Balances one material across plants without breaching any safety stock."""

    def __init__(
        self,
        *,
        gemini: Optional[GeminiService] = None,
        sap: SAPConnector,
    ) -> None:
        self._gemini = gemini or GeminiService()
        self._sap = sap

    def plan(self, request: RebalancingRequest) -> RebalancingPlan:
        """Build a deterministic rebalancing plan for ``request``.

        Raises:
            InventoryRebalancingError: The material is unknown, or the requested
                target plant does not hold it.
            GeminiNotConfiguredError: No Gemini API key is configured.
            GeminiRequestError: Gemini was unreachable or returned unusable output.
        """
        logger.info(
            "Rebalancing analysis for material %s (target plant %s)",
            request.material_id,
            request.target_plant or "auto",
        )

        holdings, source_label = self._holdings(request.material_id)
        target_plant, target_stock = self._select_target(request, holdings)

        safety_stock, safety_source = self._safety_stock_requirement(request, target_stock)
        position = call_recorded(
            "inventory.calculate_inventory_shortage",
            {"material_id": request.material_id, "plant": target_plant},
            calculate_inventory_shortage,
            on_hand=target_stock[0],
            committed=request.committed,
            in_transit=request.in_transit,
            demand_forecast=request.demand_forecast,
            safety_stock=float(safety_stock),
            product=request.material_id,
            warehouse=target_plant,
            summarise=lambda result: (
                f"shortage {result.shortage_units} unit(s) of {result.required_units} required"
            ),
        )

        sources = [
            (plant, stock)
            for plant, stock in holdings.items()
            if plant != target_plant
        ]
        transfers, rejected, total_moved = self._allocate(
            shortage=position.shortage_units,
            target_plant=target_plant,
            sources=sources,
        )
        shortage_after = round_units(max(0.0, position.shortage_units - total_moved))
        improvement = (
            round(total_moved / position.shortage_units * 100.0, 2)
            if position.shortage_units > 0
            else 0.0
        )

        narrative = self._narrate(
            request=request,
            target_plant=target_plant,
            position=position,
            safety_stock=safety_stock,
            safety_source=safety_source,
            transfers=transfers,
            rejected=rejected,
            shortage_after=shortage_after,
            improvement=improvement,
        )

        plan = RebalancingPlan(
            material_id=request.material_id,
            target_plant=target_plant,
            shortage_before=position.shortage_units,
            safety_stock_requirement=safety_stock,
            required_units=position.required_units,
            available_units=position.available_units,
            inventory_positions=self._warehouse_positions(holdings, target_plant),
            transfer_recommendations=transfers,
            rejected_transfers=rejected,
            total_transferred_units=round_units(total_moved),
            shortage_after=shortage_after,
            availability_improvement_percent=improvement,
            explanation=narrative.explanation,
            confidence=round(narrative.confidence, 3),
            evidence=self._build_evidence(request, holdings, source_label),
            missing_information=[
                *narrative.missing_information,
                *self._detected_gaps(target_plant, sources, position, shortage_after),
            ],
            assumptions=[*position.assumptions, f"Safety stock source: {safety_source}."],
        )

        logger.info(
            "Rebalancing plan for %s at %s: shortage %s -> %s after %s unit(s) moved",
            request.material_id,
            target_plant,
            plan.shortage_before,
            plan.shortage_after,
            plan.total_transferred_units,
        )
        return plan

    # -- deterministic inputs ---------------------------------------------

    def _holdings(self, material_id: str) -> Tuple[Dict[str, Tuple[float, float]], str]:
        """Plant -> (on_hand, safety_stock) plus the provenance label of the source rows."""
        items = [item for item in self._sap.list_inventory() if item.material_id == material_id]
        if not items:
            raise InventoryRebalancingError(
                f"Material {material_id!r} is not present in any plant in the inventory "
                f"master data, so no inventory position can be established."
            )
        holdings: Dict[str, Tuple[float, float]] = {}
        for item in items:
            on_hand, safety = holdings.get(item.plant, (0.0, 0.0))
            holdings[item.plant] = (
                on_hand + item.on_hand_units,
                safety + item.safety_stock_units,
            )
        return dict(sorted(holdings.items())), _inventory_label(items[0])

    @staticmethod
    def _select_target(
        request: RebalancingRequest, holdings: Dict[str, Tuple[float, float]]
    ) -> Tuple[str, Tuple[float, float]]:
        """Choose the plant to rebalance: the caller's choice, or the largest stock."""
        if request.target_plant:
            stock = holdings.get(request.target_plant)
            if stock is None:
                raise InventoryRebalancingError(
                    f"Target plant {request.target_plant!r} does not hold material "
                    f"{request.material_id!r}. Plants holding it: "
                    f"{', '.join(holdings)}."
                )
            return request.target_plant, stock
        # Deterministic: largest on-hand stock wins, ties broken by plant name.
        plant = max(holdings, key=lambda name: (holdings[name][0], name))
        return plant, holdings[plant]

    @staticmethod
    def _safety_stock_requirement(
        request: RebalancingRequest, target_stock: Tuple[float, float]
    ) -> Tuple[int, str]:
        """Derive the safety stock the plan must protect, and say where it came from."""
        if request.average_daily_demand > 0 and request.lead_time_days > 0:
            calculated = call_recorded(
                "safety_stock.calculate_safety_stock",
                {
                    "material_id": request.material_id,
                    "average_daily_demand": request.average_daily_demand,
                    "lead_time_days": request.lead_time_days,
                    "service_level_percent": request.service_level_percent,
                },
                calculate_safety_stock,
                average_daily_demand=request.average_daily_demand,
                lead_time_days=request.lead_time_days,
                demand_std_dev=request.demand_std_dev,
                lead_time_std_dev=request.lead_time_std_dev,
                service_level_percent=request.service_level_percent,
                summarise=lambda result: (
                    f"safety stock {result.safety_stock_units} unit(s) at "
                    f"{request.service_level_percent}% service level"
                ),
            )
            return calculated.safety_stock_units, (
                f"calculated by app.tools.safety_stock at a "
                f"{request.service_level_percent}% service level"
            )
        return int(target_stock[1]), "the safety stock recorded against the plant in SAP"

    @staticmethod
    def _allocate(
        *,
        shortage: float,
        target_plant: str,
        sources: Sequence[Tuple[str, Tuple[float, float]]],
    ) -> Tuple[List[TransferRecommendation], List[RejectedTransfer], float]:
        """Greedily cover ``shortage`` from surplus stock, never breaching safety stock.

        Sources are visited largest surplus first (ties broken by plant name) so the
        plan is repeatable. A plant may release only what it holds **above** its
        safety stock; committed stock is never considered releasable because the
        connector does not report it as free stock.
        """
        ordered = sorted(
            sources,
            key=lambda row: (-max(0.0, row[1][0] - row[1][1]), row[0]),
        )

        transfers: List[TransferRecommendation] = []
        rejected: List[RejectedTransfer] = []
        remaining = shortage

        for plant, (on_hand, safety) in ordered:
            transferable = round_units(max(0.0, on_hand - safety))
            if remaining <= 0:
                continue
            if transferable <= 0:
                rejected.append(
                    RejectedTransfer(
                        from_plant=plant,
                        units_requested=round_units(remaining),
                        reason=(
                            f"{plant} holds no stock above its safety stock of "
                            f"{round_units(safety)} units, so nothing can be released."
                        ),
                    )
                )
                continue
            moved = round_units(min(remaining, transferable))
            transfers.append(
                TransferRecommendation(
                    from_plant=plant,
                    to_plant=target_plant,
                    units=moved,
                    source_on_hand_before=round_units(on_hand),
                    source_on_hand_after=round_units(on_hand - moved),
                    preserves_safety_stock=on_hand - moved >= safety,
                )
            )
            remaining = round_units(remaining - moved)

        total_moved = round_units(sum(transfer.units for transfer in transfers))
        return transfers, rejected, total_moved

    @staticmethod
    def _warehouse_positions(
        holdings: Dict[str, Tuple[float, float]], target_plant: str
    ) -> List[WarehousePosition]:
        """Expose every plant's position so the caller can audit the allocation."""
        return [
            WarehousePosition(
                plant=plant,
                on_hand_units=round_units(on_hand),
                safety_stock_units=round_units(safety),
                transferable_units=round_units(max(0.0, on_hand - safety)),
                is_target=plant == target_plant,
            )
            for plant, (on_hand, safety) in holdings.items()
        ]

    # -- LLM call ---------------------------------------------------------

    def _narrate(
        self,
        *,
        request: RebalancingRequest,
        target_plant: str,
        position: InventoryPosition,
        safety_stock: int,
        safety_source: str,
        transfers: Sequence[TransferRecommendation],
        rejected: Sequence[RejectedTransfer],
        shortage_after: float,
        improvement: float,
    ) -> LLMRebalancingNarrative:
        """Ask Gemini to explain the deterministic plan."""
        raw = call_recorded(
            "gemini.generate_structured_json",
            {"agent": "inventory_rebalancing", "material_id": request.material_id},
            self._gemini.generate_structured_json,
            prompt=build_prompt(
                request=request,
                target_plant=target_plant,
                position=position,
                safety_stock=safety_stock,
                safety_source=safety_source,
                transfers=transfers,
                rejected=rejected,
                shortage_after=shortage_after,
                improvement=improvement,
            ),
            response_schema=LLM_REBALANCING_SCHEMA,
            system_instruction=SYSTEM_INSTRUCTION,
            summarise=lambda result: "structured rebalancing narrative returned",
        )
        try:
            return LLMRebalancingNarrative.model_validate(raw)
        except ValidationError as exc:
            raise InventoryRebalancingError(
                f"Gemini returned a rebalancing narrative for {request.material_id} that "
                f"does not match the expected schema: {exc.error_count()} validation "
                f"error(s). First error: {exc.errors()[0]['msg']} at "
                f"{'.'.join(str(part) for part in exc.errors()[0]['loc'])}"
            ) from exc

    # -- deterministic post-processing ------------------------------------

    @staticmethod
    def _build_evidence(
        request: RebalancingRequest,
        holdings: Dict[str, Tuple[float, float]],
        source_label: str,
    ) -> List[EvidenceItem]:
        """Record which plant inventory rows the plan was built from."""
        plants = ", ".join(
            f"{plant} ({round_units(stock[0])} units)" for plant, stock in holdings.items()
        )
        return [
            EvidenceItem(
                source=source_label,
                description=f"Material {request.material_id} positions: {plants}",
            )
        ]

    @staticmethod
    def _detected_gaps(
        target_plant: str,
        sources: Sequence[Tuple[str, Tuple[float, float]]],
        position: InventoryPosition,
        shortage_after: float,
    ) -> List[str]:
        """Gaps the deterministic layer can see, independent of the model."""
        gaps: List[str] = []
        if not sources:
            gaps.append(
                f"{target_plant} is the only plant holding this material, so there is no "
                f"alternative warehouse to rebalance from."
            )
        if position.shortage_units <= 0:
            gaps.append(
                f"{target_plant} has no shortage against the stated demand and safety "
                f"stock, so no transfer is required."
            )
        elif shortage_after > 0:
            gaps.append(
                f"{round_units(shortage_after)} unit(s) of shortage remain even after "
                f"releasing all available surplus stock across plants."
            )
        if position.committed > 0:
            gaps.append(
                f"{round_units(position.committed)} unit(s) at {target_plant} are already "
                f"committed and were excluded from the available stock."
            )
        return gaps


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    *,
    request: RebalancingRequest,
    target_plant: str,
    position: InventoryPosition,
    safety_stock: int,
    safety_source: str,
    transfers: Sequence[TransferRecommendation],
    rejected: Sequence[RejectedTransfer],
    shortage_after: float,
    improvement: float,
) -> str:
    """Render the deterministic facts into the user-turn prompt."""
    lines = [
        "Explain the deterministic inventory rebalancing plan below.",
        "",
        f"MATERIAL: {request.material_id}",
        f"TARGET PLANT: {target_plant}",
        f"ON HAND: {position.on_hand} units",
        f"COMMITTED (not available): {position.committed} units",
        f"IN TRANSIT: {position.in_transit} units",
        f"AVAILABLE: {position.available_units} units",
        f"DEMAND FORECAST: {position.demand_forecast} units",
        f"SAFETY STOCK PROTECTED: {safety_stock} units (from {safety_source})",
        f"REQUIRED: {position.required_units} units",
        f"SHORTAGE BEFORE TRANSFERS: {position.shortage_units} units",
        "",
        "RECOMMENDED TRANSFERS (decided deterministically; do not change these)",
        "---------------------------------------------------------------",
    ]
    if not transfers:
        lines.append("No transfer is recommended.")
    for transfer in transfers:
        lines.append(
            f"{transfer.from_plant} -> {transfer.to_plant}: {transfer.units} units "
            f"(source on hand {transfer.source_on_hand_before} -> "
            f"{transfer.source_on_hand_after}, safety stock preserved: "
            f"{transfer.preserves_safety_stock})"
        )
    if rejected:
        lines.append("")
        lines.append("TRANSFERS REFUSED (would breach safety stock)")
        for rejection in rejected:
            lines.append(f"{rejection.from_plant}: {rejection.reason}")
    lines.extend(
        [
            "",
            f"SHORTAGE AFTER TRANSFERS: {shortage_after} units",
            f"AVAILABILITY IMPROVEMENT: {improvement}%",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inventory_label(item: SAPInventoryItem) -> str:
    """Provenance label for one inventory row, keeping simulated data obvious."""
    return item.provenance.label
