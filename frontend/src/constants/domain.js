export const AGENTS = [
  {
    id: 'disruption_sensing',
    label: 'Disruption Sensing',
    focus: 'Reads the event and scores risk deterministically.',
  },
  {
    id: 'scenario_planning',
    label: 'Scenario Planning',
    focus: 'Builds and ranks recovery alternatives.',
  },
  {
    id: 'rerouting_logistics',
    label: 'Rerouting & Logistics',
    focus: 'Scores routes, carriers and transit time.',
  },
  {
    id: 'inventory_rebalancing',
    label: 'Inventory Rebalancing',
    focus: 'Moves stock without breaching safety stock.',
  },
  {
    id: 'compliance_audit',
    label: 'Compliance & Audit',
    focus: 'Validates policy, budget and approval level.',
  },
]

export const AGENT_LABELS = Object.fromEntries(
  AGENTS.map((agent) => [agent.id, agent.label]),
)

export const DISRUPTION_TYPES = [
  'Maritime Security Threat',
  'Severe Weather',
  'Geopolitical Development',
  'Tariff Change',
  'Port Congestion',
  'Supplier Failure',
  'Transportation Delay',
  'Infrastructure Disruption',
]

export const SEVERITIES = ['Negligible', 'Low', 'Moderate', 'High', 'Critical']

export const FAILED_STATUSES = new Set([
  'failed',
  'iteration_limit_reached',
  'no_feasible_recovery',
  'no_compliant_recovery',
])
