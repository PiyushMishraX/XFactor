"""Deterministic engines for the X FACTOR platform (Step 2).

This package holds the deterministic business-logic engines used by the agents
and the orchestration layer. Every engine here:

* performs plain arithmetic — **none of them ever calls an LLM**, and none makes
  a network or database call;
* validates its inputs and raises :class:`~app.tools.base.ToolInputError`
  instead of returning a meaningless number;
* returns a Pydantic result that documents the assumptions it relied on.

The Risk Scoring Engine itself lives in :mod:`app.services.risk_scoring`
(delivered in Step 1): the weight table, severity bands and the 100-point cap are
owned there. :mod:`app.tools.risk` is only the uniform tools-layer entry point
that delegates to it, so the scoring model stays in a single place.

Engine modules
--------------
* :mod:`app.tools.risk` — risk scoring entry point (delegates to ``app.services.risk_scoring``).
* :mod:`app.tools.costing` — freight cost calculation.
* :mod:`app.tools.lead_time` — lead-time estimation.
* :mod:`app.tools.route_optimization` — route comparison and ranking.
* :mod:`app.tools.inventory` — inventory position / shortage calculation.
* :mod:`app.tools.safety_stock` — safety stock and reorder point.
* :mod:`app.tools.supplier_ranking` — supplier ranking.
* :mod:`app.tools.compliance` — compliance rules.
* :mod:`app.tools.budget` — budget validation.
* :mod:`app.tools.approval` — approval management (decides, never executes).

``app.tools.base`` provides the shared helpers (:class:`~app.tools.base.EngineResult`,
:class:`~app.tools.base.ToolInputError`, the ``require_*`` guards and the scoring
utilities) that the engines build on.
"""
