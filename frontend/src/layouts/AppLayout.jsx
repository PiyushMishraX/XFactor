import { useState } from 'react'

import StatusBadge from '../components/StatusBadge'

function healthLabel(health) {
  if (health.status === 'success') {
    return health.data?.database === 'connected'
      ? 'Backend online · DB connected'
      : 'Backend online · DB degraded'
  }
  if (health.status === 'error') return 'Backend unreachable'
  return 'Checking backend…'
}

function healthTone(health) {
  if (health.status === 'success') {
    return health.data?.database === 'connected' ? 'ok' : 'warn'
  }
  return health.status === 'error' ? 'error' : 'warn'
}

export default function AppLayout({ pages, page, onNavigate, health, children }) {
  const [navOpen, setNavOpen] = useState(false)
  const current = pages.find((item) => item.id === page)

  function navigate(id) {
    onNavigate(id)
    setNavOpen(false)
  }

  return (
    <div className="shell">
      <aside className={`sidebar ${navOpen ? 'sidebar--open' : ''}`}>
        <div className="sidebar__brand">
          <span className="sidebar__mark">XF</span>
          <span>
            <strong>X FACTOR</strong>
            <small>Supply Chain Control Tower</small>
          </span>
        </div>

        <nav className="nav" aria-label="Dashboard sections">
          {pages.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`nav__item ${page === item.id ? 'nav__item--active' : ''}`}
              aria-current={page === item.id ? 'page' : undefined}
              onClick={() => navigate(item.id)}
            >
              <span className="nav__index">{String(index + 1).padStart(2, '0')}</span>
              <span className="nav__text">
                <strong>{item.label}</strong>
                <small>{item.hint}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="sidebar__system">
          <span className="sidebar__system-label">System status</span>
          <span className="sidebar__health">
            <span className={`dot dot--${healthTone(health)}`} />
            {healthLabel(health)}
          </span>
          <span className="sidebar__meta">Gemini reasoning · deterministic decisions</span>
        </div>
      </aside>

      <div className="shell__main">
        <header className="topbar">
          <button
            type="button"
            className="topbar__menu"
            aria-label="Toggle navigation"
            onClick={() => setNavOpen((open) => !open)}
          >
            Menu
          </button>
          <div className="topbar__title">
            <span className="topbar__eyebrow">Control tower / {current?.label ?? 'Overview'}</span>
            <strong>{current?.hint ?? 'Agentic supply chain resilience'}</strong>
          </div>
          <div className="topbar__status">
            <StatusBadge status={health.status === 'success' ? 'live' : health.status} />
            <span className="muted">{healthLabel(health)}</span>
          </div>
        </header>

        <main className="content">{children}</main>

        <footer className="footer">
          SAP Resilient Supply Chains Hackathon · simulated data is always labelled
        </footer>
      </div>
    </div>
  )
}
