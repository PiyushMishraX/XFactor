import KpiCard from '../components/KpiCard'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { useAsyncData } from '../hooks/useAsyncData'
import { getDashboardOverview } from '../services/api'
import { titleCase, when } from '../utils/format'

const PIPELINE = [
  ['Detect', 'Disruption Sensing Agent reads the event'],
  ['Reason', 'Scenario, rerouting and inventory agents analyse'],
  ['Validate', 'Compliance & Audit Agent decides deterministically'],
  ['Approve', 'An authenticated human reviews the proposal'],
  ['Execute', 'Only an approved plan is executed, idempotently'],
]

export default function Overview({ onOpenThread, onNavigate }) {
  const { status, data, error, refresh } = useAsyncData(getDashboardOverview)

  if (status === 'loading' && !data) return <LoadingState />
  if (status === 'error') return <ErrorState message={error} onRetry={refresh} />

  const counts = data?.counts ?? {}
  const runs = data?.latest_runs ?? []
  const sources = data?.data_sources ?? {}

  return (
    <div className="page">
      <PageHeader
        eyebrow="Overview"
        title="Supply chain control tower"
        description="The posture of the agentic system, read from recorded workflow state — never from placeholder activity."
        actions={
          <button type="button" className="button" onClick={refresh}>
            Refresh
          </button>
        }
      />

      <section className="kpi-grid" aria-label="Platform indicators">
        <KpiCard
          label="Tracked shipments"
          value={counts.shipments ?? '—'}
          hint={`${counts.suppliers ?? 0} suppliers in master data`}
        />
        <KpiCard
          label="Workflow runs"
          value={counts.runs ?? 0}
          hint={`${counts.agent_executions ?? 0} agent executions recorded`}
          tone="accent"
        />
        <KpiCard
          label="Awaiting approval"
          value={counts.awaiting_approval ?? 0}
          hint="authenticated decision required"
          tone={counts.awaiting_approval ? 'warn' : ''}
        />
        <KpiCard
          label="Failed runs"
          value={counts.failed ?? 0}
          hint={`${counts.errors ?? 0} recorded error(s)`}
          tone={counts.failed ? 'error' : ''}
        />
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2>Decision pipeline</h2>
            <p>Every stage is backed by a deterministic engine or a recorded human decision.</p>
          </div>
        </div>
        <ol className="pipeline">
          {PIPELINE.map(([step, detail], index) => (
            <li key={step} className="pipeline__step">
              <span className="pipeline__index">{String(index + 1).padStart(2, '0')}</span>
              <strong>{step}</strong>
              <span>{detail}</span>
            </li>
          ))}
        </ol>
      </section>

      <div className="split">
        <section className="panel">
          <div className="panel__head">
            <div>
              <h2>Latest workflow runs</h2>
              <p>Recorded by the orchestration API after a real graph invocation.</p>
            </div>
          </div>

          {runs.length === 0 ? (
            <EmptyState
              title="No workflow runs recorded yet"
              action={
                <button
                  type="button"
                  className="button button--ok"
                  onClick={() => onNavigate('shipments')}
                >
                  Start from a shipment
                </button>
              }
            >
              Open Shipment Management to submit a disruption to the supervisor. Results will
              appear here and in Agent Activity.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Thread</th>
                    <th>Disruption</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.thread_id}
                      className="table__row--clickable"
                      onClick={() => onOpenThread(run.thread_id, 'agents')}
                    >
                      <td className="mono">{run.thread_id}</td>
                      <td>
                        <strong>{run.headline || run.disruption_type || '—'}</strong>
                        <span className="muted block">{run.event_id}</span>
                      </td>
                      <td>{run.severity || '—'}</td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                      <td>{when(run.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <div>
              <h2>Data sources</h2>
              <p>Provenance travels with every record.</p>
            </div>
          </div>
          <dl className="facts">
            <div>
              <dt>Shipments</dt>
              <dd>{sources.shipments ?? '—'}</dd>
            </div>
            <div>
              <dt>Workflow history</dt>
              <dd>{sources.workflow_history ?? '—'}</dd>
            </div>
            <div>
              <dt>Inventory</dt>
              <dd>{sources.inventory ?? '—'}</dd>
            </div>
            <div>
              <dt>Run status mix</dt>
              <dd>
                {Object.entries(counts.by_status ?? {}).length === 0
                  ? 'No runs yet'
                  : Object.entries(counts.by_status).map(([key, value]) => (
                      <span key={key} className="chip">
                        {titleCase(key)} {value}
                      </span>
                    ))}
              </dd>
            </div>
          </dl>
          <div className="quick-links">
            <button type="button" className="button" onClick={() => onNavigate('disruptions')}>
              Monitor disruptions
            </button>
            <button type="button" className="button" onClick={() => onNavigate('audit')}>
              Audit history
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
