import { useState } from 'react'

import AppLayout from './layouts/AppLayout'
import ApprovalCenter from './pages/ApprovalCenter'
import Overview from './pages/Overview'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'approvals', label: 'Approval Center' },
]

function App() {
  const [page, setPage] = useState('overview')

  return (
    <AppLayout>
      <nav className="tabs" aria-label="Sections">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab ${page === tab.id ? 'tab--active' : ''}`}
            aria-current={page === tab.id ? 'page' : undefined}
            onClick={() => setPage(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {page === 'overview' ? <Overview /> : <ApprovalCenter />}
    </AppLayout>
  )
}

export default App
