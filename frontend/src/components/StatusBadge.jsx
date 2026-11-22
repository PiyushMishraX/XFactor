import { titleCase } from '../utils/format'

const TONE_BY_STATUS = {
  ok: 'ok',
  success: 'ok',
  healthy: 'ok',
  completed: 'ok',
  approved: 'ok',
  live: 'ok',
  degraded: 'warn',
  loading: 'warn',
  running: 'warn',
  awaiting_approval: 'warn',
  pending: 'warn',
  modifications_requested: 'warn',
  simulated: 'warn',
  error: 'error',
  failed: 'error',
  rejected: 'error',
  approval_rejected: 'error',
  no_feasible_recovery: 'error',
  no_compliant_recovery: 'error',
  iteration_limit_reached: 'error',
  skipped: 'muted',
  idle: 'muted',
  not_delegated: 'muted',
  queued: 'muted',
}

const LABELS = {
  awaiting_approval: 'Awaiting approval',
  modifications_requested: 'Modifications requested',
  approval_rejected: 'Approval rejected',
  no_feasible_recovery: 'No feasible recovery',
  no_compliant_recovery: 'No compliant recovery',
  iteration_limit_reached: 'Iteration limit',
  not_delegated: 'Not delegated',
  not_started: 'Not started',
  mock: 'Simulated',
}

/**
 * Small coloured status pill.
 *
 * @param {{status: string}} props
 */
export default function StatusBadge({ status }) {
  const key = String(status || 'unknown')
  const tone = TONE_BY_STATUS[key] ?? 'warn'
  return <span className={`badge badge--${tone}`}>{LABELS[key] ?? titleCase(key)}</span>
}
