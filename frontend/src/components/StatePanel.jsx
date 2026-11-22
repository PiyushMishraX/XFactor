export function LoadingState({ label = 'Loading recorded data…' }) {
  return (
    <div className="state-panel" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <div>
        <strong>Could not load this view.</strong>
        <p>{message}</p>
      </div>
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state-panel state-panel--empty">
      <div>
        <strong>{title}</strong>
        {children && <p>{children}</p>}
      </div>
      {action}
    </div>
  )
}
