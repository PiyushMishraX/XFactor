import { useState } from 'react'

import AgentWorkflowGraph from '../components/AgentWorkflowGraph'
import PageHeader from '../components/PageHeader'
import RunSelector from '../components/RunSelector'
import StatusBadge from '../components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '../components/StatePanel'
import { AGENTS, AGENT_LABELS } from '../constants/domain'
import { useAsyncData } from '../hooks/useAsyncData'
import { getWorkflowRun, getWorkflowRuns } from '../services/api'
import { titleCase, when } from '../utils/format'

function agentRuntime(agentId, executions, tasks) {
  const attempts = executions.filter((execution) => execution.agent === agentId)
  const latest = attempts.at(-1)
  const task = tasks.filter((item) => item.agent === agentId).at(-1)
  return {
    status: latest?.status ?? (task ? 'queued' : 'not_delegated'),
    attempts,
    latest: latest ?? null,
    task: task ?? null,
  }
}

function TimelineEvent({ time, title, tone, children }) {
  return (
    <li className="timeline__event">
      <span className={`dot dot--${tone}`} />
      <div>
        <div className="timeline__head">
          <strong>{title}</strong>
          <span className="muted">{when(time)}</span>
        </div>
        {children}
      </div>
    </li>
  )
}

export default function AgentActivity({ activeThread, onSelectThread, onOpenThread, onNavigate }) {
  const runsState = useAsyncData(getWorkflowRuns, [])
  const runs = runsState.data?.runs ?? []
  const thread = activeThread || runs[0]?.thread_id || ''

  const detailState = useAsyncData(
    () => (thread ? getWorkflowRun(thread) : Promise.resolve(null)),
    [thread],
    { enabled: Boolean(thread) },
  )
  const [selectedAgent, setSelectedAgent] = useState('')

  if (runsState.status === 'loading' && !runsState.data) return <LoadingState />
  if (runsState.status === 'error') {
    return <ErrorState message={runsState.error} onRetry={runsState.refresh} />
  }

  if (!thread) {
    return (
      <div className="page">
        <PageHeader
          eyebrow="Agent activity"
          title="No workflow has run yet"
          description="This view renders the recorded supervisor and agent events for one workflow thread."
        />
        <EmptyState
          title="Nothing to show"
          action={
            <button
              type="button"
              className="button button--ok"
              onClick={() => onNavigate('shipments')}
            >
              Start a workflow
            </button>
          }
        >
          Submit a disruption from Shipment Management. The five agents, their tools, handoffs
          and decisions will be recorded here.
        </EmptyState>
      </div>
    )
  }

  const detail = detailState.data
  const state = detail?.state ?? {}
  const executions = state.agent_executions ?? []
  const tasks = state.tasks ?? []
  const decisions = state.decisions ?? []
  const replanning = state.replanning ?? []
  const errors = state.errors ?? []
  const approvalHistory = state.approval_history ?? []
  const assessment = state.assessment ?? {}
  const recommendation = state.recommendation ?? {}
  const completedAgents = new Set(
    executions.filter((execution) => execution.status === 'completed').map((execution) => execution.agent),
  )
  const progress = Math.round((completedAgents.size / AGENTS.length) * 100)
  const lastDecision = decisions.at(-1)
  const allTools = executions.flatMap((execution) =>
    (execution.tool_calls ?? []).map((call) => ({
      ...call,
      agent: execution.agent,
      executionId: execution.execution_id,
    })),
  )

  const timeline = [
    ...executions.map((execution) => ({
      kind: 'execution',
      at: execution.started_at,
      execution,
    })),
    ...approvalHistory.map((record) => ({
      kind: 'approval',
      at: record.decided_at,
      record,
    })),
  ].sort((a, b) => new Date(a.at ?? 0) - new Date(b.at ?? 0))

  return (
    <div className="page">
      <PageHeader
        eyebrow="Agent activity"
        title={detail?.headline || assessment.description || 'Supervisor workflow'}
        description="Workflow ID, supervisor decisions and the actual execution record of all five agents."
        actions={
          <StatusBadge status={detailState.status === 'error' ? 'error' : detail?.status ?? 'loading'} />
        }
      />

      <div className="toolbar">
        <RunSelector
          runs={runs}
          value={thread}
          onChange={onSelectThread}
          onRefresh={runsState.refresh}
          busy={runsState.status === 'loading'}
        />
      </div>

      {detailState.status === 'error' && (
        <ErrorState message={detailState.error} onRetry={detailState.refresh} />
      )}

      <section className="kpi-grid kpi-grid--compact">
        <div className="kpi">
          <span className="kpi__label">Workflow</span>
          <strong className="kpi__value kpi__value--mono">{thread}</strong>
          <span className="kpi__hint">{detail?.event_id || '—'}</span>
        </div>
        <div className="kpi">
          <span className="kpi__label">Active disruption</span>
          <strong className="kpi__value kpi__value--small">
            {assessment.disruption_type || detail?.disruption_type || '—'}
          </strong>
          <span className="kpi__hint">
            {assessment.location || detail?.location || 'Unknown location'} · risk{' '}
            {assessment.risk_score ?? detail?.risk_score ?? '—'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi__label">Supervisor decision</span>
          <strong className="kpi__value kpi__value--small">
            {lastDecision?.action ?? 'No decision recorded'}
          </strong>
          <span className="kpi__hint">{lastDecision?.reason ?? '—'}</span>
        </div>
        <div className="kpi">
          <span className="kpi__label">Agent progress</span>
          <strong className="kpi__value">{progress}%</strong>
          <span className="progress" aria-label={`${progress}% complete`}>
            <span className="progress__fill" style={{ width: `${progress}%` }} />
          </span>
          <span className="kpi__hint">
            {completedAgents.size} of {AGENTS.length} agents completed ·{' '}
            {executions.length} attempt(s)
          </span>
        </div>
      </section>

      {detailState.status === 'loading' && <LoadingState label="Loading recorded execution…" />}

      {detail && (
        <>
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Agent workflow</h2>
                <p>
                  Nodes are coloured from recorded executions. Select a node to focus its record
                  below. Dashed scenario edges are the composition handoff.
                </p>
              </div>
              <div className="legend">
                <span><i className="dot dot--ok" /> completed</span>
                <span><i className="dot dot--warn" /> active / queued</span>
                <span><i className="dot dot--error" /> failed</span>
                <span><i className="dot dot--muted" /> not delegated</span>
              </div>
            </div>
            <AgentWorkflowGraph
              executions={executions}
              tasks={tasks}
              status={detail.status}
              awaitingApproval={detail.awaiting_approval}
              approvalHistory={approvalHistory}
              selectedAgent={selectedAgent}
              onSelectAgent={setSelectedAgent}
            />
          </section>

          <section className="agent-grid">
            {AGENTS.map((agent) => {
              const runtime = agentRuntime(agent.id, executions, tasks)
              return (
                <button
                  key={agent.id}
                  type="button"
                  className={`agent-card ${selectedAgent === agent.id ? 'agent-card--active' : ''}`}
                  onClick={() => setSelectedAgent(agent.id)}
                >
                  <div className="agent-card__head">
                    <strong>{agent.label}</strong>
                    <StatusBadge status={runtime.status} />
                  </div>
                  <span className="muted">{agent.focus}</span>
                  <div className="agent-card__meta">
                    <span>{runtime.task?.objective ?? 'No task issued'}</span>
                    <span>
                      {runtime.attempts.length} attempt(s)
                      {runtime.latest?.duration_ms != null
                        ? ` · ${Math.round(runtime.latest.duration_ms)} ms`
                        : ''}
                    </span>
                    <span>
                      {runtime.latest?.tool_calls?.length ?? 0} tool call(s)
                      {runtime.latest?.result_summary
                        ? ` · ${runtime.latest.result_summary}`
                        : ''}
                    </span>
                  </div>
                  {runtime.latest?.error && <span className="error-text">{runtime.latest.error}</span>}
                  {runtime.latest?.findings?.length > 0 && (
                    <ul className="bullets bullets--compact">
                      {runtime.latest.findings.map((finding) => (
                        <li key={finding}>{finding}</li>
                      ))}
                    </ul>
                  )}
                </button>
              )
            })}
          </section>

          <div className="split">
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>Execution timeline</h2>
                  <p>Agent attempts and human decisions in recorded order.</p>
                </div>
              </div>
              {timeline.length === 0 ? (
                <p className="muted">No execution events have been recorded for this run.</p>
              ) : (
                <ol className="timeline">
                  {timeline.map((event) =>
                    event.kind === 'execution' ? (
                      <TimelineEvent
                        key={event.execution.execution_id}
                        time={event.execution.started_at}
                        title={`${AGENT_LABELS[event.execution.agent] ?? event.execution.agent} · ${event.execution.status}`}
                        tone={
                          event.execution.status === 'completed'
                            ? 'ok'
                            : event.execution.status === 'failed'
                              ? 'error'
                              : 'muted'
                        }
                      >
                        <p>
                          Task {event.execution.task_id} · attempt {event.execution.attempt} ·{' '}
                          {Math.round(event.execution.duration_ms)} ms ·{' '}
                          {event.execution.tool_calls?.length ?? 0} tool call(s)
                        </p>
                        {event.execution.result_summary && (
                          <p className="muted">{event.execution.result_summary}</p>
                        )}
                        {event.execution.error && (
                          <p className="error-text">{event.execution.error}</p>
                        )}
                      </TimelineEvent>
                    ) : (
                      <TimelineEvent
                        key={`${event.record.decided_at}-${event.record.approver_id}`}
                        time={event.record.decided_at}
                        title={`Human ${event.record.action} · ${event.record.approver_id}`}
                        tone={event.record.action === 'approve' ? 'ok' : 'warn'}
                      >
                        <p>
                          {event.record.approver_role || 'role not recorded'} · proposal{' '}
                          {event.record.proposal_version || '—'}
                        </p>
                        {event.record.comment && <p className="muted">{event.record.comment}</p>}
                      </TimelineEvent>
                    ),
                  )}
                </ol>
              )}
            </section>

            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>Supervisor decision log</h2>
                  <p>Why each delegation was chosen.</p>
                </div>
              </div>
              {decisions.length === 0 ? (
                <p className="muted">No supervisor decision was recorded.</p>
              ) : (
                <ol className="decision-log">
                  {decisions.map((decision, index) => (
                    <li key={`${decision.step}-${index}`}>
                      <span className="decision-log__step">Step {decision.step}</span>
                      <strong>{decision.action}</strong>
                      <p>{decision.reason}</p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>

          <div className="split">
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>Tools invoked</h2>
                  <p>Recorded by the tools themselves; simulated data is labelled.</p>
                </div>
              </div>
              {allTools.length === 0 ? (
                <p className="muted">No tool calls were recorded.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Agent</th>
                        <th>Tool</th>
                        <th>Status</th>
                        <th>Duration</th>
                        <th>Outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {allTools.map((call, index) => (
                        <tr key={`${call.executionId}-${call.tool}-${index}`}>
                          <td>{AGENT_LABELS[call.agent] ?? call.agent}</td>
                          <td className="mono">{call.tool}</td>
                          <td>
                            <StatusBadge status={call.status} />
                          </td>
                          <td>{Math.round(call.duration_ms ?? 0)} ms</td>
                          <td>
                            {call.outcome || '—'}
                            {call.is_mock ? ' [SIMULATED]' : ''}
                          </td>
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
                  <h2>Handoffs & replanning</h2>
                  <p>Task objects and any bounded revision rounds.</p>
                </div>
              </div>

              <h3 className="subtitle">Supervisor handoffs</h3>
              {tasks.length === 0 ? (
                <p className="muted">No tasks were issued.</p>
              ) : (
                <ul className="handoffs">
                  {tasks.map((task) => (
                    <li key={task.task_id}>
                      <span className="chip">{task.step ? `Step ${task.step}` : 'Task'}</span>
                      <strong>{AGENT_LABELS[task.agent] ?? task.agent}</strong>
                      <span className="muted">{task.reason}</span>
                      <span className="muted">
                        {task.tools.length > 0 ? task.tools.join(', ') : 'no tools declared'}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              <h3 className="subtitle">Replanning events</h3>
              {replanning.length === 0 ? (
                <p className="muted">No replanning was required.</p>
              ) : (
                <ul className="handoffs">
                  {replanning.map((round) => (
                    <li key={`${round.round}-${round.trigger}`}>
                      <span className="chip">Round {round.round}</span>
                      <strong>{round.trigger}</strong>
                      <span className="muted">
                        Rejected: {round.rejected_scenario_ids.join(', ') || '—'}
                      </span>
                      <span className="muted">{round.reasons.join(' · ') || 'No reason recorded'}</span>
                    </li>
                  ))}
                </ul>
              )}

              <h3 className="subtitle">Errors & retries</h3>
              {errors.length === 0 && executions.every((execution) => execution.attempt === 1) ? (
                <p className="muted">No errors or retries were recorded.</p>
              ) : (
                <ul className="bullets bullets--error">
                  {errors.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                  {executions
                    .filter((execution) => execution.attempt > 1)
                    .map((execution) => (
                      <li key={execution.execution_id}>
                        Retry: {AGENT_LABELS[execution.agent] ?? execution.agent} attempt{' '}
                        {execution.attempt}
                      </li>
                    ))}
                </ul>
              )}
            </section>
          </div>

          {recommendation.headline && (
            <section className="panel panel--accent">
              <div className="panel__head">
                <div>
                  <h2>Current recommendation</h2>
                  <p>{recommendation.headline}</p>
                </div>
                <StatusBadge status={recommendation.audit_verdict ?? recommendation.status ?? 'completed'} />
              </div>
              <p>{recommendation.summary}</p>
              <div className="actions">
                <button
                  type="button"
                  className="button"
                  onClick={() => onOpenThread(thread, 'scenarios')}
                >
                  Compare scenarios
                </button>
                <button type="button" className="button" onClick={() => onNavigate('audit')}>
                  Open audit history
                </button>
              </div>
            </section>
          )}
        </>
      )}

      {detailState.status === 'idle' && (
        <EmptyState title="Select a workflow run">Choose a run to inspect its execution.</EmptyState>
      )}
      {detail?.status && (
        <p className="footnote">
          Recorded at {when(detail.updated_at)} · run status {titleCase(detail.status)}
        </p>
      )}
    </div>
  )
}
