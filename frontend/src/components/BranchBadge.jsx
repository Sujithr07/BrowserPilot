export default function BranchBadge({ n }) {
  if (!n) return null
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 mr-1.5">
      B{n}
    </span>
  )
}
