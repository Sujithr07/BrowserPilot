import { useEffect, useRef } from 'react'
import ActivityItem from './ActivityItem'
import PlanPreview from './PlanPreview'
import FinalAnswer from './FinalAnswer'
import MetricsPanel from './MetricsPanel'

function ThinkingRow() {
  return (
    <div className="flex gap-3 px-4 py-3 border-b border-[#1e1e1e]">
      <div className="w-7 h-7 rounded-lg bg-purple-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
        <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 text-purple-400 animate-pulse">
          <path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm0 2a6 6 0 110 12A6 6 0 0110 4z" />
        </svg>
      </div>
      <div className="flex items-center gap-1 mt-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}

export default function ActivityFeed({ status, plan, replan, steps, finalAnswer, metrics }) {
  const bottomRef = useRef(null)
  const containerRef = useRef(null)

  const isRunning = status === 'connecting' || status === 'planning' || status === 'running'

  // Auto-scroll to bottom if user is within 80px of it
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (nearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [steps, status, finalAnswer])

  // Build a plan step index for matching step_done to plan step instruction
  const planStepMap = {}
  if (plan?.steps) {
    for (const s of plan.steps) planStepMap[s.step_number] = s
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto min-h-0">
      {/* Empty state */}
      {!plan && !steps.length && !isRunning && (
        <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-6">
          <p className="text-gray-600 text-sm">Activity will appear here</p>
          <p className="text-gray-700 text-xs">Enter a goal below and click Run to start</p>
        </div>
      )}

      {/* Connecting state */}
      {status === 'connecting' && !plan && (
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[#1e1e1e]">
          <svg className="animate-spin w-4 h-4 text-blue-400 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-gray-400 text-sm">Connecting…</span>
        </div>
      )}

      {plan && <PlanPreview plan={plan} isReplan={false} />}
      {replan && <PlanPreview plan={replan} isReplan={true} />}

      {steps.map((step, i) => (
        <ActivityItem key={i} step={step} planStep={planStepMap[step.step_number]} />
      ))}

      {isRunning && steps.length > 0 && <ThinkingRow />}

      {finalAnswer && <FinalAnswer answer={finalAnswer} status={status} />}
      {metrics && <MetricsPanel metrics={metrics} />}

      <div ref={bottomRef} />
    </div>
  )
}
