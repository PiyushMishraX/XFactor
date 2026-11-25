import { useEffect, useState } from 'react'

import KpiCard from '../components/KpiCard'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { useAsyncData } from '../hooks/useAsyncData'
import { getActiveWorkflow, getDashboardOverview, startAgents } from '../services/api'
import { titleCase, when } from '../utils/format'

const PIPELINE = [
  ['Detect', 'Disruption Sensing Agent reads the event'],
  ['Reason', 'Scenario, rerouting and inventory agents analyse'],
  ['Validate', 'Compliance & Audit Agent decides deterministically'],
  ['Approve', 'An authenticated human reviews the proposal'],
  ['Execute', 'Only an approved plan is executed, idempotently'],
]

const IDLE_START = { phase: 'idle', result: null, error: '' }

function StartPanel({ active, onOpenThread, onNavigate, onFinished }) {
  const [start, setStart] = useState(IDLE_START)

  const running = start.phase === 'running' || Boolean(active?.running)
  const otherRun = active?.running && start.phase !== 'running'

  async function handleStart() {
    setStart({ phase: 'running', result: null, error: '' })
    try {
      const result = await startAgents()
      setStart({ phase: 'done', result, error: '' })
    } catch (err) {
      setStart({ phase: 'error', result: null, error: err.message })
    } finally {
      onFinished()
    }
  }

  const result = start.result

  return (
    <section className="panel panel--accent">
      <div className="panel__head">
        <div>
          <h2>Start one agent run</h2>
          <p>
            Runs the validated Red Sea scenario through all five agents exactly once. The
            backend admits one run at a time, so repeated clicks and extra tabs cannot
            overload the agents or the Gemini quota.
          </p>
        </div>
        <button
          type="button"
          className="button button--ok"
          onClick={handleStart}
          disabled={running}
        >
          {start.phase === 'running'
            ? 'Agents running…'
            : otherRun
              ? 'Another run is in flight'
              : 'Start agents'}
        </button>
      </div>

      {start.phase === 'running' && (
        <p className="muted" role="status">
          The supervisor is delegating to the five agents. This can take up to a minute; the
          result will appear here and in Agent Activity.
        </p>
      )}

      {otherRun && (
        <p className="muted" role="status">
          Thread <span className="mono">{active.thread_id}</span> is already running. Wait for it
          to finish before starting another run.
        </p>
      )}

      {start.phase === 'error' && <p className="error">{start.error}</p>}

      {result && (
        <div className="outcome" role="status">
          <div className="detail__head">
            <div>
              <h3 className="subtitle">Run output</h3>
              <strong className="mono">{result.thread_id}</strong>
            </div>
            <StatusBadge status={result.status ?? 'completed'} />
          </div>
          <div className="row">
            <span className="row__label">Awaiting approval</span>
            <span className="row__value">{result.awaiting_approval ? 'yes' : 'no'}</span>
          </div>
          <div className="row">
            <span className="row__label">Agents executed</span>
            <span className="row__value">{result.agent_executions?.length ?? 0}</span>
          </div>
          {result.proposal_version && (
            <div className="row">
              <span className="row__label">Proposal version</span>
              <span className="row__value">{result.proposal_version}</span>
            </div>
          )}
          {result.recommendation?.headline && (
            <div className="row">
              <span className="row__label">Recommendation</span>
              <span className="row__value">{result.recommendation.headline}</span>
            </div>
          )}
          {result.errors?.length > 0 && (
            <ul className="bullets bullets--error">
              {result.errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
          <div className="actions">
            <button
              type="button"
              className="button"
              onClick={() => onOpenThread(result.thread_id, 'agents')}
            >
              Open agent activity
            </button>
            {result.awaiting_approval && (
              <button
                type="button"
                className="button button--warn"
                onClick={() => onNavigate('approvals')}
              >
                Open Approval Center
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

export default function Overview({ onOpenThread, onNavigate }) {
  const { status, data, error, refresh } = useAsyncData(getDashboardOverview)
  const [active, setActive] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function pollActive() {
      try {
        const body = await getActiveWorkflow()
        if (!cancelled) setActive(body)
      } catch {
        // The slot status is advisory; a failed poll must not block the dashboard.
      }
    }

    pollActive()
    const timer = setInterval(pollActive, 4000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

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

      <StartPanel
        active={active}
        onOpenThread={onOpenThread}
        onNavigate={onNavigate}
        onFinished={() => {
          refresh()
          getActiveWorkflow()
            .then(setActive)
            .catch(() => {})
        }}
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
