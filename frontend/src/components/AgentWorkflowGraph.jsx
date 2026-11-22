import { useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { AGENTS } from '../constants/domain'

const TONE_BY_EXECUTION = {
  completed: 'ok',
  failed: 'error',
  skipped: 'muted',
}

function statusOf(agentId, executions, tasks) {
  const attempts = executions.filter((execution) => execution.agent === agentId)
  const latest = attempts[attempts.length - 1]
  if (latest) {
    return {
      label: latest.status,
      tone: TONE_BY_EXECUTION[latest.status] ?? 'warn',
      meta: `${latest.attempt} attempt${latest.attempt === 1 ? '' : 's'} · ${Math.round(
        latest.duration_ms ?? 0,
      )} ms`,
    }
  }
  const task = tasks.filter((item) => item.agent === agentId).at(-1)
  if (task) return { label: 'queued', tone: 'warn', meta: `task ${task.task_id}` }
  return { label: 'not delegated', tone: 'muted', meta: 'no supervisor task' }
}

function FlowNode({ data, selected }) {
  return (
    <div className={`flow-node flow-node--${data.tone} ${selected ? 'flow-node--selected' : ''}`}>
      <Handle type="target" position={Position.Top} />
      <span className="flow-node__eyebrow">{data.eyebrow}</span>
      <strong className="flow-node__label">{data.label}</strong>
      <span className="flow-node__status">
        <span className={`dot dot--${data.tone}`} />
        {data.statusLabel}
      </span>
      {data.meta && <span className="flow-node__meta">{data.meta}</span>}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

const nodeTypes = { agent: FlowNode }

function edgeStyle(tone) {
  const colors = { ok: '#22c55e', error: '#ef4444', warn: '#f59e0b', muted: '#3a4a66' }
  return { stroke: colors[tone] ?? colors.muted, strokeWidth: 1.6 }
}

const markerEnd = { type: MarkerType.ArrowClosed, color: '#4b6288' }

export default function AgentWorkflowGraph({
  executions = [],
  tasks = [],
  status,
  awaitingApproval,
  approvalHistory = [],
  selectedAgent,
  onSelectAgent,
}) {
  const { nodes, edges } = useMemo(() => {
    const agentNodes = AGENTS.map((agent, index) => {
      const state = statusOf(agent.id, executions, tasks)
      return {
        id: agent.id,
        type: 'agent',
        position: { x: index * 210, y: 170 },
        selected: selectedAgent === agent.id,
        data: {
          eyebrow: 'Agent',
          label: agent.label,
          statusLabel: state.label,
          tone: state.tone,
          meta: state.meta,
        },
      }
    })

    const completed = status === 'completed'
    const failed = ['failed', 'iteration_limit_reached'].includes(status)
    const supervisorTone = failed ? 'error' : awaitingApproval ? 'warn' : completed ? 'ok' : 'warn'

    const nodes = [
      {
        id: 'supervisor',
        type: 'agent',
        position: { x: 420, y: 10 },
        data: {
          eyebrow: 'LangGraph',
          label: 'Supervisor',
          statusLabel: status || 'running',
          tone: supervisorTone,
          meta: 'routes on structured state',
        },
      },
      ...agentNodes,
      {
        id: 'approval_gate',
        type: 'agent',
        position: { x: 420, y: 340 },
        data: {
          eyebrow: 'Human control',
          label: 'Approval Gate',
          statusLabel: awaitingApproval
            ? 'awaiting decision'
            : approvalHistory.length
              ? 'decided'
              : 'not reached',
          tone: awaitingApproval ? 'warn' : approvalHistory.length ? 'ok' : 'muted',
          meta: approvalHistory.length
            ? `${approvalHistory.length} decision(s)`
            : 'authenticated approver required',
        },
      },
      {
        id: 'finalize',
        type: 'agent',
        position: { x: 420, y: 490 },
        data: {
          eyebrow: 'Result',
          label: 'Finalize',
          statusLabel: completed ? 'recommendation ready' : status || 'pending',
          tone: completed ? 'ok' : failed ? 'error' : 'muted',
          meta: 'deterministic recommendation',
        },
      },
    ]

    const edges = AGENTS.map((agent) => {
      const state = statusOf(agent.id, executions, tasks)
      return {
        id: `supervisor-${agent.id}`,
        source: 'supervisor',
        target: agent.id,
        animated: state.label === 'queued' || state.label === 'running',
        style: edgeStyle(state.tone),
        markerEnd,
      }
    })

    const scenarioRan = executions.some(
      (execution) => execution.agent === 'scenario_planning' && execution.status === 'completed',
    )
    if (scenarioRan) {
      for (const agentId of ['rerouting_logistics', 'inventory_rebalancing']) {
        edges.push({
          id: `scenario-${agentId}`,
          source: 'scenario_planning',
          target: agentId,
          type: 'smoothstep',
          style: { ...edgeStyle('ok'), strokeDasharray: '5 4' },
          label: 'composed',
          labelStyle: { fill: '#8296ae', fontSize: 10 },
        })
      }
    }

    edges.push({
      id: 'supervisor-gate',
      source: 'supervisor',
      target: 'approval_gate',
      animated: awaitingApproval,
      style: edgeStyle(awaitingApproval ? 'warn' : approvalHistory.length ? 'ok' : 'muted'),
      markerEnd,
    })
    edges.push({
      id: 'gate-finalize',
      source: 'approval_gate',
      target: 'finalize',
      style: edgeStyle(awaitingApproval ? 'warn' : approvalHistory.length ? 'ok' : 'muted'),
      markerEnd,
    })

    return { nodes, edges }
  }, [executions, tasks, status, awaitingApproval, approvalHistory, selectedAgent])

  return (
    <div className="agent-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.35}
        maxZoom={1.5}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelectAgent?.(node.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#23314b" gap={22} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
