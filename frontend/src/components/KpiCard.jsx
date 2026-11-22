export default function KpiCard({ label, value, hint, tone = '' }) {
  return (
    <div className={`kpi ${tone ? `kpi--${tone}` : ''}`}>
      <span className="kpi__label">{label}</span>
      <strong className="kpi__value">{value}</strong>
      {hint && <span className="kpi__hint">{hint}</span>}
    </div>
  )
}
