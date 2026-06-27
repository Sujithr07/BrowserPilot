import { useState } from 'react'
import ApprovalBanner from './ApprovalBanner'

function EmptyState() {
  return (
    <div
      className="flex flex-col items-center justify-center select-none"
      style={{ width: '100%', height: '100%', gap: 12 }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        style={{ width: 40, height: 40, color: 'var(--border-strong)' }}
      >
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path strokeLinecap="round" d="M3 9h18" />
        <circle cx="6" cy="6.5" r="0.5" fill="currentColor" />
        <circle cx="8" cy="6.5" r="0.5" fill="currentColor" />
      </svg>
      <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Waiting for browser…</span>
    </div>
  )
}

export default function BrowserViewport({ screenshotUrl, pageUrl, approval, onApprove, onDeny }) {
  // Track which url has finished loading so we can fade it in (derived, no effect).
  const [loadedUrl, setLoadedUrl] = useState(null)
  const loaded = loadedUrl === screenshotUrl

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* URL bar */}
      <div
        className="flex items-center"
        style={{
          height: 36,
          background: 'var(--bg-panel)',
          borderBottom: '1px solid var(--border)',
          padding: '0 12px',
          gap: 8,
        }}
      >
        <div className="flex" style={{ gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--border-strong)' }} />
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--border-strong)' }} />
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--border-strong)' }} />
        </div>

        <div
          className="truncate"
          style={{
            flex: 1,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 5,
            padding: '3px 10px',
            fontSize: 11,
            fontFamily: 'monospace',
            color: 'var(--text-muted)',
          }}
        >
          {pageUrl || 'about:blank'}
        </div>

        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>↺</span>
      </div>

      {/* Viewport content */}
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: 'calc(100% - 36px)',
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
