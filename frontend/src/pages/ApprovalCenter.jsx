import { useCallback, useEffect, useState } from 'react'

import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { EmptyState } from '../components/StatePanel'
import { AGENTS, AGENT_LABELS } from '../constants/domain'
import {
  decideApproval,
  getApprovalExecution,
  getPendingApprovals,
  getWorkflowRun,
} from '../services/api'
import { money, percent, titleCase, when } from '../utils/format'

const TOKEN_STORAGE_KEY = 'xfactor.approver-token'

function validationTone(status) {
  if (status === 'completed') return 'ok'
  if (status === 'failed') return 'error'
  if (status === 'not_delegated' || status === 'skipped') return 'muted'
  return 'warn'
}

function impactTone(value, { warnAt, errorAt } = {}) {
  if (typeof value !== 'number') return ''
  if (errorAt != null && value >= errorAt) return 'impact--error'
  if (warnAt != null && value >= warnAt) return 'impact--warn'
  return ''
}

/**
 * Approval Center — the human side of the approval loop.
 *
 * The approver enters their bearer token, reviews the versioned proposal,
 * the recorded cost/risk impact and each agent's validation, then submits an
 * authenticated decision. The token is kept in sessionStorage for this tab
 * only; it is sent solely in the Authorization header.
 */
export default function ApprovalCenter() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? '')
  const [tokenDraft, setTokenDraft] = useState(
    () => sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? '',
  )
  const [pending, setPending] = useState([])
  const [selected, setSelected] = useState(null)
  const [comment, setComment] = useState('')
  const [outcome, setOutcome] = useState(null)
  const [execution, setExecution] = useState(null)
  const [runContext, setRunContext] = useState({ status: 'idle', data: null, error: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const loadRun = useCallback(async (threadId) => {
    if (!threadId) {
      setRunContext({ status: 'idle', data: null, error: '' })
      return
    }
    setRunContext({ status: 'loading', data: null, error: '' })
    try {
      setRunContext({ status: 'success', data: await getWorkflowRun(threadId), error: '' })
    } catch (err) {
      setRunContext({ status: 'error', data: null, error: err.message })
    }
  }, [])

  const refresh = useCallback(
    async (activeToken) => {
      if (!activeToken) {
        setPending([])
        return
      }
      setBusy(true)
      setError('')
      try {
        const data = await getPendingApprovals(activeToken)
        setPending(data.pending ?? [])
      } catch (err) {
        setError(err.message)
      } finally {
        setBusy(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (token) refresh(token)
    // Run once on mount with the token restored for this tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    loadRun(selected?.thread_id)
  }, [selected?.thread_id, loadRun])

  function saveToken(event) {
    event.preventDefault()
    const value = tokenDraft.trim()
    setToken(value)
    if (value) sessionStorage.setItem(TOKEN_STORAGE_KEY, value)
    else sessionStorage.removeItem(TOKEN_STORAGE_KEY)
    setSelected(null)
    setOutcome(null)
    setExecution(null)
    setComment('')
    refresh(value)
  }

  function choose(view) {
    setSelected(view)
    setOutcome(null)
    setExecution(view.execution ?? null)
    setComment('')
    setError('')
  }

  async function submitDecision(action) {
    if (!selected) return
    if (action !== 'approve' && !comment.trim()) {
      setError('Add a comment so the supervisor can act on your decision.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await decideApproval(
        selected.thread_id,
        {
          action,
          comment: comment.trim(),
          proposal_version: selected.proposal_version,
        },
        token,
      )
      setOutcome(result)
      setSelected(result.view)
      setExecution(result.execution ?? null)
      setComment('')
      loadRun(result.view?.thread_id ?? selected.thread_id)
      const data = await getPendingApprovals(token)
      setPending(data.pending ?? [])
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function reloadExecution() {
    if (!selected) return
    setBusy(true)
    setError('')
    try {
      setExecution(await getApprovalExecution(selected.thread_id, token))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const proposal = selected?.proposal
  const runState = runContext.data?.state ?? {}
  const assessment = runState.assessment ?? {}
  const plan = runState.scenario_plan ?? {}
  const audit = runState.audit_report ?? {}
  const budget = audit.budget ?? {}
  const executions = runState.agent_executions ?? []
  const chosenScenario = (plan.scenarios ?? []).find(
    (scenario) =>
      scenario.scenario_id ===
      (proposal?.recommended_scenario_id ?? plan.recommended_scenario_id),
  )
  const disruptionRisk = assessment.risk_score
  const routeRisk = chosenScenario?.risk_score
  const remainingBudget = budget.remaining_budget_usd
  const costDelta = plan.cost_delta_vs_current_usd
  const daysDelta = plan.days_delta_vs_current

  return (
    <div className="page">
      <PageHeader
        eyebrow="Approval center"
        title="Authenticated human control"
        description="Review the exact proposal version, its recorded cost and risk impact, and the validations produced by each agent. Decisions are bound to the version and recorded with the approver identity."
        actions={
          <button
            type="button"
            className="button"
            disabled={busy || !token}
            onClick={() => refresh(token)}
          >
            {busy ? 'Refreshing…' : 'Refresh queue'}
          </button>
        }
      />

      <form className="token-form" onSubmit={saveToken}>
        <label className="field">
          <span className="field__label">Approver bearer token</span>
          <input
            className="input"
            type="password"
            autoComplete="off"
            value={tokenDraft}
            onChange={(event) => setTokenDraft(event.target.value)}
            placeholder="Token from APPROVER_CREDENTIALS"
          />
        </label>
        <button type="submit" className="button" disabled={busy}>
          {token ? 'Update token' : 'Load queue'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {!token ? (
        <EmptyState title="Approver token required">
          Enter a token configured in <span className="mono">APPROVER_CREDENTIALS</span>. Every
          approval endpoint fails closed without an authenticated approver.
        </EmptyState>
      ) : (
        <div className="split split--wide-left">
          <section className="panel panel--list">
            <div className="panel__head">
              <div>
                <h2>Pending proposals ({pending.length})</h2>
                <p>One queue item per workflow awaiting a decision.</p>
              </div>
            </div>
            {busy && pending.length === 0 && <p className="muted">Loading queue…</p>}
            {!busy && pending.length === 0 && (
              <p className="muted">No proposals are waiting for a decision.</p>
            )}
            <ul className="list">
              {pending.map((item) => (
                <li key={item.thread_id}>
                  <button
                    type="button"
                    className={`list__item ${selected?.thread_id === item.thread_id ? 'list__item--active' : ''}`}
                    onClick={() => choose(item)}
                  >
                    <span>
                      <strong>{item.proposal.headline}</strong>
                      <span className="muted">
                        {item.thread_id} · version {item.proposal_version} ·{' '}
                        {item.approval_level || 'no named level'} ·{' '}
                        {money(item.proposal.total_cost_usd)}
                      </span>
                    </span>
                    <StatusBadge status={item.status} />
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {!proposal ? (
            <EmptyState title="Select a proposal">
              Choose a queued proposal to review its action, impact and agent validations.
            </EmptyState>
          ) : (
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>{proposal.headline}</h2>
                  <p>{proposal.summary}</p>
                </div>
                <StatusBadge status={selected.status} />
              </div>

              <h3 className="subtitle">Proposed action</h3>
              <div className="actions actions--flush">
                {(proposal.actions ?? []).length === 0 ? (
                  <span className="muted">No execution action types were recorded.</span>
                ) : (
                  proposal.actions.map((action) => (
                    <span key={action} className="chip">
                      {action}
                    </span>
                  ))
                )}
              </div>

              <h3 className="subtitle">Cost and risk impact</h3>
              {runContext.status === 'loading' && (
                <p className="muted">Loading recorded impact from the workflow run…</p>
              )}
              {runContext.status === 'error' && (
                <p className="error-text">
                  Recorded workflow context is unavailable: {runContext.error}. Proposal figures
                  below still come from the versioned proposal snapshot.
                </p>
              )}
              <div className="impact-grid">
                <div className="impact">
                  <span>Proposed cost</span>
                  <strong>{money(proposal.total_cost_usd)}</strong>
                  <small>
                    {budget.available_budget_usd != null
                      ? `budget ${money(budget.available_budget_usd)}`
                      : 'budget not recorded'}
                  </small>
                </div>
                <div className={`impact ${impactTone(costDelta, { warnAt: 0.01 })}`}>
                  <span>Cost delta vs current</span>
                  <strong>{costDelta == null ? '—' : money(costDelta)}</strong>
                  <small>
                    {remainingBudget == null
                      ? 'remaining budget not recorded'
                      : `remaining ${money(remainingBudget)}`}
                  </small>
                </div>
                <div className="impact">
                  <span>Transit</span>
                  <strong>{Number(proposal.total_days).toFixed(1)} d</strong>
                  <small>{daysDelta == null ? 'no delta recorded' : `${Number(daysDelta).toFixed(1)} d vs current`}</small>
                </div>
                <div className={`impact ${impactTone(disruptionRisk, { warnAt: 60, errorAt: 80 })}`}>
                  <span>Disruption risk</span>
                  <strong>{disruptionRisk ?? '—'}</strong>
                  <small>{routeRisk != null ? `chosen route risk ${routeRisk}` : 'route risk not recorded'}</small>
                </div>
                <div className="impact">
                  <span>Inventory transfer</span>
                  <strong>{Number(proposal.inventory_transfer_units ?? 0).toLocaleString()}</strong>
                  <small>
                    {plan.inventory_shortage_after != null
                      ? `shortage after ${plan.inventory_shortage_after}`
                      : 'no inventory analysis'}
                  </small>
                </div>
                <div className={`impact ${proposal.is_within_budget ? 'impact--ok' : 'impact--error'}`}>
                  <span>Budget check</span>
                  <strong>{proposal.is_within_budget ? 'Within' : 'Exceeded'}</strong>
                  <small>
                    {budget.utilisation_percent != null
                      ? `${percent(budget.utilisation_percent, 1)} utilised`
                      : 'not recorded'}
                  </small>
                </div>
              </div>

              <h3 className="subtitle">Agent validations</h3>
              {runContext.status === 'success' ? (
                <>
                  <ul className="validation-list">
                    {AGENTS.map((agent) => {
                      const attempts = executions.filter(
                        (execution) => execution.agent === agent.id,
                      )
                      const latest = attempts.at(-1)
                      const status = latest?.status ?? 'not_delegated'
                      return (
                        <li key={agent.id} className={`validation--${validationTone(status)}`}>
                          <div>
                            <strong>{agent.label}</strong>
                            <small>
                              {latest?.result_summary ||
                                latest?.error ||
                                (latest
                                  ? 'No result summary recorded.'
                                  : 'This agent was not delegated in the recorded run.')}
                            </small>
                          </div>
                          <StatusBadge status={status} />
                        </li>
                      )
                    })}
                  </ul>
                  {audit.verdict && (
                    <div className="quote">
                      <strong>
                        Compliance & Audit verdict: {audit.verdict} ·{' '}
                        {audit.checked_rule_count ?? 0} rule(s) checked
                      </strong>
                      <p>{audit.explanation}</p>
                    </div>
                  )}
                </>
              ) : runContext.status === 'error' ? (
                <p className="muted">
                  Agent validation results could not be read from the run history.
                </p>
              ) : (
                <p className="muted">Loading recorded agent validations…</p>
              )}

              <h3 className="subtitle">Why this needs a human</h3>
              {proposal.reasons.length === 0 ? (
                <p className="muted">No approval reasons were recorded.</p>
              ) : (
                <ul className="bullets">
                  {proposal.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
              {proposal.violations.length > 0 && (
                <>
                  <h3 className="subtitle">Deterministic violations</h3>
                  <ul className="bullets bullets--error">
                    {proposal.violations.map((violation) => (
                      <li key={violation}>{violation}</li>
                    ))}
                  </ul>
                </>
              )}

              <h3 className="subtitle">Proposal metadata</h3>
              <div className="grid grid--tight">
                <div className="row">
                  <span className="row__label">Workflow</span>
                  <span className="row__value mono">{selected.thread_id}</span>
                </div>
                <div className="row">
                  <span className="row__label">Proposal id</span>
                  <span className="row__value">{proposal.proposal_id}</span>
                </div>
                <div className="row">
                  <span className="row__label">Proposal version</span>
                  <span className="row__value">{proposal.proposal_version}</span>
                </div>
                <div className="row">
                  <span className="row__label">Approval level</span>
                  <span className="row__value">{proposal.approval_level || 'None'}</span>
                </div>
                <div className="row">
                  <span className="row__label">Recommendation</span>
                  <span className="row__value">
                    {proposal.recommended_scenario_id ?? proposal.recommended_route_id ?? '—'}
                  </span>
                </div>
                <div className="row">
                  <span className="row__label">Carrier / mode</span>
                  <span className="row__value">
                    {proposal.recommended_carrier || '—'} / {proposal.transport_mode || '—'}
                  </span>
                </div>
                <div className="row">
                  <span className="row__label">Shipment value</span>
                  <span className="row__value">{money(proposal.shipment_value_usd)}</span>
                </div>
                <div className="row">
                  <span className="row__label">Run status</span>
                  <span className="row__value">{titleCase(runContext.data?.status ?? selected.status)}</span>
                </div>
              </div>

              {selected.decision_history.length > 0 && (
                <>
                  <h3 className="subtitle">Decision history</h3>
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Action</th>
                          <th>Approver</th>
                          <th>Role</th>
                          <th>Version</th>
                          <th>Decided at</th>
                          <th>Workflow</th>
                          <th>Comment</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.decision_history.map((record, index) => (
                          <tr key={`${record.decided_at}-${index}`}>
                            <td>{record.action}</td>
                            <td>{record.approver_id}</td>
                            <td>{record.approver_role || '—'}</td>
                            <td className="mono">{record.proposal_version || '—'}</td>
                            <td>{when(record.decided_at)}</td>
                            <td>{record.workflow_status || '—'}</td>
                            <td>{record.comment || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}

              {selected.status === 'pending' ? (
                <div className="decision">
                  <label className="field">
                    <span className="field__label">Comment / modification instructions</span>
                    <textarea
                      className="textarea"
                      rows={3}
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                      placeholder="Required when rejecting or requesting modifications."
                    />
                  </label>
                  <div className="actions">
                    <button
                      type="button"
                      className="button button--ok"
                      disabled={busy}
                      onClick={() => submitDecision('approve')}
                    >
                      Approve and execute
                    </button>
                    <button
                      type="button"
                      className="button button--warn"
                      disabled={busy}
                      onClick={() => submitDecision('request_modifications')}
                    >
                      Request modifications
                    </button>
                    <button
                      type="button"
                      className="button button--danger"
                      disabled={busy}
                      onClick={() => submitDecision('reject')}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ) : (
                <p className="muted">
                  This proposal is already {selected.status}. No further decision can be submitted
                  for version {selected.proposal_version}.
                </p>
              )}

              {outcome && (
                <div className="outcome">
                  <h3 className="subtitle">Decision result</h3>
                  <div className="row">
                    <span className="row__label">Approval status</span>
                    <span className="row__value">{outcome.approval_status}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Workflow status</span>
                    <span className="row__value">{outcome.workflow_status}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Awaiting new decision</span>
                    <span className="row__value">{outcome.awaiting_approval ? 'yes' : 'no'}</span>
                  </div>
                  {outcome.errors?.length > 0 && (
                    <ul className="bullets bullets--error">
                      {outcome.errors.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <h3 className="subtitle">Execution report</h3>
              {!execution && (
                <div className="actions actions--flush">
                  <p className="muted">No execution report is loaded for this proposal.</p>
                  <button type="button" className="button" disabled={busy} onClick={reloadExecution}>
                    Reload execution
                  </button>
                </div>
              )}
              {execution && (
                <>
                  <div className="row">
                    <span className="row__label">Execution status</span>
                    <span className="row__value">{execution.status}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Execution id</span>
                    <span className="row__value">{execution.execution_id}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Idempotent replay</span>
                    <span className="row__value">
                      {execution.idempotent_replay ? 'yes' : 'no'}
                    </span>
                  </div>
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Action</th>
                          <th>Status</th>
                          <th>Adapter</th>
                          <th>Reference</th>
                          <th>Message</th>
                        </tr>
                      </thead>
                      <tbody>
                        {execution.actions.map((action) => (
                          <tr key={action.action_id}>
                            <td>{action.action_type}</td>
                            <td>{action.status}</td>
                            <td>
                              {action.adapter}
                              {action.is_mock ? ' [SIMULATED]' : ''}
                            </td>
                            <td className="mono">{action.external_reference || '—'}</td>
                            <td>{action.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>
          )}
        </div>
      )}

      {selected && (
        <p className="footnote">
          Decision is bound to proposal version {selected.proposal_version}. {AGENT_LABELS.compliance_audit}{' '}
          verdicts are deterministic and cannot be overridden by an approver.
        </p>
      )}
    </div>
  )
}
