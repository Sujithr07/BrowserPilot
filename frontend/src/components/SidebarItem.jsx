import StatusBadge from './StatusBadge'

function relativeTime(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function SidebarItem({ task, isSelected, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`relative w-full text-left flex flex-col gap-1 px-3 py-2.5 rounded-lg transition-colors cursor-pointer group ${isSelected ? 'bg-[#242424]' : 'hover:bg-[#1e1e1e]'}`}
    >
      {isSelected && (
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-blue-500 rounded-r" />
      )}
      <p className="text-gray-200 text-xs font-medium leading-snug line-clamp-2 pr-1">{task.goal}</p>
      <div className="flex items-center gap-2">
        <StatusBadge status={task.status} size="xs" />
        <span className="text-gray-600 text-[10px]">{relativeTime(task.created_at)}</span>
      </div>
    </button>
  )
}
