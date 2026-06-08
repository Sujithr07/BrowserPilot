import { useState } from 'react'

export default function PlanPreview({ plan, isReplan }) {
  const [open, setOpen] = useState(true)
  if (!plan) return null

  return (
    <div className={`border-b border-[#1e1e1e] ${isReplan ? 'bg-blue-500/5' : 'bg-purple-500/5'}`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-white/5 transition-colors"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" className={`w-3.5 h-3.5 flex-shrink-0 transition-transform ${open ? 'rotate-90' : ''} ${isReplan ? 'text-blue-400' : 'text-purple-400'}`}>
          <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
        </svg>
        <span className={`text-xs font-semibold uppercase tracking-wider ${isReplan ? 'text-blue-400' : 'text-purple-400'}`}>
          {isReplan ? 'Recovery Plan' : 'Plan'} — {plan.estimated_steps} steps
        </span>
      </button>
      {open && plan.steps?.length > 0 && (
        <div className="pb-2">
          {plan.steps.map((step, i) => (
            <div key={i} className="flex gap-2 px-4 py-1">
              <span className="text-gray-600 text-xs w-5 flex-shrink-0 text-right">{i + 1}.</span>
              <span className="text-gray-400 text-xs">
                <span className="text-gray-500 font-mono">{step.tool}</span>
                {step.target ? ` → ${step.target}` : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
