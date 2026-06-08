import { useState, useEffect } from 'react'

const TIMEOUT_S = 300

export default function ApprovalModal({ approval, onApprove, onDeny }) {
  const [secondsLeft, setSecondsLeft] = useState(TIMEOUT_S)

  useEffect(() => {
    setSecondsLeft(TIMEOUT_S)
  }, [approval])

  useEffect(() => {
    if (secondsLeft <= 0) {
      onDeny()
      return
    }
    const id = setTimeout(() => setSecondsLeft(s => s - 1), 1000)
    return () => clearTimeout(id)
  }, [secondsLeft, onDeny])

  if (!approval) return null

  const progress = secondsLeft / TIMEOUT_S

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[#1a1a1a] border border-amber-500/30 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-2 px-5 py-4 bg-amber-500/10 border-b border-amber-500/20">
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 text-amber-400 flex-shrink-0">
            <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
          </svg>
          <h2 className="text-amber-400 text-sm font-semibold">Approval Required</h2>
        </div>

        <div className="p-5">
          <p className="text-gray-300 text-sm mb-3">The agent wants to perform this action:</p>

          {/* Instruction */}
          <div className="bg-[#0f0f0f] border border-[#2a2a2a] rounded-lg p-3 font-mono text-xs text-gray-300 break-all mb-3">
            {approval.instruction}
          </div>

          {/* Meta */}
          <p className="text-gray-600 text-xs mb-4">
            Step {approval.step_number} · Tool: <span className="text-gray-500 font-mono">{approval.tool}</span>
          </p>

          {/* Countdown progress */}
          <div className="mb-5">
            <div className="h-1 bg-[#2a2a2a] rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 rounded-full transition-all duration-1000 ease-linear"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
            <p className="text-gray-600 text-xs mt-1.5">Auto-denying in {secondsLeft}s</p>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={onDeny}
              className="flex-1 py-2.5 rounded-xl bg-[#2a2a2a] hover:bg-red-900/40 text-gray-300 hover:text-red-300 text-sm font-medium transition-colors border border-[#333] hover:border-red-500/30"
            >
              Deny
            </button>
            <button
              onClick={onApprove}
              className="flex-1 py-2.5 rounded-xl bg-green-600 hover:bg-green-500 text-white text-sm font-medium transition-colors"
            >
              Approve
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
