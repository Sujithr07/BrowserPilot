import { useState } from 'react'
import BranchBadge from './BranchBadge'

const BRANCH_STRIDE = 1000

function stepLabel(step) {
  const n = step.step_number
  const branch = step.branch ?? (n >= BRANCH_STRIDE ? Math.floor(n / BRANCH_STRIDE) + 1 : null)
  const local = n >= BRANCH_STRIDE ? n % BRANCH_STRIDE : n
  return { branch, local }
}

const toolIcons = {
  navigate: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.5 5.969 6.5 6c0 1.105.896 2 2 2a2 2 0 012 2c0 .628-.315 1.181-.797 1.508.143.083.289.159.44.224a.5.5 0 01-.162.867l-.055.02A1.5 1.5 0 018.5 14c0-.828.672-1.5 1.5-1.5.172 0 .337.03.49.084a6.017 6.017 0 01-6.158-4.557zM10 4.5a.5.5 0 01.5.5v.5a.5.5 0 01-1 0V5a.5.5 0 01.5-.5zM6 10a.5.5 0 01.5-.5H7a.5.5 0 010 1h-.5A.5.5 0 016 10z" clipRule="evenodd" />
    </svg>
  ),
  click: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
    </svg>
  ),
  type_text: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M2 5a2 2 0 012-2h12a2 2 0 012 2v2a2 2 0 01-2 2H4a2 2 0 01-2-2V5zm2 0v2h12V5H4zm-1 9a1 1 0 100 2h2a1 1 0 100-2H3zm4 0a1 1 0 100 2h2a1 1 0 100-2H7zm4 0a1 1 0 100 2h2a1 1 0 100-2h-2zm4 0a1 1 0 100 2h2a1 1 0 100-2h-2z" clipRule="evenodd" />
    </svg>
  ),
  extract_text: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clipRule="evenodd" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
    </svg>
  ),
  scroll: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clipRule="evenodd" />
    </svg>
  ),
  task_complete: (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
    </svg>
  ),
}

const defaultIcon = (
  <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
    <path d="M6 10a2 2 0 11-4 0 2 2 0 014 0zM12 10a2 2 0 11-4 0 2 2 0 014 0zM16 12a2 2 0 100-4 2 2 0 000 4z" />
  </svg>
)

const API_URL = 'http://localhost:8000'

export default function ActivityItem({ step, planStep }) {
  const { branch, local } = stepLabel(step)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const icon = toolIcons[step.tool] ?? defaultIcon
  const screenshotUrl = step.screenshot_path ? `${API_URL}/${step.screenshot_path}` : null

  return (
    <>
      <div className={`flex gap-3 px-4 py-3 border-b border-[#1e1e1e] hover:bg-[#161616] transition-colors group ${step.success === false ? 'bg-red-500/5' : ''}`}>
        {/* Tool icon */}
        <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5 ${step.success === false ? 'bg-red-500/20 text-red-400' : step.success ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}`}>
          {icon}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <BranchBadge n={branch} />
            <span className="text-gray-500 text-xs">Step {local}</span>
            <span className={`text-xs font-medium ${step.success === false ? 'text-red-400' : step.success ? 'text-green-400' : 'text-gray-400'}`}>
              {step.success === false ? 'Failed' : step.success ? 'Done' : '…'}
            </span>
          </div>

          {planStep?.instruction && (
            <p className="text-white text-sm mt-1 leading-snug">{planStep.instruction}</p>
          )}
          {step.observation && (
            <p className="text-gray-400 text-xs mt-1 leading-relaxed line-clamp-3">{step.observation}</p>
          )}
          {step.success === false && step.error && (
            <p className="text-red-400 text-xs mt-1 font-mono">{step.error}</p>
          )}
        </div>

        {/* Screenshot thumbnail */}
        {screenshotUrl && (
          <button
            onClick={() => setLightboxOpen(true)}
            className="flex-shrink-0 w-16 h-10 rounded overflow-hidden border border-[#2a2a2a] hover:border-blue-500/50 transition-colors opacity-70 group-hover:opacity-100"
          >
            <img src={screenshotUrl} alt="" className="w-full h-full object-cover" />
          </button>
        )}
      </div>

      {/* Lightbox */}
      {lightboxOpen && screenshotUrl && (
        <div
          className="fixed inset-0 bg-black/90 flex items-center justify-center z-50 p-4"
          onClick={() => setLightboxOpen(false)}
        >
          <img src={screenshotUrl} alt="Step screenshot" className="max-w-full max-h-full rounded-lg shadow-2xl" />
        </div>
      )}
    </>
  )
}
