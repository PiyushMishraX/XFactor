import PageHeader from '../components/PageHeader'
import RunSelector from '../components/RunSelector'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { useAsyncData } from '../hooks/useAsyncData'
import { getInventory, getWorkflowRun, getWorkflowRuns } from '../services/api'

function positionHealth(item) {
  if (item.on_hand_units < item.safety_stock_units) return 'Below safety'
  if (item.on_hand_units < item.reorder_point_units) return 'Reorder'
  return 'Healthy'
}

export default function InventoryManagement({ activeThread, onSelectThread, onOpenThread }) {
  const inventoryState = useAsyncData(getInventory, [])
  const runsState = useAsyncData(getWorkflowRuns, [])
  const runs = runsState.data?.runs ?? []
  const thread = activeThread || runs[0]?.thread_id || ''
  const detailState = useAsyncData(
    () => (thread ? getWorkflowRun(thread) : Promise.resolve(null)),
    [thread],
    { enabled: Boolean(thread) },
  )

  if (inventoryState.status === 'loading' && !inventoryState.data) {
    return <LoadingState label="Loading inventory positions…" />
  }
  if (inventoryState.status === 'error') {
    return <ErrorState message={inventoryState.error} onRetry={inventoryState.refresh} />
  }

  const inventory = inventoryState.data ?? {}
  const items = inventory.items ?? []
  const materials = inventory.materials ?? []
  const rebalancing = detailState.data?.state?.rebalancing ?? {}
  const recommendations = rebalancing.transfer_recommendations ?? []

  return (
    <div className="page">
      <PageHeader
        eyebrow="Inventory management"
        title="Plant positions and rebalancing"
        description="Positions come from the SAP connector. The provenance banner states whether the data is simulated or live."
        actions={
          <button type="button" className="button" onClick={inventoryState.refresh}>
            Refresh inventory
          </button>
        }
      />

      <div className={`source-banner ${inventory.is_mock ? 'source-banner--warn' : 'source-banner--ok'}`}>
        <div>
          <strong>{inventory.is_mock ? '[SIMULATED] SAP inventory' : 'Live SAP inventory'}</strong>
          <span>{inventory.source}</span>
        </div>
        <span className="mono">{inventory.endpoint || 'simulated://sap/inventory'}</span>
      </div>

      {items.length === 0 ? (
        <EmptyState title="No inventory positions returned">
          The SAP connector returned no rows. Check the connector configuration or mock mode.
        </EmptyState>
      ) : (
        <section className="panel">
          <div className="panel__head">
            <div>
              <h2>Inventory positions ({items.length})</h2>
              <p>Safety and reorder thresholds are the connector's own values.</p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Material</th>
                  <th>Plant</th>
                  <th>On hand</th>
                  <th>Safety stock</th>
                  <th>Reorder point</th>
                  <th>Position</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const health = positionHealth(item)
                  return (
                    <tr key={`${item.material_id}-${item.plant}`}>
                      <td>
                        <strong className="mono">{item.material_id}</strong>
                        <span className="muted block">{item.description}</span>
                      </td>
                      <td>{item.plant}</td>
                      <td>{Number(item.on_hand_units).toLocaleString()}</td>
                      <td>{Number(item.safety_stock_units).toLocaleString()}</td>
                      <td>{Number(item.reorder_point_units).toLocaleString()}</td>
                      <td>
                        <StatusBadge status={health === 'Healthy' ? 'ok' : health === 'Reorder' ? 'warn' : 'error'} />
                        <span className="muted block">{health}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="split">
        <section className="panel">
          <div className="panel__head">
            <div>
              <h2>Material master ({materials.length})</h2>
              <p>Material information read through the same SAP connector.</p>
            </div>
          </div>
          {materials.length === 0 ? (
            <p className="muted">No material master records were returned.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Material</th>
                    <th>Type</th>
                    <th>Category</th>
                    <th>Base unit</th>
                  </tr>
                </thead>
                <tbody>
                  {materials.map((material) => (
                    <tr key={material.material_id}>
                      <td>
                        <strong className="mono">{material.material_id}</strong>
                        <span className="muted block">{material.description}</span>
                      </td>
                      <td>{material.material_type}</td>
                      <td>{material.category}</td>
                      <td>{material.base_unit}</td>
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
              <h2>Recorded rebalancing plan</h2>
              <p>Transfer recommendations from a real agent run.</p>
            </div>
          </div>

          <RunSelector
            runs={runs}
            value={thread}
            onChange={onSelectThread}
            onRefresh={runsState.refresh}
            busy={runsState.status === 'loading'}
          />

          {detailState.status === 'error' && (
            <ErrorState message={detailState.error} onRetry={detailState.refresh} />
          )}
          {!thread && (
            <p className="muted">No workflow runs are recorded yet.</p>
          )}
          {thread && detailState.status === 'loading' && <LoadingState label="Loading plan…" />}
          {thread && detailState.status === 'success' && !rebalancing.material_id && (
            <p className="muted">This run did not request or produce an inventory rebalancing plan.</p>
          )}

          {rebalancing.material_id && (
            <>
              <div className="grid grid--tight">
                <div className="row">
                  <span className="row__label">Material</span>
                  <span className="row__value mono">{rebalancing.material_id}</span>
                </div>
                <div className="row">
                  <span className="row__label">Target plant</span>
                  <span className="row__value">{rebalancing.target_plant}</span>
                </div>
                <div className="row">
                  <span className="row__label">Shortage before</span>
                  <span className="row__value">
                    {Number(rebalancing.shortage_before ?? 0).toLocaleString()} units
                  </span>
                </div>
                <div className="row">
                  <span className="row__label">Total transferred</span>
                  <span className="row__value">
                    {Number(rebalancing.total_transferred_units).toLocaleString()} units
                  </span>
                </div>
                <div className="row">
                  <span className="row__label">Shortage after</span>
                  <span className="row__value">
                    {Number(rebalancing.shortage_after).toLocaleString()} units
                  </span>
                </div>
                <div className="row">
                  <span className="row__label">Availability improvement</span>
                  <span className="row__value">
                    {Number(rebalancing.availability_improvement_percent).toFixed(1)}%
                  </span>
                </div>
              </div>

              <h3 className="subtitle">Recommended transfers</h3>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>From</th>
                      <th>To</th>
                      <th>Units</th>
                      <th>Source after</th>
                      <th>Safety stock</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recommendations.map((transfer) => (
                      <tr key={`${transfer.from_plant}-${transfer.to_plant}`}>
                        <td>{transfer.from_plant}</td>
                        <td>{transfer.to_plant}</td>
                        <td>{Number(transfer.units).toLocaleString()}</td>
                        <td>{Number(transfer.source_on_hand_after).toLocaleString()}</td>
                        <td>{transfer.preserves_safety_stock ? 'preserved' : 'at risk'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">{rebalancing.explanation}</p>
            </>
          )}

          {rebalancing.rejected_transfers?.length > 0 && (
            <>
              <h3 className="subtitle">Rejected transfers</h3>
              <ul className="bullets bullets--error">
                {rebalancing.rejected_transfers.map((transfer) => (
                  <li key={`${transfer.from_plant}-${transfer.units_requested}`}>
                    {transfer.from_plant} ({Number(transfer.units_requested).toLocaleString()}{' '}
                    units): {transfer.reason}
                  </li>
                ))}
              </ul>
            </>
          )}

          {rebalancing.material_id && (
            <div className="actions">
              <button
                type="button"
                className="button"
                onClick={() => onOpenThread(thread, 'agents')}
              >
                Inspect agent activity
              </button>
            </div>
          )}
        </section>
      </div>

      {rebalancing.material_id && (
        <p className="footnote">
          Plan for {rebalancing.material_id} at {rebalancing.target_plant} · confidence{' '}
          {rebalancing.confidence != null ? `${(rebalancing.confidence * 100).toFixed(0)}%` : '—'} ·
          safety stock requirement{' '}
          {Number(rebalancing.safety_stock_requirement ?? 0).toLocaleString()} units
        </p>
      )}
    </div>
  )
}
