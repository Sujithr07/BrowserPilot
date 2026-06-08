import { useState, useEffect } from 'react'

function ViewportPlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 select-none">
      <div className="w-12 h-12 rounded-2xl bg-[#1a1a1a] border border-[#2a2a2a] flex items-center justify-center">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-6 h-6 text-gray-600">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-gray-500 text-sm font-medium">No browser activity</p>
        <p className="text-gray-700 text-xs mt-0.5">Screenshots will appear here as the agent browses</p>
      </div>
    </div>
  )
}

function SpinnerOverlay({ label }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#0a0a0a]/80">
      <svg className="animate-spin w-6 h-6 text-blue-400" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span className="text-gray-400 text-xs">{label}</span>
    </div>
  )
}

export default function BrowserViewport({ screenshotUrl, status, currentTool }) {
  const [displayUrl, setDisplayUrl] = useState(null)
  const [prevUrl, setPrevUrl] = useState(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (screenshotUrl && screenshotUrl !== displayUrl) {
      setPrevUrl(displayUrl)
      setLoaded(false)
      setDisplayUrl(screenshotUrl)
    }
  }, [screenshotUrl])

  const isRunning = status === 'connecting' || status === 'planning' || status === 'running'

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Mock browser chrome */}
      <div className="flex-shrink-0 flex items-center gap-2 px-3 py-2 bg-[#161616] border-b border-[#2a2a2a]">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-[#3a3a3a]" />
          <div className="w-2.5 h-2.5 rounded-full bg-[#3a3a3a]" />
          <div className="w-2.5 h-2.5 rounded-full bg-[#3a3a3a]" />
        </div>
        <div className="flex-1 bg-[#0f0f0f] rounded-md px-3 py-1 text-xs text-gray-600 font-mono truncate border border-[#2a2a2a]">
          {isRunning ? (
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse inline-block" />
              <span className="text-gray-500">
                {currentTool ? `Executing: ${currentTool}` : 'Agent is working…'}
              </span>
            </span>
          ) : displayUrl ? (
            <span className="text-gray-400">Page captured</span>
          ) : (
            <span>Waiting for task…</span>
          )}
        </div>
      </div>

      {/* Viewport content */}
      <div className="relative flex-1 bg-[#0a0a0a] overflow-hidden">
        {!displayUrl && !isRunning && <ViewportPlaceholder />}
        {!displayUrl && isRunning && <SpinnerOverlay label="Initializing browser…" />}

        {/* Crossfade images */}
        {prevUrl && (
          <img
            key={`prev-${prevUrl}`}
            src={prevUrl}
            alt=""
            className="absolute inset-0 w-full h-full object-contain transition-opacity duration-300"
            style={{ opacity: loaded ? 0 : 1 }}
          />
        )}
        {displayUrl && (
          <img
            key={`curr-${displayUrl}`}
            src={displayUrl}
            alt="Current browser view"
            className="absolute inset-0 w-full h-full object-contain transition-opacity duration-300"
            style={{ opacity: loaded ? 1 : 0 }}
            onLoad={() => setLoaded(true)}
          />
        )}

        {/* Loading new screenshot overlay */}
        {displayUrl && !loaded && isRunning && (
          <SpinnerOverlay label="Capturing…" />
        )}
      </div>
    </div>
  )
}
