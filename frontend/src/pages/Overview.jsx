import StatusBadge from '../components/StatusBadge'
import { useHealthCheck } from '../hooks/useHealthCheck'

/**
 * Overview page — verifies end-to-end frontend <-> backend connectivity.
 */
export default function Overview() {
  const { status, data, error, refresh } = useHealthCheck()
  const backendStatus = status === 'success' ? data.status : status

  return (
    <section className="card">
      <header className="card__header">
        <h1>Control Tower Overview</h1>
        <p>Backend connectivity and platform status.</p>
      </header>

      <div className="card__body">
        <div className="row">
          <span className="row__label">Backend API</span>
          <StatusBadge status={backendStatus} />
        </div>

        {data && (
          <>
            <div className="row">
              <span className="row__label">Service</span>
              <span className="row__value">
                {data.service} v{data.version}
              </span>
            </div>
            <div className="row">
              <span className="row__label">Environment</span>
              <span className="row__value">{data.environment}</span>
            </div>
            <div className="row">
              <span className="row__label">Database</span>
              <span className="row__value">{data.database}</span>
            </div>
            <div className="row">
              <span className="row__label">Checked at</span>
              <span className="row__value">{data.timestamp}</span>
            </div>
          </>
        )}

        {error && <p className="error">Unable to reach the backend: {error}</p>}

        <button
          type="button"
          className="button"
          onClick={refresh}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? 'Checking…' : 'Refresh status'}
        </button>
      </div>
    </section>
  )
}
