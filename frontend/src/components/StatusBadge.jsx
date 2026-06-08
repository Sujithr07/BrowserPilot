const variants = {
  idle:             { label: 'Idle',              cls: 'bg-gray-500/20 text-gray-400 border-gray-500/30' },
  connecting:       { label: 'Connecting…',       cls: 'bg-blue-500/20 text-blue-400 border-blue-500/30', pulse: true },
  planning:         { label: 'Planning…',         cls: 'bg-purple-500/20 text-purple-400 border-purple-500/30', pulse: true },
  running:          { label: 'Browsing…',         cls: 'bg-blue-500/20 text-blue-400 border-blue-500/30', pulse: true },
  waiting_approval: { label: 'Awaiting approval', cls: 'bg-amber-500/20 text-amber-400 border-amber-500/30', pulse: true },
  completed:        { label: 'Completed',         cls: 'bg-green-500/20 text-green-400 border-green-500/30' },
  failed:           { label: 'Failed',            cls: 'bg-red-500/20 text-red-400 border-red-500/30' },
}

export default function StatusBadge({ status, size = 'sm' }) {
  const v = variants[status] ?? variants.idle
  const dot = size === 'xs' ? 'w-1.5 h-1.5' : 'w-2 h-2'
  const text = size === 'xs' ? 'text-[10px]' : 'text-xs'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border ${text} font-medium ${v.cls}`}>
      <span className={`${dot} rounded-full bg-current ${v.pulse ? 'animate-pulse' : ''}`} />
      {v.label}
    </span>
  )
}
