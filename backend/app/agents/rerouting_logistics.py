"""Rerouting & Logistics Agent — AGENT 3 (Step 3).

Design rule enforced here, identical to Step 1: **the LLM explains, deterministic
code decides.**

* the :mod:`app.integrations.mapping` connector supplies the lane distance;
* the :mod:`app.integrations.carriers` connector supplies the bookable services;
* :mod:`app.tools.route_optimization` scores and ranks those services using
  :mod:`app.tools.costing`, :mod:`app.tools.lead_time` and
  :mod:`app.services.risk_scoring`. It never invents a route the caller did not
  supply, so this agent cannot invent one either;
* Gemini writes the explanation, the qualitative route risks and the confidence —
  and may not alter a single number.

The agent performs analysis only. It never books, books-out or executes anything.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.carriers import CarrierConnector, CarrierService
from app.integrations.mapping import MappingConnector, RouteDistance
from app.schemas.disruption_schemas import EvidenceItem
from app.schemas.rerouting_schemas import (
    ReroutingAnalysis,
    ReroutingOption,
    ReroutingRequest,
)
from app.services.gemini_service import GeminiService
from app.tools.route_optimization import RouteOption, RouteRanking, rank_routes

logger = logging.getLogger(__name__)


class ReroutingLogisticsError(RuntimeError):
    """Raised when the agent cannot produce a usable rerouting analysis."""


SYSTEM_INSTRUCTION = """You are the Rerouting & Logistics Agent inside X FACTOR, an
enterprise supply-chain resilience platform used by a logistics control tower.

You are given ONE disrupted lane plus a set of logistics alternatives that have
already been costed, timed, risk-scored and ranked by deterministic engines.

RULES
1. Explain the ranking you are given. Do not re-rank, re-price or re-time anything.
2. Quote the supplied numbers exactly. Never invent a carrier, a route, a cost, a
   transit time or a risk score.
3. route_risks must be grounded in the supplied option data or the supplied
   disruption risk factors. Describe the risk of the options that were actually
   scored; state none when the data does not support a risk.
4. List everything you could not establish in missing_information. Use an empty
   list when nothing is missing.
5. recommended_route_id is decided by the ranking engine, not by you. Never claim a
   different option is the recommendation.
6. confidence is your own certainty in this explanation, between 0 and 1.
7. You analyse only. Never state or imply that a booking, a diversion or any other
   operational action has been taken.
"""


#: OpenAPI-subset schema handed to Gemini so the narrative is valid JSON.
LLM_REROUTING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "Why the deterministic ranking produced this order, citing the numbers.",
        },
        "route_risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Route-related risks evidenced by the supplied option data.",
        },
        "confidence": {"type": "number", "description": "Certainty between 0 and 1."},
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Facts required for a firmer recommendation that were not supplied.",
        },
    },
    "required": ["explanation", "route_risks", "confidence", "missing_information"],
}


class LLMReroutingNarrative(BaseModel):
    """The only fields the model decides for Agent 3."""

    model_config = ConfigDict(str_strip_whitespace=True)

    explanation: str = Field(min_length=1)
    route_risks: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_information: List[str] = Field(default_factory=list)


class ReroutingLogisticsAgent:
    """Finds, scores and ranks logistics alternatives for one disrupted lane."""

    def __init__(
        self,
        *,
        gemini: Optional[GeminiService] = None,
        mapping: MappingConnector,
        carriers: CarrierConnector,
    ) -> None:
        self._gemini = gemini or GeminiService()
        self._mapping = mapping
        self._carriers = carriers

    def analyse(self, request: ReroutingRequest) -> ReroutingAnalysis:
        """Score every available carrier service for ``request`` and rank them.

        Raises:
            GeminiNotConfiguredError: No Gemini API key is configured.
            GeminiRequestError: Gemini was unreachable or returned unusable output.
            ReroutingLogisticsError: Gemini's output did not satisfy the schema.
        """
        logger.info(
            "Rerouting analysis for %s: %s -> %s",
            request.disruption_id,
            request.origin,
            request.destination,
        )

        lane = self._mapping.get_route(origin=request.origin, destination=request.destination)
        services = self._candidate_services(request)
        options = [self._build_option(request, lane, service) for service in services]
        ranking = rank_routes(options=options)

        ranked_routes = self._to_analysis_options(options, ranking, request)
        recommended = ranking.recommended_route_id
        current_rank = self._current_route_rank(ranked_routes)

        narrative = self._narrate(request, lane, ranked_routes, recommended)

        analysis = ReroutingAnalysis(
            disruption_id=request.disruption_id,
            origin=request.origin,
            destination=request.destination,
            lane_distance_km=lane.distance_km,
            lane_is_estimated=lane.is_estimated,
            ranked_routes=ranked_routes,
            recommended_route_id=recommended,
            current_route_rank=current_rank,
            explanation=narrative.explanation,
            route_risks=narrative.route_risks,
            confidence=round(narrative.confidence, 3),
            evidence=self._build_evidence(lane, services),
            missing_information=_deduplicate(
                [
                    *narrative.missing_information,
                    *self._detected_gaps(request, lane, services, current_rank),
                ]
            ),
        )

        logger.info(
            "Rerouting analysis %s: %s option(s) scored, recommended=%s",
            request.disruption_id,
            len(analysis.ranked_routes),
            analysis.recommended_route_id,
        )
        return analysis

    # -- deterministic inputs ---------------------------------------------

    def _candidate_services(self, request: ReroutingRequest) -> List[CarrierService]:
        """Return the carrier services eligible for this lane, in a stable order."""
        allowed = {mode.strip().lower() for mode in request.candidate_modes if mode.strip()}
        services = [
            service
            for service in self._carriers.list_services()
            if not allowed or service.transport_mode.strip().lower() in allowed
        ]
        # Deterministic order so the same request always produces the same options.
        return sorted(services, key=lambda service: (service.transport_mode, service.carrier))

    @staticmethod
    def _build_option(
        request: ReroutingRequest, lane: RouteDistance, service: CarrierService
    ) -> RouteOption:
        """Turn one carrier service into a scored-candidate route option."""
        return RouteOption(
            route_id=_route_id(service),
            distance_km=lane.distance_km,
            transport_mode=service.transport_mode,
            carrier=service.carrier,
            cargo_value_usd=request.cargo_value_usd,
            container_count=request.container_count,
            tariff_rate_percent=request.tariff_rate_percent,
            congestion_days=request.congestion_days,
            weather_delay_days=request.weather_delay_days,
            carrier_reliability=service.reliability,
            risk_factors=tuple(request.risk_factors),
        )

    @staticmethod
    def _to_analysis_options(
        options: Sequence[RouteOption],
        ranking: RouteRanking,
        request: ReroutingRequest,
    ) -> List[ReroutingOption]:
        """Join the ranking back onto the carrier services it scored."""
        by_id = {option.route_id: option for option in options}
        carrier = request.current_carrier.strip().lower()
        mode = request.current_mode.strip().lower()
        results: List[ReroutingOption] = []
        for score in ranking.ranked:
            option = by_id[score.route_id]
            is_current = bool(carrier) and (
                option.carrier.strip().lower() == carrier
                and option.transport_mode.strip().lower() == mode
            )
            results.append(
                ReroutingOption(
                    route_id=score.route_id,
                    carrier=option.carrier,
                    transport_mode=option.transport_mode,
                    distance_km=option.distance_km,
                    total_cost_usd=score.total_cost_usd,
                    total_days=score.total_days,
                    risk_score=score.risk_score,
                    carrier_reliability=score.carrier_reliability,
                    weighted_score=score.weighted_score,
                    rank=score.rank,
                    is_current_route=is_current,
                    congestion_days=option.congestion_days,
                    weather_delay_days=option.weather_delay_days,
                )
            )
        return results

    @staticmethod
    def _current_route_rank(options: Sequence[ReroutingOption]) -> Optional[int]:
        """Rank of the incumbent option, or ``None`` when no option matches it."""
        ranks = [option.rank for option in options if option.is_current_route]
        return min(ranks) if ranks else None

    # -- LLM call ---------------------------------------------------------

    def _narrate(
        self,
        request: ReroutingRequest,
        lane: RouteDistance,
        options: Sequence[ReroutingOption],
        recommended: Optional[str],
    ) -> LLMReroutingNarrative:
        """Ask Gemini to explain the deterministic ranking."""
        raw = self._gemini.generate_structured_json(
            prompt=build_prompt(request, lane, options, recommended),
            response_schema=LLM_REROUTING_SCHEMA,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        try:
            return LLMReroutingNarrative.model_validate(raw)
        except ValidationError as exc:
            raise ReroutingLogisticsError(
                f"Gemini returned a rerouting narrative for {request.disruption_id} that "
                f"does not match the expected schema: {exc.error_count()} validation "
                f"error(s). First error: {exc.errors()[0]['msg']} at "
                f"{'.'.join(str(part) for part in exc.errors()[0]['loc'])}"
            ) from exc

    # -- deterministic post-processing ------------------------------------

    @staticmethod
    def _build_evidence(
        lane: RouteDistance, services: Sequence[CarrierService]
    ) -> List[EvidenceItem]:
        """Record the lane and the carrier source behind the ranking."""
        evidence = [
            EvidenceItem(
                source=lane.provenance.label,
                description=(
                    f"Lane distance {lane.distance_km} km for {lane.origin} -> "
                    f"{lane.destination}"
                    + (" (derived, not measured)" if lane.is_estimated else "")
                ),
                timestamp=lane.provenance.retrieved_at,
            )
        ]
        if services:
            evidence.append(
                EvidenceItem(
                    source=services[0].provenance.label,
                    description=(
                        f"{len(services)} carrier service(s) evaluated: "
                        + ", ".join(sorted({service.carrier for service in services}))
                    ),
                    timestamp=services[0].provenance.retrieved_at,
                )
            )
        return evidence

    @staticmethod
    def _detected_gaps(
        request: ReroutingRequest,
        lane: RouteDistance,
        services: Sequence[CarrierService],
        current_rank: Optional[int],
    ) -> List[str]:
        """Gaps the deterministic layer can see, independent of the model."""
        gaps: List[str] = []
        if lane.is_estimated:
            gaps.append(
                "The lane distance was derived rather than measured, so the cost and "
                "transit estimates are indicative."
            )
        if not services:
            gaps.append(
                "No carrier service matched the requested transport mode(s), so no "
                "logistics alternative could be scored."
            )
        if request.current_carrier and current_rank is None:
            gaps.append(
                f"The incumbent carrier '{request.current_carrier}' is not among the "
                f"configured carrier services, so it could not be compared directly."
            )
        if not request.risk_factors:
            gaps.append(
                "No disruption risk factors were supplied, so route risk was scored from "
                "the carrier profile alone."
            )
        return gaps


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    request: ReroutingRequest,
    lane: RouteDistance,
    options: Sequence[ReroutingOption],
    recommended: Optional[str],
) -> str:
    """Render the deterministic facts into the user-turn prompt."""
    lines = [
        "Explain the deterministic logistics ranking below and describe its route risks.",
        "",
        f"DISRUPTION ID: {request.disruption_id}",
        f"LANE: {request.origin} -> {request.destination}",
        f"LANE DISTANCE: {lane.distance_km} km"
        f"{' (derived, not measured)' if lane.is_estimated else ' (known lane)'}",
        f"CARGO VALUE: {request.cargo_value_usd} USD in {request.container_count} container(s)",
        f"INCUMBENT: carrier '{request.current_carrier or 'not supplied'}' on "
        f"{request.current_mode}",
        f"CONGESTION DELAY: {request.congestion_days} day(s)",
        f"WEATHER DELAY: {request.weather_delay_days} day(s)",
        f"TARIFF RATE: {request.tariff_rate_percent}%",
        f"DISRUPTION RISK FACTORS: {', '.join(request.risk_factors) or 'none supplied'}",
        "",
        "RANKED OPTIONS (computed deterministically; do not change these numbers)",
        "---------------------------------------------------------------",
    ]
    if not options:
        lines.append("No option could be scored.")
    for option in options:
        lines.append(
            f"rank {option.rank} | id {option.route_id} | carrier {option.carrier} | "
            f"mode {option.transport_mode} | cost {option.total_cost_usd} USD | "
            f"{option.total_days} days | risk score {option.risk_score} | "
            f"carrier reliability {option.carrier_reliability} | "
            f"scorecard {option.weighted_score}"
        )
    lines.extend(
        [
            "",
            f"DETERMINISTIC RECOMMENDATION: {recommended or 'none'}",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_id(service: CarrierService) -> str:
    """Stable, unique identifier for one carrier service."""
    return f"{_slug(service.transport_mode)}-{_slug(service.carrier)}-{_slug(service.service_name)}"


def _slug(value: str) -> str:
    """Lower-case hyphenated form of ``value``, safe to use in an identifier."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-") or "unknown"


def _deduplicate(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
