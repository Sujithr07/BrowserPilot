const badgeStyles = {
  planning:  { label: 'planning', fg: 'var(--accent)',  bg: 'var(--accent-tint)' },
  running:   { label: 'running',  fg: 'var(--success)', bg: 'var(--success-tint)' },
  completed: { label: 'done',     fg: 'var(--success)', bg: 'var(--success-tint)' },
  failed:    { label: 'failed',   fg: 'var(--danger)',  bg: 'var(--danger-tint)' },
}

// Map the runner's raw status onto one of the four badge styles.
function normalize(status) {
  if (status === 'connecting' || status === 'planning') return 'planning'
  if (status === 'running') return 'running'
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
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
        fontSize: 11,
        fontWeight: 500,
        borderRadius: 3,
        padding: '2px 8px',
      }}
    >
      {s.label}
    </span>
  )
}

export default function TopBar({ taskId, status, stepCount = 0, totalSteps, isRunning, onStop }) {
  return (
    <div
      className="flex-shrink-0 flex items-center justify-between"
      style={{
        height: 40,
        background: 'var(--bg-panel)',
        borderBottom: '1px solid var(--border)',
        padding: '0 12px',
      }}
    >
      {/* Left: logo mark + wordmark */}
      <div className="flex items-center" style={{ gap: 8 }}>
        <div style={{ width: 14, height: 14, background: '#f0f0f0', borderRadius: 3 }} />
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>agentflow</span>
      </div>

      {/* Right: task id · status · step counter · stop */}
      <div className="flex items-center" style={{ gap: 12 }}>
        {taskId && (
          <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)' }}>
            {taskId.slice(0, 8)}
          </span>
        )}

        <StatusBadge status={status} />

        {totalSteps != null && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            step {stepCount} / {totalSteps}
          </span>
        )}

        {isRunning && (
          <button
            onClick={onStop}
            style={{
              fontSize: 11,
              border: '1px solid var(--danger)',
              color: 'var(--danger)',
              background: 'transparent',
              borderRadius: 4,
              padding: '2px 10px',
              cursor: 'pointer',
            }}
          >
            Stop
          </button>
        )}
      </div>
    </div>
  )
}
