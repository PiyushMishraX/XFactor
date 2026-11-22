"""Pydantic request / response and agent I/O schemas.

Each agent has its own schema module, kept strictly separate from the
deterministic engines (which live in :mod:`app.tools`):

- ``disruption_schemas``  (Step 1) — ``DisruptionReport`` / ``LLMAssessment`` /
  ``DisruptionAssessment`` + disruption, severity and risk-factor enums.
- ``scenario_schemas``    (Step 3) — ``ScenarioRequest`` / ``ScenarioComparison`` /
  ``ScenarioPlan`` + ``ScenarioFeasibility``.
- ``rerouting_schemas``   (Step 3) — ``ReroutingRequest`` / ``ReroutingOption`` /
  ``ReroutingAnalysis``.
- ``rebalancing_schemas`` (Step 3) — ``RebalancingRequest`` / ``RebalancingPlan`` +
  warehouse-position, transfer and rejection models.
- ``audit_schemas``       (Step 3) — ``AuditRequest`` / ``AuditReport`` /
  ``AuditEvidence`` + ``AuditVerdict``.
- ``approval_schemas``    (Step 6) — ``ProposalSnapshot`` / ``ApprovalDecisionRecord`` /
  ``ApprovalRequestView`` + approval action, status and approver role enums.
- ``execution_schemas``   (Step 6) — ``ExecutionAction`` / ``ExecutionReport`` +
  execution action and run status enums.
"""
