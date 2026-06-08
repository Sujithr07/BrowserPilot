import { useState, useRef, useEffect } from 'react'

export default function GoalInput({ onSubmit, isRunning }) {
  const [value, setValue] = useState('')
  const textareaRef = useRef(null)

  // Auto-resize textarea up to ~3 lines
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 96) + 'px'
  }, [value])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !isRunning && value.trim()) {
      e.preventDefault()
      onSubmit(value.trim())
      setValue('')
    }
  }

  const handleSubmit = () => {
    if (!isRunning && value.trim()) {
      onSubmit(value.trim())
      setValue('')
    }
  }

  return (
    <div className="flex-shrink-0 border-t border-[#2a2a2a] bg-[#111111] p-4">
      <div className="flex gap-3 items-end">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isRunning}
            placeholder="Describe your goal… e.g. Go to Amazon and find the price of iPhone 16"
            rows={1}
            className="w-full bg-[#1a1a1a] border border-[#333] rounded-xl px-4 py-3 text-sm text-white placeholder-gray-600 resize-none focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed leading-relaxed"
          />
        </div>
        <button
          onClick={handleSubmit}
          disabled={isRunning || !value.trim()}
          className="flex-shrink-0 h-11 px-5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center gap-2"
        >
          {isRunning ? (
            <>
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Running
            </>
          ) : (
            <>
              <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path d="M3.105 2.289a.75.75 0 00-.826.95l1.903 6.002H10.75a.75.75 0 010 1.5H4.182l-1.903 6.002a.75.75 0 00.826.95 28.896 28.896 0 0015.293-7.154.75.75 0 000-1.115A28.897 28.897 0 003.105 2.289z" />
              </svg>
              Run
            </>
          )}
        </button>
      </div>
      <p className="text-gray-700 text-xs mt-2 px-1">Enter to run · Shift+Enter for new line</p>
    </div>
  )
}
