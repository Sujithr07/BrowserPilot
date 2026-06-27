const badgeStyles = {
  planning:  { label: 'planning', fg: 'var(--accent)',         bg: 'var(--accent-tint)' },
  running:   { label: 'running',  fg: 'var(--success)',        bg: 'var(--success-tint)' },
  completed: { label: 'done',     fg: 'var(--success)',        bg: 'var(--success-tint)' },
  failed:    { label: 'failed',   fg: 'var(--danger)',         bg: 'var(--danger-tint)' },
  stopped:   { label: 'stopped',  fg: 'var(--text-secondary)', bg: 'var(--bg-card)' },
}

// Map the runner's raw status onto one of the badge styles.
function normalize(status) {
  if (status === 'connecting' || status === 'planning') return 'planning'
  if (status === 'running') return 'running'
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  if (status === 'stopped') return 'stopped'
  return null
}

function StatusBadge({ status }) {
  const key = normalize(status)
  if (!key) return null
  const s = badgeStyles[key]
  return (
    <span
      style={{
        color: s.fg,
        background: s.bg,
        fontSize: 13,
        fontWeight: 500,
        borderRadius: 5,
        padding: '4px 12px',
      }}
    >
      {s.label}
    </span>
  )
}

export default function TopBar({ taskId, status, stepCount = 0, totalSteps, isRunning, onStop }) {
  // Thin progress bar under the bar: steps done / estimated, full on completion.
  const total = totalSteps ?? 0
  let progress = total > 0 ? Math.min(stepCount / total, 1) : 0
  if (status === 'completed') progress = 1
  const barColor =
    status === 'failed' ? 'var(--danger)'
    : status === 'completed' ? 'var(--success)'
    : status === 'stopped' ? 'var(--text-muted)'
    : 'var(--accent)'

  return (
    <div
      className="flex-shrink-0 flex items-center justify-between"
      style={{
        position: 'relative',
        height: 56,
        background: 'var(--bg-panel)',
        borderBottom: '1px solid var(--border)',
        padding: '0 24px',
      }}
    >
      {/* Left: logo mark + wordmark */}
      <div className="flex items-center" style={{ gap: 12 }}>
        <div style={{ width: 20, height: 20, background: '#f0f0f0', borderRadius: 5 }} />
        <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
          agentflow
        </span>
      </div>

      {/* Right: task id · status · step counter · stop */}
      <div className="flex items-center" style={{ gap: 18 }}>
        {taskId && (
          <span style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>
            {taskId.slice(0, 8)}
          </span>
        )}

        <StatusBadge status={status} />

        {totalSteps != null && (
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            step {stepCount} / {totalSteps}
          </span>
        )}

        {isRunning && (
          <button
            onClick={onStop}
            aria-label="Stop task"
            style={{
              fontSize: 13,
              border: '1px solid var(--danger)',
              color: 'var(--danger)',
              background: 'transparent',
              borderRadius: 7,
              padding: '6px 16px',
              cursor: 'pointer',
            }}
          >
            Stop
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          bottom: 0,
          height: 2,
          width: `${progress * 100}%`,
          background: barColor,
          opacity: progress > 0 ? 1 : 0,
          transition: 'width 300ms ease, opacity 300ms ease',
        }}
      />
    </div>
  )
}
