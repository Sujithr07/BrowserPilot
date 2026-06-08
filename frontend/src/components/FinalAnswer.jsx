const configs = {
  completed: { border: 'border-green-500/30', bg: 'bg-green-500/5', label: 'text-green-400', text: 'text-green-300', icon: '✓' },
  partial:   { border: 'border-amber-500/30', bg: 'bg-amber-500/5', label: 'text-amber-400', text: 'text-amber-300', icon: '~' },
  failed:    { border: 'border-red-500/30',   bg: 'bg-red-500/5',   label: 'text-red-400',   text: 'text-red-300',   icon: '✗' },
}

export default function FinalAnswer({ answer, status }) {
  const c = configs[status] ?? configs.completed
  if (!answer) return null
  return (
    <div className={`mx-4 my-3 rounded-xl border ${c.border} ${c.bg} p-4`}>
      <div className={`flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider mb-2 ${c.label}`}>
        <span>{c.icon}</span>
        <span>Final Answer</span>
      </div>
      <p className={`text-sm leading-relaxed whitespace-pre-wrap ${c.text}`}>{answer}</p>
    </div>
  )
}
