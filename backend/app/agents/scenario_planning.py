"""Scenario Planning Agent — AGENT 2 (Step 3).

Design rule enforced here, identical to Step 1: **the LLM explains, deterministic
code decides.**

The agent is the first place two other agents are *requested* rather than duplicated:

* it asks :class:`~app.agents.rerouting_logistics.ReroutingLogisticsAgent` for the
  route and logistics analysis of the affected lane;
* it asks :class:`~app.agents.inventory_rebalancing.InventoryRebalancingAgent` for the
  inventory impact analysis when the caller supplies an inventory request.

It then turns those results into **at least three recovery alternatives** — continue on
the existing route, change transport mode, change carrier — and scores every one of
them with :func:`app.tools.route_optimization.rank_routes`, the same deterministic
engine Agent 3 uses. Gemini writes only the rationale, the per-scenario assessment and
the confidence; it never supplies a cost, a transit time or a rank.

This is *not* the central supervisor: that arrives in Step 4 as a LangGraph workflow.
The agent plans only; it never executes a recovery action.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.inventory_rebalancing import InventoryRebalancingAgent
from app.agents.rerouting_logistics import ReroutingLogisticsAgent
from app.schemas.disruption_schemas import EvidenceItem
from app.schemas.rerouting_schemas import ReroutingAnalysis, ReroutingRequest
from app.schemas.rebalancing_schemas import RebalancingPlan
from app.schemas.scenario_schemas import (
    ScenarioComparison,
    ScenarioFeasibility,
    ScenarioPlan,
    ScenarioRequest,
)
from app.services.gemini_service import GeminiService
from app.tools.base import round_units
from app.tools.route_optimization import RouteOption, RouteRanking, rank_routes

logger = logging.getLogger(__name__)


class ScenarioPlanningError(RuntimeError):
    """Raised when the agent cannot produce a usable scenario plan."""


SYSTEM_INSTRUCTION = """You are the Scenario Planning Agent inside X FACTOR, an
enterprise supply-chain resilience platform used by a logistics control tower.

You are given a disruption, the affected lane, a set of recovery alternatives that have
already been costed, timed, risk-scored and ranked by deterministic engines, plus the
results of a route/logistics analysis and an inventory impact analysis.

RULES
1. Explain the deterministic ranking you are given. Do not re-rank, re-price or re-time.
2. Quote the supplied numbers exactly. Never invent a cost, a transit time, a risk score,
   a carrier, a route or a supplier.
3. recommendation_rationale must explain why the top-ranked scenario is preferable,
   citing its cost, transit time and risk against the alternatives.
4. scenario_assessments must contain one entry per supplied scenario id, describing that
   scenario's trade-offs and constraints. Use only the supplied scenario ids.
5. List everything you could not establish in missing_information. Use an empty list when
   nothing is missing.
6. confidence is your own certainty in this plan, between 0 and 1.
7. You plan only. Never state or imply that a recovery action has been executed.
"""


#: OpenAPI-subset schema handed to Gemini so the narrative is valid JSON.
LLM_SCENARIO_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommendation_rationale": {
            "type": "string",
            "description": "Why the top-ranked scenario is preferable, citing the numbers.",
        },
        "scenario_assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scenario_id": {"type": "string"},
                    "assessment": {"type": "string"},
                },
                "required": ["scenario_id", "assessment"],
            },
            "description": "One trade-off assessment per supplied scenario id.",
        },
        "confidence": {"type": "number", "description": "Certainty between 0 and 1."},
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Facts required for a firmer plan that were not supplied.",
        },
    },
    "required": [
        "recommendation_rationale",
        "scenario_assessments",
        "confidence",
        "missing_information",
    ],
}


class ScenarioAssessment(BaseModel):
    """One per-scenario trade-off note contributed by the model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_id: str = Field(min_length=1)
    assessment: str = Field(min_length=1)


class LLMScenarioNarrative(BaseModel):
    """The only fields the model decides for Agent 2."""

    model_config = ConfigDict(str_strip_whitespace=True)

    recommendation_rationale: str = Field(min_length=1)
    scenario_assessments: List[ScenarioAssessment] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_information: List[str] = Field(default_factory=list)


#: Feasibility tiers used for the deterministic final ordering. Lower sorts first.
_FEASIBILITY_TIER: Dict[ScenarioFeasibility, int] = {
    ScenarioFeasibility.FEASIBLE: 0,
    ScenarioFeasibility.FEASIBLE_WITH_APPROVAL: 1,
    ScenarioFeasibility.UNKNOWN: 2,
}

_CONTINUE_APPROACH = "Continue existing route"
_MODE_CHANGE_APPROACH = "Change transport mode"
_CARRIER_CHANGE_APPROACH = "Change carrier"


class ScenarioPlanningAgent:
    """Builds, scores and ranks recovery scenarios for one disruption."""

    def __init__(
        self,
        *,
        gemini: Optional[GeminiService] = None,
        rerouting: ReroutingLogisticsAgent,
        rebalancing: InventoryRebalancingAgent,
    ) -> None:
        self._gemini = gemini or GeminiService()
        self._rerouting = rerouting
        self._rebalancing = rebalancing

    def plan(self, request: ScenarioRequest) -> ScenarioPlan:
        """Produce a ranked recovery plan for ``request``.

        Raises:
            GeminiNotConfiguredError: No Gemini API key is configured.
            GeminiRequestError: Gemini was unreachable or returned unusable output.
            ScenarioPlanningError: Gemini's output did not satisfy the schema.
            ReroutingLogisticsError: The requested route analysis failed.
            InventoryRebalancingError: The requested inventory analysis failed.
        """
        logger.info(
            "Scenario planning for event %s: %s -> %s",
            request.event_id,
            request.origin,
            request.destination,
        )

        logistics = self._rerouting.analyse(self._rerouting_request(request))
        inventory = self._inventory_plan(request)

        drafts = self._draft_scenarios(request, logistics)
        ranking = rank_routes(options=[draft.option for draft in drafts])
        scenarios = self._assemble(request, drafts, ranking)

        recommended = scenarios[0] if scenarios else None
        incumbent = next((item for item in scenarios if item.approach == _CONTINUE_APPROACH), None)
        narrative = self._narrate(request, logistics, inventory, scenarios, recommended)
        self._attach_assessments(scenarios, narrative)

        plan = ScenarioPlan(
            event_id=request.event_id,
            disruption_type=request.disruption_type,
            severity=request.severity,
            scenarios=scenarios,
            recommended_scenario_id=recommended.scenario_id if recommended else None,
            recommendation_rationale=narrative.recommendation_rationale,
            confidence=round(narrative.confidence, 3),
            logistics_summary=logistics.explanation,
            inventory_impact=inventory.explanation if inventory else "",
            inventory_shortage_after=inventory.shortage_after if inventory else None,
            inventory_can_cover_disruption=bool(inventory and inventory.shortage_after <= 0),
            cost_delta_vs_current_usd=(
                round(recommended.total_cost_usd - incumbent.total_cost_usd, 2)
                if recommended and incumbent
                else None
            ),
            days_delta_vs_current=(
                round_units(recommended.total_days - incumbent.total_days)
                if recommended and incumbent
                else None
            ),
            evidence=self._build_evidence(logistics, inventory, len(scenarios)),
            missing_information=self._missing_information(
                logistics, inventory, scenarios, narrative
            ),
        )

        logger.info(
            "Scenario plan for %s: %s scenario(s), recommended=%s",
            request.event_id,
            len(plan.scenarios),
            plan.recommended_scenario_id,
        )
        return plan

    # -- requested analyses ------------------------------------------------

    def _rerouting_request(self, request: ScenarioRequest) -> ReroutingRequest:
        """Translate the scenario request into Agent 3's input."""
        return ReroutingRequest(
            disruption_id=request.event_id,
            origin=request.origin,
            destination=request.destination,
            cargo_value_usd=request.cargo_value_usd,
            container_count=request.container_count,
            current_carrier=request.current_carrier,
            current_mode=request.transport_mode,
            congestion_days=request.congestion_days,
            weather_delay_days=request.weather_delay_days,
            tariff_rate_percent=request.tariff_rate_percent,
            risk_factors=list(request.risk_factors),
        )

    def _inventory_plan(self, request: ScenarioRequest) -> Optional[RebalancingPlan]:
        """Request the inventory impact analysis when the caller asked for one."""
        if request.inventory is None:
            return None
        return self._rebalancing.plan(request.inventory)

    # -- deterministic scenario construction -------------------------------

    def _draft_scenarios(
        self, request: ScenarioRequest, logistics: ReroutingAnalysis
    ) -> List["_Draft"]:
        """Build every recovery alternative the data supports, in a stable order."""
        incumbent_option = next(
            (option for option in logistics.ranked_routes if option.is_current_route), None
        )
        if incumbent_option is not None:
            incumbent_carrier = incumbent_option.carrier
            incumbent_mode = incumbent_option.transport_mode
            incumbent_reliability = incumbent_option.carrier_reliability
        else:
            incumbent_carrier = request.current_carrier or "Incumbent"
            incumbent_mode = request.transport_mode
            incumbent_reliability = 1.0

        drafts: List[_Draft] = []

        continue_notes = [
            "Keeps the carrier and transport mode already in service on this lane.",
        ]
        if incumbent_option is None:
            continue_notes.append(
                "The incumbent carrier is not present in the carrier master data, so full "
                "reliability was assumed when scoring this scenario."
            )
        if request.congestion_days or request.weather_delay_days:
            continue_notes.append(
                f"Inherits the reported {round_units(request.congestion_days)} day(s) of "
                f"congestion and {round_units(request.weather_delay_days)} day(s) of weather "
                f"delay."
            )
        drafts.append(
            _Draft(
                scenario_id="SC1",
                name="Continue with the existing route and carrier",
                approach=_CONTINUE_APPROACH,
                option=self._route_option(
                    "SC1", request, logistics, incumbent_carrier, incumbent_mode, incumbent_reliability
                ),
                notes=continue_notes,
            )
        )

        alternative_mode = next(
            (
                option
                for option in logistics.ranked_routes
                if option.transport_mode != incumbent_mode
            ),
            None,
        )
        if alternative_mode is not None:
            drafts.append(
                _Draft(
                    scenario_id="SC2",
                    name=f"Reroute using {alternative_mode.transport_mode} with {alternative_mode.carrier}",
                    approach=_MODE_CHANGE_APPROACH,
                    option=self._route_option(
                        "SC2",
                        request,
                        logistics,
                        alternative_mode.carrier,
                        alternative_mode.transport_mode,
                        alternative_mode.carrier_reliability,
                    ),
                    notes=[
                        f"Changes transport mode from {incumbent_mode} to "
                        f"{alternative_mode.transport_mode}.",
                        f"Uses carrier {alternative_mode.carrier} (rank "
                        f"{alternative_mode.rank} in the logistics analysis).",
                    ],
                )
            )

        alternative_carrier = next(
            (
                option
                for option in logistics.ranked_routes
                if option.transport_mode == incumbent_mode and option.carrier != incumbent_carrier
            ),
            None,
        )
        if alternative_carrier is not None:
            drafts.append(
                _Draft(
                    scenario_id="SC3",
                    name=f"Use alternative carrier {alternative_carrier.carrier} on the same lane",
                    approach=_CARRIER_CHANGE_APPROACH,
                    option=self._route_option(
                        "SC3",
                        request,
                        logistics,
                        alternative_carrier.carrier,
                        alternative_carrier.transport_mode,
                        alternative_carrier.carrier_reliability,
                    ),
                    notes=[
                        f"Switches carrier from {incumbent_carrier} to "
                        f"{alternative_carrier.carrier} on the same lane and mode.",
                        f"Carrier reliability is {alternative_carrier.carrier_reliability}.",
                    ],
                )
            )

        return drafts

    @staticmethod
    def _route_option(
        scenario_id: str,
        request: ScenarioRequest,
        logistics: ReroutingAnalysis,
        carrier: str,
        transport_mode: str,
        carrier_reliability: float,
    ) -> RouteOption:
        """One scenario expressed in the shape the ranking engine scores."""
        return RouteOption(
            route_id=scenario_id,
            distance_km=logistics.lane_distance_km,
            transport_mode=transport_mode,
            carrier=carrier,
            cargo_value_usd=request.cargo_value_usd,
            container_count=request.container_count,
            tariff_rate_percent=request.tariff_rate_percent,
            congestion_days=request.congestion_days,
            weather_delay_days=request.weather_delay_days,
            carrier_reliability=carrier_reliability,
            risk_factors=tuple(request.risk_factors),
        )

    @staticmethod
    def _assemble(
        request: ScenarioRequest,
        drafts: Sequence["_Draft"],
        ranking: RouteRanking,
    ) -> List[ScenarioComparison]:
        """Attach the deterministic scores, tier by feasibility and rank."""
        scores = {score.route_id: score for score in ranking.ranked}

        comparisons: List[ScenarioComparison] = []
        for draft in drafts:
            score = scores[draft.scenario_id]
            feasibility = _feasibility_for(score.total_cost_usd, request.available_budget_usd)
            notes = list(draft.notes)
            if feasibility is ScenarioFeasibility.FEASIBLE_WITH_APPROVAL:
                notes.append(
                    f"Cost {score.total_cost_usd} USD exceeds the available budget of "
                    f"{request.available_budget_usd} USD, so finance approval is required."
                )
            elif feasibility is ScenarioFeasibility.UNKNOWN:
                notes.append(
                    "No available budget was supplied, so affordability could not be checked."
                )
            comparisons.append(
                ScenarioComparison(
                    scenario_id=draft.scenario_id,
                    name=draft.name,
                    approach=draft.approach,
                    carrier=draft.option.carrier,
                    transport_mode=draft.option.transport_mode,
                    distance_km=draft.option.distance_km,
                    total_cost_usd=score.total_cost_usd,
                    total_days=score.total_days,
                    risk_score=score.risk_score,
                    carrier_reliability=score.carrier_reliability,
                    weighted_score=score.weighted_score,
                    feasibility=feasibility,
                    rank=0,
                    notes=notes,
                )
            )

        comparisons.sort(
            key=lambda item: (
                _FEASIBILITY_TIER[item.feasibility],
                -item.weighted_score,
                item.total_cost_usd,
                item.scenario_id,
            )
        )
        return [
            comparison.model_copy(update={"rank": position})
            for position, comparison in enumerate(comparisons, start=1)
        ]

    # -- LLM call ---------------------------------------------------------

    def _narrate(
        self,
        request: ScenarioRequest,
        logistics: ReroutingAnalysis,
        inventory: Optional[RebalancingPlan],
        scenarios: Sequence[ScenarioComparison],
        recommended: Optional[ScenarioComparison],
    ) -> LLMScenarioNarrative:
        """Ask Gemini to explain the deterministic scenario ranking."""
        raw = self._gemini.generate_structured_json(
            prompt=build_prompt(request, logistics, inventory, scenarios, recommended),
            response_schema=LLM_SCENARIO_SCHEMA,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        try:
            return LLMScenarioNarrative.model_validate(raw)
        except ValidationError as exc:
            raise ScenarioPlanningError(
                f"Gemini returned a scenario narrative for {request.event_id} that does not "
                f"match the expected schema: {exc.error_count()} validation error(s). "
                f"First error: {exc.errors()[0]['msg']} at "
                f"{'.'.join(str(part) for part in exc.errors()[0]['loc'])}"
            ) from exc

    def _attach_assessments(
        self,
        scenarios: List[ScenarioComparison],
        narrative: LLMScenarioNarrative,
    ) -> None:
        """Fold the model's per-scenario assessments into the matching scenarios."""
        by_id = {scenario.scenario_id: scenario for scenario in scenarios}
        for assessment in narrative.scenario_assessments:
            scenario = by_id.get(assessment.scenario_id)
            if scenario is None or assessment.assessment in scenario.notes:
                continue
            scenario.notes.append(assessment.assessment)

    # -- deterministic post-processing ------------------------------------

    @staticmethod
    def _build_evidence(
        logistics: ReroutingAnalysis,
        inventory: Optional[RebalancingPlan],
        scenario_count: int,
    ) -> List[EvidenceItem]:
        """Combine the evidence from the two requested analyses."""
        evidence: List[EvidenceItem] = [
            EvidenceItem(
                source="Scenario Planning Agent",
                description=(
                    f"{scenario_count} recovery scenario(s) scored with "
                    f"app.tools.route_optimization.rank_routes; no scenario was invented."
                ),
            ),
            *logistics.evidence,
        ]
        if inventory is not None:
            evidence.extend(inventory.evidence)
        return evidence

    def _missing_information(
        self,
        logistics: ReroutingAnalysis,
        inventory: Optional[RebalancingPlan],
        scenarios: Sequence[ScenarioComparison],
        narrative: LLMScenarioNarrative,
    ) -> List[str]:
        """Combine the model's gaps, the sub-agents' gaps and the agent's own."""
        gaps: List[str] = [
            *narrative.missing_information,
            *logistics.missing_information,
        ]
        if inventory is None:
            gaps.append(
                "No inventory impact analysis was requested, so stock coverage was not "
                "considered when ranking the scenarios."
            )
        else:
            gaps.extend(inventory.missing_information)
        if len(scenarios) < 3:
            gaps.append(
                f"Only {len(scenarios)} recovery scenario(s) could be built from the available "
                f"data; the roadmap asks for at least three when sufficient data exists."
            )
        return gaps


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    request: ScenarioRequest,
    logistics: ReroutingAnalysis,
    inventory: Optional[RebalancingPlan],
    scenarios: Sequence[ScenarioComparison],
    recommended: Optional[ScenarioComparison],
) -> str:
    """Render the deterministic facts into the user-turn prompt."""
    lines = [
        "Explain the deterministic recovery scenario ranking below.",
        "",
        f"EVENT ID: {request.event_id}",
        f"DISRUPTION TYPE: {request.disruption_type}",
        f"SEVERITY: {request.severity or 'not supplied'}",
        f"AFFECTED LOCATION: {request.location or 'not supplied'}",
        f"LANE: {request.origin} -> {request.destination} "
        f"({logistics.lane_distance_km} km, "
        f"{'derived' if logistics.lane_is_estimated else 'known'} lane)",
        f"CARGO VALUE: {request.cargo_value_usd} USD in {request.container_count} container(s)",
        f"AVAILABLE BUDGET: {request.available_budget_usd} USD",
        f"DISRUPTION RISK FACTORS: {', '.join(request.risk_factors) or 'none supplied'}",
        "",
        "LOGISTICS ANALYSIS (Agent 3)",
        "----------------------------",
        logistics.explanation,
        "",
        "INVENTORY IMPACT ANALYSIS (Agent 4)",
        "-----------------------------------",
    ]
    if inventory is None:
        lines.append("Not requested.")
    else:
        lines.append(inventory.explanation)
        lines.append(
            f"Shortage before: {inventory.shortage_before} units; after recommended "
            f"transfers: {inventory.shortage_after} units."
        )

    lines.extend(
        [
            "",
            "SCENARIOS (computed deterministically; do not change these numbers)",
            "-----------------------------------------------------------------",
        ]
    )
    for scenario in scenarios:
        lines.append(
            f"{scenario.scenario_id} | rank {scenario.rank} | {scenario.name} | "
            f"carrier {scenario.carrier} | mode {scenario.transport_mode} | "
            f"cost {scenario.total_cost_usd} USD | {scenario.total_days} days | "
            f"risk score {scenario.risk_score} | reliability "
            f"{scenario.carrier_reliability} | scorecard {scenario.weighted_score} | "
            f"feasibility {scenario.feasibility.value}"
        )
    lines.extend(
        [
            "",
            f"DETERMINISTIC RECOMMENDATION: "
            f"{recommended.scenario_id if recommended else 'none'}",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Draft:
    """A scenario before the ranking engine has scored it."""

    __slots__ = ("scenario_id", "name", "approach", "option", "notes")

    def __init__(
        self,
        *,
        scenario_id: str,
        name: str,
        approach: str,
        option: RouteOption,
        notes: Sequence[str],
    ) -> None:
        self.scenario_id = scenario_id
        self.name = name
        self.approach = approach
        self.option = option
        self.notes: List[str] = list(notes)


def _feasibility_for(total_cost_usd: float, available_budget_usd: float) -> ScenarioFeasibility:
    """Affordability of a scenario against the supplied budget."""
    if available_budget_usd <= 0:
        return ScenarioFeasibility.UNKNOWN
    if total_cost_usd > available_budget_usd:
        return ScenarioFeasibility.FEASIBLE_WITH_APPROVAL
    return ScenarioFeasibility.FEASIBLE
