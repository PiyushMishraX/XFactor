import { useState } from 'react'

import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { AGENT_LABELS } from '../constants/domain'
import { useAsyncData } from '../hooks/useAsyncData'
import { getWorkflowRun, getWorkflowRuns } from '../services/api'
import { money, percent, titleCase, when } from '../utils/format'

function FindingList({ items, tone }) {
  if (!items?.length) return <p className="muted">None recorded.</p>
  return (
    <ul className={`bullets ${tone === 'error' ? 'bullets--error' : ''}`}>
      {items.map((item, index) => (
        <li key={`${item.rule_id ?? 'finding'}-${index}`}>
          <strong>{item.rule_id ?? 'Finding'}</strong>
          {item.detail ? `: ${item.detail}` : ''}
          {item.mandatory === false ? ' (non-mandatory)' : ''}
        </li>
      ))}
    </ul>
  )
}

export default function AuditHistory({ activeThread, onSelectThread, onOpenThread }) {
  const runsState = useAsyncData(getWorkflowRuns, [])
  const runs = runsState.data?.runs ?? []
  const [selectedId, setSelectedId] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const thread = selectedId || activeThread || runs[0]?.thread_id || ''
  const detailState = useAsyncData(
    () => (thread ? getWorkflowRun(thread) : Promise.resolve(null)),
    [thread],
    { enabled: Boolean(thread) },
  )

  if (runsState.status === 'loading' && !runsState.data) return <LoadingState />
  if (runsState.status === 'error') {
    return <ErrorState message={runsState.error} onRetry={runsState.refresh} />
  }

  const statuses = [...new Set(runs.map((run) => run.status).filter(Boolean))]
  const filteredRuns = statusFilter ? runs.filter((run) => run.status === statusFilter) : runs
  const detail = detailState.data
  const state = detail?.state ?? {}
  const audit = state.audit_report ?? {}
  const decisions = state.decisions ?? []
  const executions = state.agent_executions ?? []
  const approvals = state.approval_history ?? []
  const replanning = state.replanning ?? []
  const errors = state.errors ?? []
  const budget = audit.budget ?? {}
  const approvalPolicy = audit.approval ?? {}

  return (
    <div className="page">
      <PageHeader
        eyebrow="Audit history"
        title="Recorded decisions and validations"
        description="The audit trail is the executed call graph plus the deterministic verdicts. Nothing here is reconstructed from a conversation."
        actions={
          <div className="actions actions--flush">
            <select
              className="input input--compact"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              aria-label="Filter runs by status"
            >
              <option value="">All statuses</option>
              {statuses.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
            <button type="button" className="button" onClick={runsState.refresh}>
              Refresh
            </button>
          </div>
        }
      />

      {runs.length === 0 ? (
        <EmptyState title="No audit records yet">
          Runs are recorded after each supervisor invocation. Start one from Shipment Management.
        </EmptyState>
      ) : (
        <div className="split split--wide-left">
          <section className="panel panel--list">
            <div className="panel__head">
              <div>
                <h2>Runs ({filteredRuns.length})</h2>
                <p>Newest update first.</p>
              </div>
            </div>
            <ul className="list">
              {filteredRuns.map((run) => (
                <li key={run.thread_id}>
                  <button
                    type="button"
                    className={`list__item ${thread === run.thread_id ? 'list__item--active' : ''}`}
                    onClick={() => {
                      setSelectedId(run.thread_id)
                      onSelectThread(run.thread_id)
                    }}
                  >
                    <span>
                      <strong>{run.headline || run.disruption_type || run.thread_id}</strong>
                      <span className="muted">
                        {run.thread_id} · {run.event_id || 'no event id'} · {when(run.updated_at)}
                      </span>
                    </span>
                    <StatusBadge status={run.status} />
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            {detailState.status === 'loading' && <LoadingState label="Loading audit record…" />}
            {detailState.status === 'error' && (
              <ErrorState message={detailState.error} onRetry={detailState.refresh} />
            )}
            {detail && (
              <>
                <div className="detail__head">
                  <div>
                    <span className="page-header__eyebrow">Audit record</span>
                    <h2 className="section-title mono">{detail.thread_id}</h2>
                    <p className="muted">{detail.summary || 'No summary recorded.'}</p>
                  </div>
                  <StatusBadge status={detail.status} />
                </div>

                <div className="grid grid--tight">
                  <div className="row">
                    <span className="row__label">Event</span>
                    <span className="row__value mono">{detail.event_id || '—'}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Disruption</span>
                    <span className="row__value">
                      {detail.disruption_type || '—'} · {detail.severity || '—'}
                    </span>
                  </div>
                  <div className="row">
                    <span className="row__label">Risk score</span>
                    <span className="row__value">{detail.risk_score ?? '—'}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Recorded</span>
                    <span className="row__value">{when(detail.updated_at)}</span>
                  </div>
                </div>

                <h3 className="subtitle">Deterministic audit report</h3>
                {!audit.verdict ? (
                  <p className="muted">This run did not reach the Compliance & Audit Agent.</p>
                ) : (
                  <>
                    <div className="grid grid--tight">
                      <div className="row">
                        <span className="row__label">Verdict</span>
                        <span className="row__value">{audit.verdict}</span>
                      </div>
                      <div className="row">
                        <span className="row__label">Approved</span>
                        <span className="row__value">{audit.is_approved ? 'yes' : 'no'}</span>
                      </div>
                      <div className="row">
                        <span className="row__label">Compliant</span>
                        <span className="row__value">{audit.is_compliant ? 'yes' : 'no'}</span>
                      </div>
                      <div className="row">
                        <span className="row__label">Within budget</span>
                        <span className="row__value">{audit.is_within_budget ? 'yes' : 'no'}</span>
                      </div>
                      <div className="row">
                        <span className="row__label">Rules checked</span>
                        <span className="row__value">{audit.checked_rule_count ?? '—'}</span>
                      </div>
                      <div className="row">
                        <span className="row__label">Budget utilisation</span>
                        <span className="row__value">{percent(budget.utilisation_percent ?? 0, 1)}</span>
                      </div>
                      <div className="row">
                        <span className="row__label">Proposed / available</span>
                        <span className="row__value">
                          {money(budget.proposed_cost_usd)} / {money(budget.available_budget_usd)}
                        </span>
                      </div>
                      <div className="row">
                        <span className="row__label">Approval level</span>
                        <span className="row__value">
                          {approvalPolicy.requires_approval
                            ? approvalPolicy.approval_level || 'required'
                            : 'not required'}
                        </span>
                      </div>
                    </div>
                    <p className="muted">{audit.explanation}</p>

                    <h3 className="subtitle">Violations</h3>
                    <FindingList items={audit.violations} tone="error" />
                    <h3 className="subtitle">Warnings</h3>
                    <FindingList items={audit.warnings} />
                    {approvalPolicy.reasons?.length > 0 && (
                      <>
                        <h3 className="subtitle">Approval reasons</h3>
                        <ul className="bullets">
                          {approvalPolicy.reasons.map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {audit.audit_evidence?.length > 0 && (
                      <>
                        <h3 className="subtitle">Audit evidence</h3>
                        <div className="table-wrap">
                          <table className="table">
                            <thead>
                              <tr>
                                <th>Check</th>
                                <th>Outcome</th>
                                <th>Detail</th>
                                <th>Source</th>
                              </tr>
                            </thead>
                            <tbody>
                              {audit.audit_evidence.map((entry) => (
                                <tr key={`${entry.check}-${entry.source}`}>
                                  <td>{entry.check}</td>
                                  <td>{entry.outcome}</td>
                                  <td>{entry.detail}</td>
                                  <td className="mono">{entry.source}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </>
                )}

                <h3 className="subtitle">Supervisor decisions</h3>
                {decisions.length === 0 ? (
                  <p className="muted">No decisions recorded.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Step</th>
                          <th>Action</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {decisions.map((decision, index) => (
                          <tr key={`${decision.step}-${index}`}>
                            <td>{decision.step}</td>
                            <td className="mono">{decision.action}</td>
                            <td>{decision.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <h3 className="subtitle">Agent executions</h3>
                {executions.length === 0 ? (
                  <p className="muted">No agent executions recorded.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Agent</th>
                          <th>Attempt</th>
                          <th>Status</th>
                          <th>Duration</th>
                          <th>Tools</th>
                        </tr>
                      </thead>
                      <tbody>
                        {executions.map((execution) => (
                          <tr key={execution.execution_id}>
                            <td>{AGENT_LABELS[execution.agent] ?? execution.agent}</td>
                            <td>{execution.attempt}</td>
                            <td>
                              <StatusBadge status={execution.status} />
                            </td>
                            <td>{Math.round(execution.duration_ms)} ms</td>
                            <td>{execution.tool_calls?.length ?? 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <h3 className="subtitle">Human approval history</h3>
                {approvals.length === 0 ? (
                  <p className="muted">No human decision was recorded for this run.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Action</th>
                          <th>Approver</th>
                          <th>Role</th>
                          <th>Version</th>
                          <th>Decided</th>
                          <th>Comment</th>
                        </tr>
                      </thead>
                      <tbody>
                        {approvals.map((record, index) => (
                          <tr key={`${record.decided_at}-${index}`}>
                            <td>{record.action}</td>
                            <td>{record.approver_id}</td>
                            <td>{record.approver_role || '—'}</td>
                            <td className="mono">{record.proposal_version || '—'}</td>
                            <td>{when(record.decided_at)}</td>
                            <td>{record.comment || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {replanning.length > 0 && (
                  <>
                    <h3 className="subtitle">Replanning</h3>
                    <ul className="bullets">
                      {replanning.map((round) => (
                        <li key={`${round.round}-${round.trigger}`}>
                          Round {round.round} ({round.trigger}): rejected{' '}
                          {round.rejected_scenario_ids.join(', ') || 'none'} —{' '}
                          {round.reasons.join(' · ') || 'no reason recorded'}
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                {errors.length > 0 && (
                  <>
                    <h3 className="subtitle">Errors</h3>
                    <ul className="bullets bullets--error">
                      {errors.map((message) => (
                        <li key={message}>{message}</li>
                      ))}
                    </ul>
                  </>
                )}

                <div className="actions">
                  <button
                    type="button"
                    className="button"
                    onClick={() => onOpenThread(thread, 'agents')}
                  >
                    Inspect agent activity
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
