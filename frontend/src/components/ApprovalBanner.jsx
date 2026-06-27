import { useState, useEffect } from 'react'

const TIMEOUT_S = 300

export default function ApprovalBanner({ approval, onApprove, onDeny }) {
  // Retain the last action so text stays visible during the slide-down,
  // and reset the countdown whenever a new approval arrives.
  const [cached, setCached] = useState(null)
  const [secondsLeft, setSecondsLeft] = useState(TIMEOUT_S)
  if (approval && approval !== cached) {
    setCached(approval)
    setSecondsLeft(TIMEOUT_S)
  }

  // Tick the auto-deny countdown; deny when it runs out.
  useEffect(() => {
    if (!approval) return
    if (secondsLeft <= 0) {
      onDeny()
      return
    }
    const id = setTimeout(() => setSecondsLeft(s => s - 1), 1000)
    return () => clearTimeout(id)
  }, [approval, secondsLeft, onDeny])

  // Keyboard: Enter = Confirm, Esc = Deny.
  useEffect(() => {
    if (!approval) return
    const onKey = (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        onApprove()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        onDeny()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [approval, onApprove, onDeny])

  const visible = !!approval
  const action = (approval ?? cached)?.instruction ?? 'continue'
  const progress = Math.max(0, secondsLeft / TIMEOUT_S)

  return (
    <div
      className="flex items-center justify-between"
      style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 10,
        gap: 16,
        background: 'var(--bg-panel)',
        borderTop: '1px solid var(--warning)',
        padding: '16px 22px',
        transform: visible ? 'translateY(0)' : 'translateY(100%)',
        transition: 'transform 200ms ease',
      }}
    >
      {/* Countdown bar across the top edge */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          height: 2,
          width: `${progress * 100}%`,
          background: 'var(--warning)',
          transition: 'width 1000ms linear',
        }}
      />

      {/* Left: warning + prompt + hint */}
      <div className="flex items-center min-w-0" style={{ gap: 12 }}>
        <span style={{ color: 'var(--warning)', fontSize: 18, flexShrink: 0 }}>⚠</span>
        <div className="min-w-0">
          <div className="truncate" style={{ fontSize: 14, color: 'var(--text-primary)' }}>
            About to {action} — confirm?
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            Auto-deny in {secondsLeft}s · Enter to confirm, Esc to deny
          </div>
        </div>
      </div>

      {/* Right: actions */}
      <div className="flex items-center" style={{ gap: 10, flexShrink: 0 }}>
        <button
          onClick={onDeny}
          style={{
            border: '1px solid var(--border-strong)',
            background: 'transparent',
            color: 'var(--text-secondary)',
            borderRadius: 7,
            padding: '8px 20px',
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          Deny
        </button>
        <button
          onClick={onApprove}
          style={{
            background: 'var(--warning)',
            color: '#000',
            border: 'none',
            borderRadius: 7,
            padding: '8px 20px',
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          Confirm
        </button>
      </div>
    </div>
  )
}
