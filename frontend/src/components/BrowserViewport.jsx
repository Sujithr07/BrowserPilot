import { useState } from 'react'
import ApprovalBanner from './ApprovalBanner'
import HeroComposer from './HeroComposer'

function EmptyState() {
  return (
    <div
      className="flex flex-col items-center justify-center select-none"
      style={{ width: '100%', height: '100%', gap: 18 }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        style={{ width: 56, height: 56, color: 'var(--border-strong)' }}
      >
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path strokeLinecap="round" d="M3 9h18" />
        <circle cx="6" cy="6.5" r="0.5" fill="currentColor" />
        <circle cx="8" cy="6.5" r="0.5" fill="currentColor" />
      </svg>
      <span style={{ fontSize: 15, color: 'var(--text-secondary)' }}>Waiting for browser…</span>
    </div>
  )
}

export default function BrowserViewport({ screenshotUrl, pageUrl, status, approval, onSubmitGoal, onApprove, onDeny }) {
  // Track which url has finished loading so we can fade it in (derived, no effect).
  const [loadedUrl, setLoadedUrl] = useState(null)
  const loaded = loadedUrl === screenshotUrl

  // Idle first-run: show the centered composer as the hero (no browser chrome).
  if (status === 'idle' && !screenshotUrl) {
    return (
      <div style={{ width: '100%', height: '100%', background: 'var(--bg-page)' }}>
        <HeroComposer onSubmit={onSubmitGoal} />
      </div>
    )
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* URL bar */}
      <div
        className="flex items-center"
        style={{
          height: 48,
          background: 'var(--bg-panel)',
          borderBottom: '1px solid var(--border)',
          padding: '0 18px',
          gap: 12,
        }}
      >
        <div className="flex" style={{ gap: 8 }}>
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: 'var(--border-strong)' }} />
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: 'var(--border-strong)' }} />
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: 'var(--border-strong)' }} />
        </div>

        <div
          className="truncate"
          style={{
            flex: 1,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '6px 14px',
            fontSize: 13,
            fontFamily: 'monospace',
            color: 'var(--text-muted)',
          }}
        >
          {pageUrl || 'about:blank'}
        </div>

        <span style={{ fontSize: 16, color: 'var(--text-muted)' }}>↺</span>
      </div>

      {/* Viewport content */}
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: 'calc(100% - 48px)',
          background: 'var(--bg-page)',
          overflow: 'hidden',
        }}
      >
        {!screenshotUrl && <EmptyState />}

        {screenshotUrl && (
          <img
            key={screenshotUrl}
            src={screenshotUrl}
            alt="Current browser view"
            onLoad={() => setLoadedUrl(screenshotUrl)}
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              background: 'var(--bg-page)',
              opacity: loaded ? 1 : 0,
              transition: 'opacity 300ms ease',
            }}
          />
        )}

        {/* Inline approval banner overlays the screenshot */}
        <ApprovalBanner approval={approval} onApprove={onApprove} onDeny={onDeny} />
      </div>
    </div>
  )
}
