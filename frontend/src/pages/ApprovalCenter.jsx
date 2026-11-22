import { useCallback, useEffect, useState } from 'react'

import {
  decideApproval,
  getApprovalExecution,
  getPendingApprovals,
} from '../services/api'

const TOKEN_STORAGE_KEY = 'xfactor.approver-token'

function money(value) {
  return `$${Number(value ?? 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function when(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

/**
 * Approval Center — the human side of the Step 6 approval loop.
 *
 * The approver enters their bearer token, reviews the versioned proposal and
 * submits approve, reject or request-modifications. The token is kept in
 * sessionStorage for this tab only; it is sent solely in the Authorization
 * header and never hard-coded in the bundle.
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
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async (activeToken) => {
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
  }, [])

  useEffect(() => {
    if (token) refresh(token)
    // Run once on mount with the token restored for this tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  return (
    <section className="card">
      <header className="card__header">
        <h1>Approval Center</h1>
        <p>
          Review the exact proposal a human is being asked to authorise. Decisions are
          bound to the proposal version and recorded with the approver identity.
        </p>
      </header>

      <div className="card__body">
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

        <h2 className="section-title">Pending proposals</h2>
        {!token && <p className="muted">Enter an approver token to load the queue.</p>}
        {token && pending.length === 0 && !busy && (
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
                <span className="badge">{item.status}</span>
              </button>
            </li>
          ))}
        </ul>

        {proposal && (
          <div className="detail">
            <div className="detail__head">
              <div>
                <h2 className="section-title">{proposal.headline}</h2>
                <p className="muted">{proposal.summary}</p>
              </div>
              <span className="badge badge--warn">{selected.status}</span>
            </div>

            <div className="grid">
              <div className="row">
                <span className="row__label">Proposal version</span>
                <span className="row__value">{proposal.proposal_version}</span>
              </div>
              <div className="row">
                <span className="row__label">Proposal id</span>
                <span className="row__value">{proposal.proposal_id}</span>
              </div>
              <div className="row">
                <span className="row__label">Approval level</span>
                <span className="row__value">{proposal.approval_level || 'None'}</span>
              </div>
              <div className="row">
                <span className="row__label">Audit verdict</span>
                <span className="row__value">{proposal.verdict}</span>
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
                <span className="row__label">Total cost</span>
                <span className="row__value">{money(proposal.total_cost_usd)}</span>
              </div>
              <div className="row">
                <span className="row__label">Transit</span>
                <span className="row__value">{proposal.total_days} day(s)</span>
              </div>
              <div className="row">
                <span className="row__label">Shipment value</span>
                <span className="row__value">{money(proposal.shipment_value_usd)}</span>
              </div>
              <div className="row">
                <span className="row__label">Inventory transfer</span>
                <span className="row__value">{proposal.inventory_transfer_units} unit(s)</span>
              </div>
            </div>

            {proposal.reasons.length > 0 && (
              <>
                <h3 className="subtitle">Why approval is required</h3>
                <ul className="bullets">
                  {proposal.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </>
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
                This proposal is already {selected.status}. No further decision can be
                submitted for version {selected.proposal_version}.
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
              <div className="actions">
                <p className="muted">No execution report is loaded for this proposal.</p>
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  onClick={reloadExecution}
                >
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
          </div>
        )}
      </div>
    </section>
  )
}
