import { useState } from 'react'

import AgentActivity from './pages/AgentActivity'
import ApprovalCenter from './pages/ApprovalCenter'
import AuditHistory from './pages/AuditHistory'
import DisruptionMonitoring from './pages/DisruptionMonitoring'
import InventoryManagement from './pages/InventoryManagement'
import Overview from './pages/Overview'
import ScenarioComparison from './pages/ScenarioComparison'
import ShipmentManagement from './pages/ShipmentManagement'
import { useHealthCheck } from './hooks/useHealthCheck'
import AppLayout from './layouts/AppLayout'

const PAGES = [
  { id: 'overview', label: 'Overview', hint: 'Control-tower posture and latest runs' },
  { id: 'disruptions', label: 'Disruption Monitoring', hint: 'Assessed events and exposure' },
  { id: 'agents', label: 'Agent Activity', hint: 'Live supervisor and agent execution' },
  { id: 'scenarios', label: 'Scenario Comparison', hint: 'Alternatives scored deterministically' },
  { id: 'approvals', label: 'Approval Center', hint: 'Human decisions and execution reports' },
  { id: 'shipments', label: 'Shipment Management', hint: 'Lanes, carriers and disruption intake' },
  { id: 'inventory', label: 'Inventory Management', hint: 'Plant positions and rebalancing' },
  { id: 'audit', label: 'Audit History', hint: 'Decisions, validations and replanning' },
]

export default function App() {
  const [page, setPage] = useState('overview')
  const [activeThread, setActiveThread] = useState('')
  const health = useHealthCheck()

  function openThread(threadId, target = 'agents') {
    setActiveThread(threadId)
    setPage(target)
  }

  const shared = {
    activeThread,
    onSelectThread: setActiveThread,
    onOpenThread: openThread,
    onNavigate: setPage,
  }

  return (
    <AppLayout pages={PAGES} page={page} onNavigate={setPage} health={health}>
      {page === 'overview' && <Overview {...shared} />}
      {page === 'disruptions' && <DisruptionMonitoring {...shared} />}
      {page === 'agents' && <AgentActivity {...shared} />}
      {page === 'scenarios' && <ScenarioComparison {...shared} />}
      {page === 'approvals' && <ApprovalCenter {...shared} />}
      {page === 'shipments' && <ShipmentManagement {...shared} />}
      {page === 'inventory' && <InventoryManagement {...shared} />}
      {page === 'audit' && <AuditHistory {...shared} />}
    </AppLayout>
  )
}
