import { useState } from 'react'

const BRANCH_STRIDE = 1000

const label = {
  fontSize: 11,
  fontWeight: 500,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
}

function branchOf(step) {
  const n = step.step_number ?? 0
  return step.branch ?? (n >= BRANCH_STRIDE ? Math.floor(n / BRANCH_STRIDE) + 1 : null)
}

// A plain-English, de-jargoned description for a step row (max 60 chars).
function describeStep(step, planStep) {
  const text = planStep?.instruction || step.instruction || step.observation || step.tool || 'Working…'
  const clean = String(text).replace(/\s+/g, ' ').trim()
  return clean.length > 60 ? clean.slice(0, 60).trimEnd() + '…' : clean
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ width: 11, height: 11 }}>
      <circle cx="12" cy="12" r="9" />
      <path strokeLinecap="round" d="M12 7v5l3 2" />
    </svg>
  )
}

function StepRow({ step, planStep, isActive }) {
  const failed = step.success === false
  const branch = branchOf(step)

  const dotColor = failed ? 'var(--danger)' : isActive ? 'var(--accent)' : 'var(--success)'

  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
      <span
        className={isActive ? 'pulse-dot' : ''}
        style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, marginTop: 5, flexShrink: 0 }}
      />
      <span
        style={{
          fontSize: 11,
          color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: isActive ? 500 : 400,
          lineHeight: 1.5,
        }}
      >
        {branch ? (
          <span style={{ fontSize: 10, color: 'var(--text-muted)', marginRight: 4 }}>[branch {branch}]</span>
        ) : null}
        {describeStep(step, planStep)}
      </span>
    </div>
  )
}

function MetricsOverlay({ metrics, onClose }) {
  const row = (k, v) => (
    <div className="flex items-center justify-between" style={{ marginTop: 4 }}>
      <span style={{ color: 'var(--text-muted)' }}>{k}</span>
      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
    </div>
  )

  const tokens = (metrics?.total_tokens ?? 0).toLocaleString()
  const cost = `$${(metrics?.cost_usd ?? 0).toFixed(4)}`
  const latency = metrics?.llm_latency_s != null ? `${metrics.llm_latency_s.toFixed(1)}s` : '—'

  return (
    <>
      {/* click-away closer */}
      <div style={{ position: 'fixed', inset: 0, zIndex: 20 }} onClick={onClose} />
      <div
        style={{
          position: 'absolute',
          bottom: 52,
          left: 8,
          right: 8,
          zIndex: 21,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 12,
          fontSize: 11,
        }}
      >
        <div style={{ ...label, marginBottom: 6 }}>Metrics</div>
        {row('Tokens', tokens)}
        {row('Cost', cost)}
        {row('Latency', latency)}
      </div>
    </>
  )
}

export default function TaskPanel({
  goal,
  status,
  plan,
  steps = [],
  finalAnswer,
  metrics,
  onSubmitGoal,
  onToggleHistory,
}) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const [metricsOpen, setMetricsOpen] = useState(false)

  const isRunning = status === 'connecting' || status === 'planning' || status === 'running'
  const lastStep = steps[steps.length - 1]

  // Match step_done entries to their plan step for a human-readable instruction.
  const planStepMap = {}
  if (plan?.steps) {
    for (const s of plan.steps) planStepMap[s.step_number] = s
  }

  const thinkingText = (() => {
    if (isRunning) {
      if (!lastStep) return 'Planning…'
      return describeStep(lastStep, planStepMap[lastStep.step_number])
    }
    return 'Waiting for task…'
  })()

  const handleSubmit = () => {
    const g = value.trim()
    if (!g) return
    onSubmitGoal(g)
    setValue('')
  }

  return (
    <div
      style={{
        position: 'relative',
        width: '27%',
        minWidth: 240,
        maxWidth: 320,
        background: 'var(--bg-panel)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      {/* History toggle (top-right, inside sidebar) */}
      <button
        onClick={onToggleHistory}
        className="flex items-center"
        style={{
          position: 'absolute',
          top: 8,
          right: 12,
          zIndex: 5,
          gap: 4,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: '2px 8px',
          fontSize: 11,
          color: 'var(--text-secondary)',
          cursor: 'pointer',
        }}
      >
        <ClockIcon />
        History
      </button>

      {/* Section A — Goal */}
      <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
        <div style={label}>Goal</div>
        <div
          style={{
            marginTop: 8,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '8px 10px',
            fontSize: 12,
            lineHeight: 1.6,
            color: goal ? 'var(--text-primary)' : 'var(--text-muted)',
          }}
        >
          {goal || 'No active task'}
        </div>
      </div>

      {/* Section B — Agent status / Thinking */}
      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center" style={{ gap: 6 }}>
          {isRunning && (
            <span
              className="pulse-dot"
              style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)' }}
            />
          )}
          <span style={label}>Thinking</span>
        </div>
        <div
          style={{
            marginTop: 6,
            fontSize: 12,
            lineHeight: 1.5,
            color: isRunning ? 'var(--text-secondary)' : 'var(--text-muted)',
          }}
        >
          {thinkingText}
        </div>
      </div>

      {/* Section C — Step log */}
      <div style={{ flex: 1, minHeight: 0, padding: 12, overflowY: 'auto', scrollbarWidth: 'thin' }}>
        <div style={{ ...label, marginBottom: 8 }}>Steps</div>

        {/* Plan as the first entry */}
        {plan && (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--text-muted)', marginTop: 5, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Plan — {plan.estimated_steps ?? plan.steps?.length ?? 0} steps
            </span>
          </div>
        )}

        {steps.map((step, i) => (
          <StepRow
            key={i}
            step={step}
            planStep={planStepMap[step.step_number]}
            isActive={isRunning && i === steps.length - 1}
          />
        ))}

        {!plan && steps.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No steps yet</div>
        )}

        {/* Final answer as the last item when completed */}
        {finalAnswer && status === 'completed' && (
          <div
            style={{
              marginTop: 10,
              background: 'var(--bg-card)',
              border: '1px solid var(--success)',
              borderRadius: 6,
              padding: 10,
              fontSize: 12,
              lineHeight: 1.6,
              color: 'var(--text-primary)',
              whiteSpace: 'pre-wrap',
            }}
          >
            {finalAnswer}
          </div>
        )}

        {/* Metrics link */}
        {metrics && (
          <button
            onClick={() => setMetricsOpen(true)}
            style={{
              marginTop: 12,
              background: 'transparent',
              border: 'none',
              padding: 0,
              fontSize: 11,
              color: 'var(--text-muted)',
              cursor: 'pointer',
            }}
          >
            Metrics
          </button>
        )}
      </div>

      {metricsOpen && <MetricsOverlay metrics={metrics} onClose={() => setMetricsOpen(false)} />}

      {/* Section D — Input bar */}
      <div style={{ borderTop: '1px solid var(--border)', padding: '8px 10px' }}>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleSubmit()
            }
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="New task..."
          style={{
            width: '100%',
            background: 'var(--bg-card)',
            border: `1px solid ${focused ? 'var(--border-strong)' : 'var(--border)'}`,
            borderRadius: 6,
            padding: '7px 10px',
            fontSize: 12,
            color: 'var(--text-primary)',
            outline: 'none',
          }}
        />
      </div>
    </div>
  )
}
