"""Risk Scoring Engine — the uniform tools-layer entry point (Step 2).

The actual risk maths lives in :mod:`app.services.risk_scoring` (delivered in
Step 1): the per-factor weight table (:data:`~app.services.risk_scoring.RISK_FACTOR_WEIGHTS`),
the severity bands, the exposure bonuses and the 100-point cap all live there
and nowhere else. This module is deliberately **not** a second implementation —
it exists so that every agent and workflow can call the tools layer uniformly
(``app.tools.<engine>``) without reaching into ``app.services`` directly, while
the single source of truth stays in one file.

Assumptions
-----------
* The weight table, severity bands and the 100-point cap are owned by
  :mod:`app.services.risk_scoring` (see
  :data:`RISK_ENGINE_LOCATION`). Changing the scoring model is a change there,
  not here.
* Scoring is pure arithmetic over the observed factors plus validated
  shipment/supplier exposure — no LLM is consulted and nothing is randomised.
* ``risk_factors`` must be :class:`~app.schemas.disruption_schemas.RiskFactor`
  members (not their raw value strings): the Step 1 engine reads each factor's
  ``.value`` label when building the breakdown. Callers holding raw strings
  should coerce them first, as :mod:`app.tools.route_optimization` does.
"""

from __future__ import annotations

from typing import Iterable

from app.schemas.disruption_schemas import RiskFactor
from app.services.risk_scoring import RiskScore, compute_risk_score

#: Where the authoritative risk weights, severity bands and cap really live.
RISK_ENGINE_LOCATION = "app.services.risk_scoring"


def calculate_risk(
    *,
    risk_factors: Iterable[RiskFactor],
    shipment_count: int = 0,
    supplier_count: int = 0,
    is_supply_chain_disruption: bool = True,
) -> RiskScore:
    """Return the deterministic :class:`RiskScore` for one assessment.

    This is a thin, documented delegate to
    :func:`app.services.risk_scoring.compute_risk_score`; it adds no logic of
    its own so the two can never drift apart.

    Args:
        risk_factors: :class:`RiskFactor` members observed in the source report.
        shipment_count: Shipments confirmed to exist in PostgreSQL.
        supplier_count: Suppliers confirmed to exist in PostgreSQL.
        is_supply_chain_disruption: When False the report is irrelevant and
            scores zero regardless of any factors listed.

    Returns:
        The :class:`~app.services.risk_scoring.RiskScore` produced by the
        Step 1 engine (identical to calling it directly).
    """
    return compute_risk_score(
        risk_factors=risk_factors,
        shipment_count=shipment_count,
        supplier_count=supplier_count,
        is_supply_chain_disruption=is_supply_chain_disruption,
    )
