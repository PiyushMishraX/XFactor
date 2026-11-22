"""Disruption Sensing Agent — the first functional agent in X FACTOR (Step 1).

Design rule enforced here: **the LLM interprets, deterministic code decides.**

* Gemini reads the unstructured report and reports observable facts — category,
  geography, risk signals, evidence, unknowns.
* :mod:`app.services.risk_scoring` turns those signals into a risk score and
  severity using a fixed weight table.
* :mod:`app.services.supply_chain_repository` decides which shipment and supplier
  identifiers are real by looking them up in PostgreSQL.

The agent performs analysis only. It never executes an operational action.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from pydantic import ValidationError

from app.schemas.disruption_schemas import (
    DisruptionAssessment,
    DisruptionCategory,
    DisruptionReport,
    EvidenceItem,
    LLMAssessment,
    RiskFactor,
)
from app.services.gemini_service import GeminiService
from app.services.risk_scoring import compute_risk_score
from app.services.supply_chain_repository import (
    ShipmentRef,
    SupplierRef,
    SupplyChainRepository,
    SupplyChainSnapshot,
)

logger = logging.getLogger(__name__)


class DisruptionSensingError(RuntimeError):
    """Raised when the agent cannot produce a usable assessment."""


SYSTEM_INSTRUCTION = """You are the Disruption Sensing Agent inside X FACTOR, an enterprise
supply-chain resilience platform used by a logistics control tower.

Read ONE disruption report and return a structured assessment of it.

RULES
1. Report only what the text supports. If the report does not say it, do not claim it.
2. Never invent identifiers. List a shipment or supplier id only when it appears verbatim
   in the report text. An empty list is a correct answer.
3. If the report is not about a supply-chain disruption, set
   is_supply_chain_disruption to false and disruption_type to "Unrelated".
4. disruption_type and risk_factors must be chosen from the allowed values only.
5. Select a risk_factor only when the report provides evidence for that specific signal.
   Do not estimate probabilities.
6. affected_locations must be real geography - region, country, port, canal, strait or city -
   that the report names or unambiguously implies.
7. List everything you could not determine in missing_information. List mutually
   inconsistent statements in contradictions. Use empty lists when there are none.
8. Every evidence entry must point back to the report. Use the report's source name and
   quote or closely paraphrase the supporting sentence.
9. recommended_next_action is an investigation or planning step for a human analyst.
   Never execute, schedule or claim to execute an operational action.
10. Do not output a risk score or severity. A deterministic engine computes both.
11. confidence is your own certainty in this assessment, between 0 and 1.
"""


#: OpenAPI-subset schema handed to Gemini so the reply is valid JSON.
LLM_ASSESSMENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_supply_chain_disruption": {
            "type": "boolean",
            "description": "False when the report is unrelated news.",
        },
        "disruption_type": {
            "type": "string",
            "enum": [category.value for category in DisruptionCategory],
        },
        "description": {
            "type": "string",
            "description": "Neutral one-sentence summary of the disruption.",
        },
        "affected_locations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Regions, countries, ports, canals or straits affected.",
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "string", "enum": [factor.value for factor in RiskFactor]},
            "description": "Observable risk signals evidenced by the report.",
        },
        "potential_impact": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Consequences the report supports, without inventing figures.",
        },
        "mentioned_shipment_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Shipment ids appearing verbatim in the report. Usually empty.",
        },
        "mentioned_supplier_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Supplier ids appearing verbatim in the report. Usually empty.",
        },
        "recommended_next_action": {
            "type": "string",
            "description": "Investigation or planning step for a human analyst.",
        },
        "confidence": {"type": "number", "description": "Certainty between 0 and 1."},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                    "timestamp": {
                        "type": "string",
                        "description": "ISO-8601 timestamp when the source states one.",
                    },
                },
                "required": ["source", "description"],
            },
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Facts required for a fuller assessment that the report omits.",
        },
        "contradictions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Mutually inconsistent statements found in the report.",
        },
    },
    "required": [
        "is_supply_chain_disruption",
        "disruption_type",
        "description",
        "affected_locations",
        "risk_factors",
        "potential_impact",
        "mentioned_shipment_ids",
        "mentioned_supplier_ids",
        "recommended_next_action",
        "confidence",
        "evidence",
        "missing_information",
        "contradictions",
    ],
}

UNKNOWN_LOCATION = "Unknown"
NO_DISRUPTION_ACTION = "No supply-chain action required; continue routine monitoring."


class DisruptionSensingAgent:
    """Turns one unstructured disruption report into a validated assessment."""

    def __init__(
        self,
        *,
        gemini: Optional[GeminiService] = None,
        repository: SupplyChainRepository,
    ) -> None:
        self._gemini = gemini or GeminiService()
        self._repository = repository

    def assess(self, report: DisruptionReport) -> DisruptionAssessment:
        """Analyse ``report`` and return a validated :class:`DisruptionAssessment`.

        Raises:
            GeminiNotConfiguredError: No Gemini API key is configured.
            GeminiRequestError: Gemini was unreachable or returned unusable output.
            DisruptionSensingError: Gemini's output did not satisfy the schema.
        """
        event_id = report.derive_event_id()
        logger.info("Assessing disruption report %s from %s", event_id, report.source)

        analysis = self._analyse(report, event_id)
        snapshot = self._repository.snapshot(
            shipment_ids=analysis.mentioned_shipment_ids,
            supplier_ids=analysis.mentioned_supplier_ids,
            locations=analysis.affected_locations,
        )

        shipments: Sequence[ShipmentRef] = snapshot.shipments if analysis.is_supply_chain_disruption else ()
        suppliers: Sequence[SupplierRef] = snapshot.suppliers if analysis.is_supply_chain_disruption else ()

        risk = compute_risk_score(
            risk_factors=analysis.risk_factors,
            shipment_count=len(shipments),
            supplier_count=len(suppliers),
            is_supply_chain_disruption=analysis.is_supply_chain_disruption,
        )

        assessment = DisruptionAssessment(
            event_id=event_id,
            disruption_type=analysis.disruption_type,
            description=analysis.description,
            location=self._primary_location(analysis, report),
            severity=risk.severity,
            risk_score=risk.score,
            affected_shipments=[shipment.id for shipment in shipments],
            affected_suppliers=[supplier.id for supplier in suppliers],
            potential_impact=analysis.potential_impact,
            recommended_next_action=(
                analysis.recommended_next_action
                if analysis.is_supply_chain_disruption
                else NO_DISRUPTION_ACTION
            ),
            confidence=round(analysis.confidence, 3),
            evidence=self._build_evidence(analysis, report),
            is_supply_chain_disruption=analysis.is_supply_chain_disruption,
            source=report.source,
            source_url=report.source_url,
            reported_at=report.reported_at,
            risk_breakdown=risk.breakdown,
            reference_contributions=risk.reference_contributions,
            affected_locations=analysis.affected_locations,
            unvalidated_shipment_references=list(snapshot.unknown_shipment_ids),
            unvalidated_supplier_references=list(snapshot.unknown_supplier_ids),
            missing_information=self._missing_information(analysis, report, snapshot),
            contradictions=self._contradictions(analysis, snapshot),
        )

        logger.info(
            "Assessed %s: type=%s severity=%s risk=%s shipments=%s",
            event_id,
            assessment.disruption_type.value,
            assessment.severity.value,
            assessment.risk_score,
            assessment.affected_shipments,
        )
        return assessment

    # -- LLM call --------------------------------------------------------

    def _analyse(self, report: DisruptionReport, event_id: str) -> LLMAssessment:
        """Ask Gemini for the structured analysis and validate it."""
        raw = self._gemini.generate_structured_json(
            prompt=build_prompt(report),
            response_schema=LLM_ASSESSMENT_SCHEMA,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        try:
            return LLMAssessment.model_validate(raw)
        except ValidationError as exc:
            raise DisruptionSensingError(
                f"Gemini returned an assessment for {event_id} that does not match the "
                f"expected schema: {exc.error_count()} validation error(s). "
                f"First error: {exc.errors()[0]['msg']} at "
                f"{'.'.join(str(part) for part in exc.errors()[0]['loc'])}"
            ) from exc

    # -- deterministic post-processing ------------------------------------

    @staticmethod
    def _primary_location(analysis: LLMAssessment, report: DisruptionReport) -> str:
        """Pick the headline location, preferring the model's own geography list."""
        if analysis.affected_locations:
            return analysis.affected_locations[0]
        if report.location_hint:
            return report.location_hint
        return UNKNOWN_LOCATION

    @staticmethod
    def _build_evidence(analysis: LLMAssessment, report: DisruptionReport) -> List[EvidenceItem]:
        """LLM evidence plus an always-present pointer to the input report.

        The report itself is added deterministically so every assessment carries
        provenance even when the model omits citations.
        """
        entries: List[EvidenceItem] = [
            EvidenceItem(
                source=report.source,
                description=report.headline,
                url=report.source_url,
                timestamp=report.reported_at,
            )
        ]
        for item in analysis.evidence:
            duplicate = any(
                existing.source == item.source and existing.description == item.description
                for existing in entries
            )
            if not duplicate:
                entries.append(item)
        return entries

    @staticmethod
    def _missing_information(
        analysis: LLMAssessment,
        report: DisruptionReport,
        snapshot: SupplyChainSnapshot,
    ) -> List[str]:
        """Combine the model's gaps with gaps the deterministic layer detected."""
        gaps = list(analysis.missing_information)
        if report.reported_at is None:
            gaps.append("The report carries no timestamp, so the event cannot be dated.")
        if analysis.is_supply_chain_disruption and not analysis.affected_locations:
            gaps.append("No affected location could be established.")
        if analysis.is_supply_chain_disruption and not snapshot.shipments and not snapshot.suppliers:
            gaps.append(
                "No shipment or supplier in the master data could be linked to this disruption."
            )
        return _deduplicate(gaps)

    @staticmethod
    def _contradictions(analysis: LLMAssessment, snapshot: SupplyChainSnapshot) -> List[str]:
        """Combine the model's contradictions with deterministically detected ones."""
        conflicts = list(analysis.contradictions)
        if (
            not analysis.is_supply_chain_disruption
            and analysis.disruption_type is not DisruptionCategory.UNRELATED
        ):
            conflicts.append(
                "The report was marked as unrelated but a supply-chain disruption type was supplied."
            )
        if snapshot.unknown_shipment_ids and not snapshot.shipments_by_reference:
            conflicts.append(
                "Every shipment id named in the report is absent from the shipment master data."
            )
        if snapshot.unknown_supplier_ids and not snapshot.suppliers_by_reference:
            conflicts.append(
                "Every supplier id named in the report is absent from the supplier master data."
            )
        return _deduplicate(conflicts)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(report: DisruptionReport) -> str:
    """Render the report into the user-turn prompt."""
    lines = [
        "Assess the disruption report below and return the structured assessment.",
        "",
        f"SOURCE: {report.source}",
        f"REPORTED AT: {report.reported_at.isoformat() if report.reported_at else 'not supplied'}",
        f"LOCATION HINT: {report.location_hint or 'not supplied'}",
        f"SOURCE URL: {report.source_url or 'not supplied'}",
        "",
        "REPORT TEXT",
        "-----------",
        report.full_text,
    ]
    return "\n".join(lines)


def _deduplicate(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
