import { useState } from 'react'

import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { useAsyncData } from '../hooks/useAsyncData'
import { getDisruptions, getShipments } from '../services/api'
import { money, when } from '../utils/format'

export default function DisruptionMonitoring({ onOpenThread, onNavigate }) {
  const { status, data, error, refresh } = useAsyncData(
    () => Promise.all([getDisruptions(), getShipments()]),
    [],
  )
  const [selectedId, setSelectedId] = useState('')
  const [severity, setSeverity] = useState('')

  if (status === 'loading' && !data) return <LoadingState />
  if (status === 'error') return <ErrorState message={error} onRetry={refresh} />

  const [disruptionPayload, shipmentPayload] = data ?? [{}, {}]
  const allDisruptions = disruptionPayload.disruptions ?? []
  const shipments = shipmentPayload.shipments ?? []
  const shipmentsById = Object.fromEntries(shipments.map((item) => [item.id, item]))
  const severities = [...new Set(allDisruptions.map((item) => item.severity).filter(Boolean))]
  const items = severity
    ? allDisruptions.filter((item) => item.severity === severity)
    : allDisruptions
  const selected =
    items.find((item) => item.thread_id === selectedId) ?? items[0] ?? null

  return (
    <div className="page">
      <PageHeader
        eyebrow="Disruption monitoring"
        title="Assessed events and shipment exposure"
        description="Every entry is a real supervisor run. The validated assessment is shown when the Disruption Sensing Agent completed; failed runs keep their recorded error and decision."
        actions={
          <div className="actions actions--flush">
            <select
              className="input input--compact"
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
              aria-label="Filter by severity"
            >
              <option value="">All severities</option>
              {severities.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            <button type="button" className="button" onClick={refresh}>
              Refresh
            </button>
          </div>
        }
      />

      {allDisruptions.length === 0 ? (
        <EmptyState
          title="No disruptions have been assessed"
          action={
            <button
              type="button"
              className="button button--ok"
              onClick={() => onNavigate('shipments')}
            >
              Submit a disruption
            </button>
          }
        >
          Shipment Management can submit a real event to the supervisor. Its assessment and
          exposure will appear here.
        </EmptyState>
      ) : (
        <div className="split split--wide-left">
          <section className="panel panel--list">
            <div className="panel__head">
              <div>
                <h2>Events ({items.length})</h2>
                <p>Newest assessment first.</p>
              </div>
            </div>
            <ul className="list">
              {items.map((item) => (
                <li key={item.thread_id}>
                  <button
                    type="button"
                    className={`list__item ${selected?.thread_id === item.thread_id ? 'list__item--active' : ''}`}
                    onClick={() => setSelectedId(item.thread_id)}
                  >
                    <span>
                      <strong>{item.reported_headline || item.disruption_type}</strong>
                      <span className="muted">
                        {item.location || 'Unknown location'} · risk {item.risk_score ?? '—'} ·{' '}
                        {when(item.updated_at)}
                      </span>
                    </span>
                    <StatusBadge status={item.status} />
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {selected && (
            <section className="panel">
              <div className="detail__head">
                <div>
                  <span className="page-header__eyebrow">Assessment</span>
                  <h2 className="section-title">{selected.reported_headline || selected.disruption_type}</h2>
                  <p className="muted">{selected.summary}</p>
                </div>
                <StatusBadge status={selected.severity || selected.status} />
              </div>

              <div className="grid grid--tight">
                <div className="row">
                  <span className="row__label">Workflow</span>
                  <span className="row__value mono">{selected.thread_id}</span>
                </div>
                <div className="row">
                  <span className="row__label">Event</span>
                  <span className="row__value mono">{selected.event_id}</span>
                </div>
                <div className="row">
                  <span className="row__label">Risk score</span>
                  <span className="row__value">{selected.risk_score ?? '—'} / 100</span>
                </div>
                <div className="row">
                  <span className="row__label">Location</span>
                  <span className="row__value">{selected.location || '—'}</span>
                </div>
                <div className="row">
                  <span className="row__label">Source</span>
                  <span className="row__value">{selected.source || '—'}</span>
                </div>
                <div className="row">
                  <span className="row__label">Run status</span>
                  <span className="row__value">{selected.status}</span>
                </div>
              </div>

              {Object.keys(selected.risk_breakdown ?? {}).length > 0 && (
                <>
                  <h3 className="subtitle">Deterministic risk breakdown</h3>
                  <ul className="risk-list">
                    {Object.entries(selected.risk_breakdown).map(([factor, points]) => (
                      <li key={factor}>
                        <span>{factor}</span>
                        <span className="risk-list__points">+{points}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              <h3 className="subtitle">Shipments explicitly affected</h3>
              {selected.affected_shipments.length === 0 ? (
                <p className="muted">
                  The assessment did not validate a specific shipment reference; geographic
                  exposure is handled by the scenario agent.
                </p>
              ) : (
                <div className="cards">
                  {selected.affected_shipments.map((shipmentId) => {
                    const shipment = shipmentsById[shipmentId]
                    return (
                      <div key={shipmentId} className="mini-card">
                        <strong>{shipmentId}</strong>
                        <span>{shipment ? `${shipment.origin} → ${shipment.destination}` : 'Not in master data'}</span>
                        <span className="muted">
                          {shipment
                            ? `${shipment.carrier} · ${shipment.status} · ${money(shipment.value_usd)}`
                            : '—'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}

              {selected.supervisor_decision && (
                <>
                  <h3 className="subtitle">Latest supervisor decision</h3>
                  <div className="quote">
                    <strong>{selected.supervisor_decision.action}</strong>
                    <p>{selected.supervisor_decision.reason || 'No reason recorded.'}</p>
                  </div>
                </>
              )}

              <div className="actions">
                <button
                  type="button"
                  className="button button--ok"
                  onClick={() => onOpenThread(selected.thread_id, 'agents')}
                >
                  Inspect agent activity
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => onOpenThread(selected.thread_id, 'scenarios')}
                >
                  Compare scenarios
                </button>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
