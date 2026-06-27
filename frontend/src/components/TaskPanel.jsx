import { useState } from 'react'

const BRANCH_STRIDE = 1000

const label = {
  fontSize: 12,
  fontWeight: 500,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.07em',
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
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ width: 13, height: 13 }}>
      <circle cx="12" cy="12" r="9" />
      <path strokeLinecap="round" d="M12 7v5l3 2" />
    </svg>
  )
}

function EyeIcon({ active }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      style={{ width: 14, height: 14, flexShrink: 0, marginTop: 4, color: active ? 'var(--accent)' : 'var(--text-muted)' }}
    >
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function StepRow({ step, planStep, isActive, selected, onClick }) {
  const failed = step.success === false
  const branch = branchOf(step)
  const hasShot = !!step.screenshot_path

  const dotColor = failed ? 'var(--danger)' : isActive ? 'var(--accent)' : 'var(--success)'

  return (
    <div
      className={hasShot ? 'step-row' : ''}
      onClick={hasShot ? onClick : undefined}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        padding: '6px 8px',
        marginLeft: -8,
        marginRight: -8,
        borderRadius: 8,
        background: selected ? 'var(--bg-card)' : 'transparent',
        cursor: hasShot ? 'pointer' : 'default',
      }}
    >
      <span
        className={isActive ? 'pulse-dot' : ''}
        style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor, marginTop: 6, flexShrink: 0 }}
      />
      <span
        style={{
          flex: 1,
          minWidth: 0,
          fontSize: 13,
          color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: isActive ? 500 : 400,
          lineHeight: 1.6,
        }}
      >
        {branch ? (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginRight: 5 }}>[branch {branch}]</span>
        ) : null}
        {describeStep(step, planStep)}
      </span>
      {hasShot && <EyeIcon active={selected} />}
    </div>
  )
}

function MetricsOverlay({ metrics, onClose }) {
  const row = (k, v) => (
    <div className="flex items-center justify-between" style={{ marginTop: 7 }}>
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
          bottom: 76,
          left: 12,
          right: 12,
          zIndex: 21,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: 16,
          fontSize: 13,
        }}
      >
        <div style={{ ...label, marginBottom: 8 }}>Metrics</div>
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
  error,
  metrics,
  selectedStepIdx,
  onSelectStep,
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
    if (status === 'stopped') return 'Stopped'
    if (status === 'completed') return 'Done'
    if (status === 'failed') return 'Failed'
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
        width: '28%',
        minWidth: 300,
        maxWidth: 400,
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
          top: 14,
          right: 18,
          zIndex: 5,
          gap: 6,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 7,
          padding: '6px 12px',
          fontSize: 12.5,
          color: 'var(--text-secondary)',
          cursor: 'pointer',
        }}
      >
        <ClockIcon />
        History
      </button>

      {/* Section A — Goal */}
      <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--border)' }}>
        <div style={label}>Goal</div>
        <div
          style={{
            marginTop: 10,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: '12px 14px',
            fontSize: 14,
            lineHeight: 1.6,
            color: goal ? 'var(--text-primary)' : 'var(--text-muted)',
          }}
        >
          {goal || 'No active task'}
        </div>
      </div>

      {/* Section B — Agent status / Thinking */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center" style={{ gap: 8 }}>
          {isRunning && (
            <span
              className="pulse-dot"
              style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent)' }}
            />
          )}
          <span style={label}>Thinking</span>
        </div>
        <div
          style={{
            marginTop: 8,
            fontSize: 13.5,
            lineHeight: 1.6,
            color: isRunning ? 'var(--text-secondary)' : 'var(--text-muted)',
          }}
        >
          {thinkingText}
        </div>
      </div>

      {/* Section C — Step log */}
      <div style={{ flex: 1, minHeight: 0, padding: '18px 20px', overflowY: 'auto', scrollbarWidth: 'thin' }}>
        <div style={{ ...label, marginBottom: 12 }}>Steps</div>

        {/* Plan as the first entry */}
        {plan && (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 10 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--text-muted)', marginTop: 6, flexShrink: 0 }} />
            <span style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
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
            selected={selectedStepIdx === i}
            onClick={() => onSelectStep?.(i)}
          />
        ))}

        {!plan && steps.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No steps yet</div>
        )}

        {/* Error surfaced when the run fails */}
        {status === 'failed' && error && (
          <div
            style={{
              marginTop: 14,
              background: 'var(--danger-tint)',
              border: '1px solid var(--danger)',
              borderRadius: 10,
              padding: 14,
              fontSize: 13,
              lineHeight: 1.6,
              color: 'var(--text-primary)',
              whiteSpace: 'pre-wrap',
            }}
          >
            <div style={{ color: 'var(--danger)', fontWeight: 600, fontSize: 12, marginBottom: 6 }}>Error</div>
            {error}
          </div>
        )}

        {/* Final answer as the last item when completed */}
        {finalAnswer && status === 'completed' && (
          <div
            style={{
              marginTop: 14,
              background: 'var(--bg-card)',
              border: '1px solid var(--success)',
              borderRadius: 10,
              padding: 14,
              fontSize: 14,
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
              marginTop: 16,
              background: 'transparent',
              border: 'none',
              padding: 0,
              fontSize: 12.5,
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
      <div style={{ borderTop: '1px solid var(--border)', padding: '14px 16px' }}>
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
            borderRadius: 10,
            padding: '11px 14px',
            fontSize: 14,
            color: 'var(--text-primary)',
            outline: 'none',
          }}
        />
      </div>
    </div>
  )
}
