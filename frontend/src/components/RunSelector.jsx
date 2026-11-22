import { titleCase } from '../utils/format'

export default function RunSelector({
  runs,
  value,
  onChange,
  onRefresh,
  busy = false,
  label = 'Workflow run',
}) {
  return (
    <div className="run-selector">
      <label className="field">
        <span className="field__label">{label}</span>
        <select
          className="input"
          value={value ?? ''}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Select a recorded run…</option>
          {runs.map((run) => (
            <option key={run.thread_id} value={run.thread_id}>
              {run.thread_id} · {titleCase(run.status)} · {run.disruption_type || 'disruption'}
            </option>
          ))}
        </select>
      </label>
      {onRefresh && (
        <button type="button" className="button" onClick={onRefresh} disabled={busy}>
          {busy ? 'Refreshing…' : 'Refresh runs'}
        </button>
      )}
    </div>
  )
}
