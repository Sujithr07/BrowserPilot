const variants = {
  idle:             { label: 'Idle',              fg: 'var(--text-secondary)', bg: 'transparent' },
  connecting:       { label: 'Connecting…',       fg: 'var(--accent)',  bg: 'var(--accent-tint)',  pulse: true },
  planning:         { label: 'Planning…',         fg: 'var(--accent)',  bg: 'var(--accent-tint)',  pulse: true },
  running:          { label: 'Browsing…',         fg: 'var(--success)', bg: 'var(--success-tint)', pulse: true },
  waiting_approval: { label: 'Awaiting approval', fg: 'var(--warning)', bg: 'var(--warning-tint)', pulse: true },
  completed:        { label: 'Completed',         fg: 'var(--success)', bg: 'var(--success-tint)' },
  partial:          { label: 'Partial',           fg: 'var(--warning)', bg: 'var(--warning-tint)' },
  failed:           { label: 'Failed',            fg: 'var(--danger)',  bg: 'var(--danger-tint)' },
  stopped:          { label: 'Stopped',           fg: 'var(--text-secondary)', bg: 'var(--bg-card)' },
}

export default function StatusBadge({ status, size = 'sm' }) {
  const v = variants[status] ?? variants.idle
  const dot = size === 'xs' ? 'w-1.5 h-1.5' : 'w-2 h-2'
  const text = size === 'xs' ? 'text-[10px]' : 'text-xs'
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full ${text} font-medium`}
      style={{ color: v.fg, background: v.bg }}
    >
      <span className={`${dot} rounded-full ${v.pulse ? 'pulse-dot' : ''}`} style={{ background: 'currentColor' }} />
      {v.label}
    </span>
  )
}
