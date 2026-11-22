const TONE_BY_STATUS = {
  ok: 'ok',
  success: 'ok',
  degraded: 'warn',
  loading: 'warn',
  error: 'error',
}

/**
 * Small coloured status pill.
 *
 * @param {{status: string}} props
 */
export default function StatusBadge({ status }) {
  const tone = TONE_BY_STATUS[status] ?? 'warn'
  return <span className={`badge badge--${tone}`}>{status}</span>
}
