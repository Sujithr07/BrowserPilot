function Tile({ label, value, sub }) {
  return (
    <div className="bg-[#0f0f0f] rounded-lg p-3 flex flex-col gap-0.5">
      <span className="text-gray-500 text-[10px] uppercase tracking-wider font-medium">{label}</span>
      <span className="text-white text-sm font-semibold">{value}</span>
      {sub && <span className="text-gray-600 text-[10px]">{sub}</span>}
    </div>
  )
}

export default function MetricsPanel({ metrics }) {
  if (!metrics) return null

  const hitRate = metrics.vision_cache_hit_rate != null
    ? `${(metrics.vision_cache_hit_rate * 100).toFixed(0)}% hit`
    : ''
  const provider = metrics.primary_provider?.split('/').pop() ?? '—'
  const latency = metrics.llm_latency_s != null ? `${metrics.llm_latency_s.toFixed(1)}s` : '—'
  const costSaved = metrics.vision_cost_saved_usd != null && metrics.vision_cost_saved_usd > 0
    ? `saved $${metrics.vision_cost_saved_usd.toFixed(4)}`
    : ''

  return (
    <div className="px-4 py-3 border-t border-[#1e1e1e]">
      <p className="text-gray-600 text-[10px] uppercase tracking-wider font-medium mb-2">Usage</p>
      <div className="grid grid-cols-2 gap-2">
        <Tile
          label="Tokens"
          value={(metrics.total_tokens ?? 0).toLocaleString()}
          sub={`${(metrics.input_tokens ?? 0).toLocaleString()}↑ ${(metrics.output_tokens ?? 0).toLocaleString()}↓`}
        />
        <Tile
          label="Cost"
          value={`$${(metrics.cost_usd ?? 0).toFixed(4)}`}
          sub={costSaved}
        />
        <Tile
          label="Vision"
          value={`${metrics.vision_calls ?? 0} calls`}
          sub={`${metrics.vision_cache_hits ?? 0} cached ${hitRate}`}
        />
        <Tile
          label="Provider"
          value={provider}
          sub={latency}
        />
      </div>
    </div>
  )
}
