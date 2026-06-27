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
        aria-hidden="true"
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

const imgLayer = {
  position: 'absolute',
  inset: 0,
  width: '100%',
  height: '100%',
  objectFit: 'contain',
}

export default function BrowserViewport({ screenshotUrl, pageUrl, status, approval, onSubmitGoal, onApprove, onDeny }) {
  // Crossfade: keep the previous frame beneath while the new one fades in over
  // it. Tracked with the guarded set-during-render pattern (no effect needed).
  const [cur, setCur] = useState(screenshotUrl ?? null)
  const [prev, setPrev] = useState(null)
  if (screenshotUrl !== cur) {
    setPrev(cur)
    setCur(screenshotUrl ?? null)
  }

  // Reload control: bump a cache-buster so the same screenshot path re-fetches,
  // and spin the glyph briefly for feedback.
  const [reloadKey, setReloadKey] = useState(0)
  const [spinning, setSpinning] = useState(false)
  const handleReload = () => {
    if (!cur) return
    setReloadKey((k) => k + 1)
    setSpinning(true)
    setTimeout(() => setSpinning(false), 600)
  }
  const curSrc = cur ? `${cur}${cur.includes('?') ? '&' : '?'}r=${reloadKey}` : cur

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
        <div className="flex" style={{ gap: 8 }} aria-hidden="true">
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

        <button
          className="icon-btn"
          onClick={handleReload}
          disabled={!cur}
          aria-label="Reload screenshot"
          title="Reload screenshot"
        >
          <span className={spinning ? 'spin' : ''} style={{ display: 'inline-block', fontSize: 16, lineHeight: 1 }}>↺</span>
        </button>
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
        {!cur && <EmptyState />}

        {/* Previous frame stays beneath while the current one fades in over it. */}
        {cur && prev && (
          <img key={prev} src={prev} alt="" aria-hidden="true" style={imgLayer} />
        )}

        {cur && (
          <img
            key={cur}
            className="screenshot-in"
            src={curSrc}
            alt="Current browser view"
            style={imgLayer}
          />
        )}

        {/* Inline approval banner overlays the screenshot */}
        <ApprovalBanner approval={approval} onApprove={onApprove} onDeny={onDeny} />
      </div>
    </div>
  )
}
