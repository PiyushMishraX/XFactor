import { useState } from 'react'

import BarChart from '../components/BarChart'
import PageHeader from '../components/PageHeader'
import RunSelector from '../components/RunSelector'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { useAsyncData } from '../hooks/useAsyncData'
import { getWorkflowRun, getWorkflowRuns } from '../services/api'
import { compactMoney, money, percent } from '../utils/format'

const METRICS = {
  total_cost_usd: { label: 'Cost', format: compactMoney },
  total_days: { label: 'Transit days', format: (value) => `${Number(value).toFixed(1)}d` },
  risk_score: { label: 'Risk score', format: (value) => String(value) },
}

export default function ScenarioComparison({ activeThread, onSelectThread, onOpenThread }) {
  const runsState = useAsyncData(getWorkflowRuns, [])
  const runs = runsState.data?.runs ?? []
  const thread = activeThread || runs[0]?.thread_id || ''
  const detailState = useAsyncData(
    () => (thread ? getWorkflowRun(thread) : Promise.resolve(null)),
    [thread],
    { enabled: Boolean(thread) },
  )
  const [selectedId, setSelectedId] = useState('')
  const [metric, setMetric] = useState('total_cost_usd')

  if (runsState.status === 'loading' && !runsState.data) return <LoadingState />
  if (runsState.status === 'error') {
    return <ErrorState message={runsState.error} onRetry={runsState.refresh} />
  }

  if (!thread) {
    return (
      <div className="page">
        <PageHeader
          eyebrow="Scenario comparison"
          title="No scenarios recorded yet"
          description="Alternatives appear after the Scenario Planning Agent has built a plan."
        />
        <EmptyState title="Nothing to compare">
          Start a workflow from Shipment Management; the plan and its deterministic evaluation will
          be shown here.
        </EmptyState>
      </div>
    )
  }

  const detail = detailState.data
  const state = detail?.state ?? {}
  const plan = state.scenario_plan ?? {}
  const screening = state.scenario_screening ?? {}
  const audit = state.audit_report ?? {}
  const scenarios = plan.scenarios ?? []
  const evaluations = screening.evaluations ?? []
  const evaluationById = Object.fromEntries(
    evaluations.map((evaluation) => [evaluation.scenario_id, evaluation]),
  )
  const recommendedId = plan.recommended_scenario_id ?? screening.recommended_scenario_id
  const selected =
    scenarios.find((scenario) => scenario.scenario_id === selectedId) ??
    scenarios.find((scenario) => scenario.scenario_id === recommendedId) ??
    scenarios[0] ??
    null
  const selectedEvaluation = selected ? evaluationById[selected.scenario_id] : null

  const chartItems = scenarios.map((scenario) => ({
    id: scenario.scenario_id,
    label: scenario.scenario_id,
    value: scenario[metric],
  }))

  return (
    <div className="page">
      <PageHeader
        eyebrow="Scenario comparison"
        title={plan.event_id ? `Recovery alternatives for ${plan.event_id}` : 'Recovery alternatives'}
        description="Route, delivery time, cost, risk, inventory impact and compliance — all produced by deterministic engines, not the language model."
        actions={<StatusBadge status={audit.verdict ?? detail?.status ?? 'loading'} />}
      />

      <div className="toolbar">
        <RunSelector
          runs={runs}
          value={thread}
          onChange={(value) => {
            setSelectedId('')
            onSelectThread(value)
          }}
          onRefresh={runsState.refresh}
          busy={runsState.status === 'loading'}
        />
      </div>

      {detailState.status === 'error' && (
        <ErrorState message={detailState.error} onRetry={detailState.refresh} />
      )}
      {detailState.status === 'loading' && <LoadingState label="Loading scenario plan…" />}

      {detail && scenarios.length === 0 && (
        <EmptyState title="This run has no scenario plan">
          The supervisor may have stopped before scenario planning, or no alternative could be
          built. See Agent Activity for the recorded decision.
        </EmptyState>
      )}

      {detail && scenarios.length > 0 && (
        <>
          <section className="panel panel--accent">
            <div className="detail__head">
              <div>
                <span className="page-header__eyebrow">Recommended alternative</span>
                <h2 className="section-title">{recommendedId ?? 'No recommendation'}</h2>
                <p>{plan.recommendation_rationale || 'No rationale was recorded.'}</p>
              </div>
              <div className="headline-stats">
                <div>
                  <span>Cost delta</span>
                  <strong>
                    {plan.cost_delta_vs_current_usd == null
                      ? '—'
                      : money(plan.cost_delta_vs_current_usd)}
                  </strong>
                </div>
                <div>
                  <span>Days delta</span>
                  <strong>
                    {plan.days_delta_vs_current == null
                      ? '—'
                      : Number(plan.days_delta_vs_current).toFixed(1)}
                  </strong>
                </div>
                <div>
                  <span>Confidence</span>
                  <strong>{percent((plan.confidence ?? 0) * 100)}</strong>
                </div>
              </div>
            </div>
            <div className="grid grid--tight">
              <div className="row">
                <span className="row__label">Inventory impact</span>
                <span className="row__value">
                  {plan.inventory_impact || screening.inventory_impact || 'Not analysed'}
                </span>
              </div>
              <div className="row">
                <span className="row__label">Inventory covers disruption</span>
                <span className="row__value">
                  {plan.inventory_can_cover_disruption ? 'yes' : 'no'}
                </span>
              </div>
              <div className="row">
                <span className="row__label">Shortage after transfers</span>
                <span className="row__value">
                  {plan.inventory_shortage_after ?? screening.inventory_shortage_after ?? '—'}
                </span>
              </div>
              <div className="row">
                <span className="row__label">Revision round</span>
                <span className="row__value">{plan.revision_round ?? 0}</span>
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Interactive comparison</h2>
                <p>Select a metric and a bar to focus that alternative.</p>
              </div>
              <div className="segmented" role="group" aria-label="Comparison metric">
                {Object.entries(METRICS).map(([key, meta]) => (
                  <button
                    key={key}
                    type="button"
                    className={`segmented__item ${metric === key ? 'segmented__item--active' : ''}`}
                    onClick={() => setMetric(key)}
                  >
                    {meta.label}
                  </button>
                ))}
              </div>
            </div>
            <BarChart
              items={chartItems}
              selectedId={selected?.scenario_id}
              onSelect={setSelectedId}
              formatValue={METRICS[metric].format}
            />
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>All alternatives</h2>
                <p>Compliance status is the deterministic screening verdict.</p>
              </div>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th>Route / approach</th>
                    <th>Delivery</th>
                    <th>Cost</th>
                    <th>Risk</th>
                    <th>Compliance</th>
                    <th>Recommendation</th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.map((scenario) => {
                    const evaluation = evaluationById[scenario.scenario_id]
                    return (
                      <tr
                        key={scenario.scenario_id}
                        className={`table__row--clickable ${selected?.scenario_id === scenario.scenario_id ? 'table__row--active' : ''}`}
                        onClick={() => setSelectedId(scenario.scenario_id)}
                      >
                        <td>
                          <strong>{scenario.scenario_id}</strong>
                          <span className="muted block">rank {scenario.rank}</span>
                        </td>
                        <td>
                          {detail.origin && detail.destination
                            ? `${detail.origin} → ${detail.destination}`
                            : 'Lane not recorded'}
                          <span className="muted block">
                            {scenario.approach} · {scenario.carrier || '—'} /{' '}
                            {scenario.transport_mode || '—'}
                          </span>
                        </td>
                        <td>{Number(scenario.total_days).toFixed(1)} d</td>
                        <td>{money(scenario.total_cost_usd)}</td>
                        <td>{scenario.risk_score}</td>
                        <td>
                          <StatusBadge
                            status={evaluation?.verdict ?? (evaluation?.is_compliant ? 'approved' : 'warn')}
                          />
                          {evaluation && (
                            <span className="muted block">
                              budget {evaluation.is_within_budget ? 'ok' : 'violated'}
                            </span>
                          )}
                        </td>
                        <td>
                          {scenario.scenario_id === recommendedId ? (
                            <span className="chip chip--ok">Recommended</span>
                          ) : (
                            <span className="muted">Alternative</span>
                          )}
                          {evaluation?.requires_approval && (
                            <span className="muted block">
                              approval: {evaluation.approval_level || 'required'}
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {selected && (
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>{selected.scenario_id}</h2>
                  <p>{selected.name || selected.approach}</p>
                </div>
                <StatusBadge
                  status={selectedEvaluation?.verdict ?? (selected.scenario_id === recommendedId ? 'approved' : 'warn')}
                />
              </div>
              <div className="grid grid--tight">
                <div className="row">
                  <span className="row__label">Weighted score</span>
                  <span className="row__value">{Number(selected.weighted_score).toFixed(3)}</span>
                </div>
                <div className="row">
                  <span className="row__label">Carrier reliability</span>
                  <span className="row__value">{percent(selected.carrier_reliability * 100)}</span>
                </div>
                <div className="row">
                  <span className="row__label">Distance</span>
                  <span className="row__value">{Number(selected.distance_km).toFixed(0)} km</span>
                </div>
                <div className="row">
                  <span className="row__label">Feasibility</span>
                  <span className="row__value">{selected.feasibility}</span>
                </div>
              </div>
              {selected.notes?.length > 0 && (
                <>
                  <h3 className="subtitle">Deterministic notes</h3>
                  <ul className="bullets">
                    {selected.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </>
              )}
              {selectedEvaluation && (
                <>
                  <h3 className="subtitle">Screening reason</h3>
                  <p>{selectedEvaluation.reason || 'No reason recorded.'}</p>
                  {selectedEvaluation.violations?.length > 0 && (
                    <ul className="bullets bullets--error">
                      {selectedEvaluation.violations.map((violation) => (
                        <li key={violation}>{violation}</li>
                      ))}
                    </ul>
                  )}
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
            </section>
          )}
        </>
      )}
    </div>
  )
}
