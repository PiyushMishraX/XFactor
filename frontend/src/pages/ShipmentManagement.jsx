import { useState } from 'react'

import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { DISRUPTION_TYPES, SEVERITIES } from '../constants/domain'
import { useAsyncData } from '../hooks/useAsyncData'
import { getShipments, startWorkflow } from '../services/api'
import { money } from '../utils/format'

function AssessmentForm({ shipment, onStarted, onNavigate }) {
  const [form, setForm] = useState({
    headline: `Disruption affecting ${shipment.id} (${shipment.origin} → ${shipment.destination})`,
    description: `Operational disruption reported on the ${shipment.origin} to ${shipment.destination} lane carrying ${shipment.cargo}.`,
    source: 'Control Tower operator',
    disruptionType: 'Port Congestion',
    severity: 'Moderate',
    location: shipment.origin,
    budget: '500000',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    const eventId = `EV-UI-${shipment.id}-${Date.now()}`
    const payload = {
      thread_id: eventId,
      request: {
        disruption_report: {
          event_id: eventId,
          headline: form.headline,
          description: form.description,
          source: form.source,
          reported_at: new Date().toISOString(),
        },
        scenario_request: {
          event_id: eventId,
          disruption_type: form.disruptionType,
          location: form.location,
          severity: form.severity,
          origin: shipment.origin,
          destination: shipment.destination,
          cargo_value_usd: shipment.value_usd,
          transport_mode: shipment.transport_mode,
          current_carrier: shipment.carrier,
          available_budget_usd: Number(form.budget) || 0,
          risk_factors: [],
        },
        supplier_id: shipment.supplier_id,
        supplier_risk_tier: shipment.supplier?.risk_tier ?? '',
        origin_country: shipment.supplier?.country ?? '',
      },
    }
    try {
      setResult(await startWorkflow(payload))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <div>
          <h2>Run a disruption assessment</h2>
          <p>
            Submits one real supervisor workflow for {shipment.id}. This calls Gemini and the
            agent graph, so it can take up to a minute.
          </p>
        </div>
        <StatusBadge status={shipment.status} />
      </div>

      <form className="form-grid" onSubmit={submit}>
        <label className="field field--wide">
          <span className="field__label">Headline</span>
          <input
            className="input"
            value={form.headline}
            onChange={(event) => update('headline', event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="field__label">Source</span>
          <input
            className="input"
            value={form.source}
            onChange={(event) => update('source', event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="field__label">Disruption type</span>
          <select
            className="input"
            value={form.disruptionType}
            onChange={(event) => update('disruptionType', event.target.value)}
          >
            {DISRUPTION_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Severity hint</span>
          <select
            className="input"
            value={form.severity}
            onChange={(event) => update('severity', event.target.value)}
          >
            {SEVERITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Location</span>
          <input
            className="input"
            value={form.location}
            onChange={(event) => update('location', event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">Available budget (USD)</span>
          <input
            className="input"
            type="number"
            min="0"
            step="1000"
            value={form.budget}
            onChange={(event) => update('budget', event.target.value)}
          />
        </label>
        <label className="field field--wide">
          <span className="field__label">Description</span>
          <textarea
            className="textarea"
            rows={3}
            value={form.description}
            onChange={(event) => update('description', event.target.value)}
          />
        </label>
        <div className="field field--wide actions actions--flush">
          <button type="submit" className="button button--ok" disabled={busy}>
            {busy ? 'Supervisor running…' : 'Submit to supervisor'}
          </button>
          <span className="muted">
            Event id is generated at submission; the thread id equals it.
          </span>
        </div>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="outcome">
          <div className="detail__head">
            <div>
              <h3 className="subtitle">Workflow result</h3>
              <strong className="mono">{result.thread_id}</strong>
            </div>
            <StatusBadge status={result.status ?? 'completed'} />
          </div>
          <div className="row">
            <span className="row__label">Awaiting approval</span>
            <span className="row__value">{result.awaiting_approval ? 'yes' : 'no'}</span>
          </div>
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
              onClick={() => onStarted(result.thread_id)}
            >
              Open agent activity
            </button>
            {result.awaiting_approval && (
              <button type="button" className="button button--warn" onClick={() => onNavigate('approvals')}>
                Open Approval Center
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

export default function ShipmentManagement({ onOpenThread, onNavigate }) {
  const { status, data, error, refresh } = useAsyncData(getShipments, [])
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [carrier, setCarrier] = useState('')
  const [selectedId, setSelectedId] = useState('')

  if (status === 'loading' && !data) return <LoadingState label="Loading shipment master data…" />
  if (status === 'error') return <ErrorState message={error} onRetry={refresh} />

  const shipments = data?.shipments ?? []
  const carriers = [...new Set(shipments.map((item) => item.carrier).filter(Boolean))]
  const statuses = [...new Set(shipments.map((item) => item.status).filter(Boolean))]
  const filtered = shipments.filter((item) => {
    const haystack = `${item.id} ${item.origin} ${item.destination} ${item.route} ${item.cargo} ${item.carrier}`.toLowerCase()
    return (
      (!query || haystack.includes(query.toLowerCase())) &&
      (!statusFilter || item.status === statusFilter) &&
      (!carrier || item.carrier === carrier)
    )
  })
  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0] ?? null

  return (
    <div className="page">
      <PageHeader
        eyebrow="Shipment management"
        title="Lanes, carriers and disruption intake"
        description="Shipment rows come from PostgreSQL. Submitting one sends a real event to the supervisor; no result is prefilled."
        actions={
          <button type="button" className="button" onClick={refresh}>
            Refresh master data
          </button>
        }
      />

      {shipments.length === 0 ? (
        <EmptyState title="No shipments are seeded">
          Run the reference-data seed (`python -m scripts.seed_reference_data`) to load the demo
          shipment master.
        </EmptyState>
      ) : (
        <>
          <section className="panel">
            <div className="filters">
              <input
                className="input"
                placeholder="Search id, lane, cargo or carrier"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search shipments"
              />
              <select
                className="input"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                aria-label="Filter by shipment status"
              >
                <option value="">All statuses</option>
                {statuses.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              <select
                className="input"
                value={carrier}
                onChange={(event) => setCarrier(event.target.value)}
                aria-label="Filter by carrier"
              >
                <option value="">All carriers</option>
                {carriers.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              <span className="muted">{filtered.length} of {shipments.length}</span>
            </div>

            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Shipment</th>
                    <th>Lane</th>
                    <th>Carrier</th>
                    <th>Cargo</th>
                    <th>Value</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((shipment) => (
                    <tr
                      key={shipment.id}
                      className={`table__row--clickable ${selected?.id === shipment.id ? 'table__row--active' : ''}`}
                      onClick={() => setSelectedId(shipment.id)}
                    >
                      <td className="mono">{shipment.id}</td>
                      <td>
                        {shipment.origin} → {shipment.destination}
                        <span className="muted block">{shipment.transport_mode}</span>
                      </td>
                      <td>{shipment.carrier}</td>
                      <td>{shipment.cargo}</td>
                      <td>{money(shipment.value_usd)}</td>
                      <td>
                        <StatusBadge status={shipment.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {selected && (
            <div className="split split--wide-left">
              <section className="panel">
                <div className="panel__head">
                  <div>
                    <h2>{selected.id}</h2>
                    <p>{selected.route}</p>
                  </div>
                  <StatusBadge status={selected.status} />
                </div>
                <div className="grid grid--tight">
                  <div className="row">
                    <span className="row__label">Supplier</span>
                    <span className="row__value">
                      {selected.supplier?.name ?? selected.supplier_id}
                    </span>
                  </div>
                  <div className="row">
                    <span className="row__label">Supplier risk tier</span>
                    <span className="row__value">{selected.supplier?.risk_tier ?? '—'}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Carrier / mode</span>
                    <span className="row__value">
                      {selected.carrier} / {selected.transport_mode}
                    </span>
                  </div>
                  <div className="row">
                    <span className="row__label">Cargo</span>
                    <span className="row__value">{selected.cargo}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Declared value</span>
                    <span className="row__value">{money(selected.value_usd)}</span>
                  </div>
                  <div className="row">
                    <span className="row__label">Origin country</span>
                    <span className="row__value">{selected.supplier?.country ?? '—'}</span>
                  </div>
                </div>
                <button
                  type="button"
                  className="button"
                  onClick={() => onNavigate('disruptions')}
                >
                  View assessed disruptions
                </button>
              </section>

              <AssessmentForm
                key={selected.id}
                shipment={selected}
                onStarted={(threadId) => onOpenThread(threadId, 'agents')}
                onNavigate={onNavigate}
              />
            </div>
          )}
        </>
      )}

      <p className="footnote">
        Shipment master data is served by the backend from PostgreSQL. These are the seeded demo
        rows, not live SAP shipment records.
      </p>
    </div>
  )
}
