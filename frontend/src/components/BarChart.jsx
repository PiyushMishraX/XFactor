/**
 * Small interactive bar chart. Bars are buttons: selecting one focuses the
 * scenario in the surrounding page. Values are the real scenario numbers.
 */
export default function BarChart({ items, selectedId, onSelect, formatValue }) {
  const max = Math.max(...items.map((item) => Number(item.value) || 0), 1)

  return (
    <div className="bar-chart" role="group" aria-label="Scenario comparison chart">
      {items.map((item) => {
        const ratio = Math.max((Number(item.value) || 0) / max, 0.02)
        return (
          <button
            key={item.id}
            type="button"
            className={`bar ${selectedId === item.id ? 'bar--active' : ''}`}
            onClick={() => onSelect?.(item.id)}
            title={`${item.label}: ${formatValue(item.value)}`}
          >
            <span className="bar__value">{formatValue(item.value)}</span>
            <span className="bar__track">
              <span className="bar__fill" style={{ height: `${ratio * 100}%` }} />
            </span>
            <span className="bar__label">{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
