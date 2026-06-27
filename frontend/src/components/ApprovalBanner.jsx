import { useState } from 'react'

export default function ApprovalBanner({ approval, onApprove, onDeny }) {
  // Retain the last action so text stays visible during the slide-down.
  const [cached, setCached] = useState(null)
  if (approval && approval !== cached) setCached(approval)

  const visible = !!approval
  const action = (approval ?? cached)?.instruction ?? 'continue'

  return (
    <div
      className="flex items-center justify-between"
      style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 10,
        gap: 12,
        background: 'var(--bg-panel)',
        borderTop: '1px solid var(--warning)',
        padding: '10px 14px',
        transform: visible ? 'translateY(0)' : 'translateY(100%)',
        transition: 'transform 200ms ease',
      }}
    >
      {/* Left: warning + prompt */}
      <div className="flex items-center min-w-0" style={{ gap: 8 }}>
        <span style={{ color: 'var(--warning)', fontSize: 14, flexShrink: 0 }}>⚠</span>
        <span className="truncate" style={{ fontSize: 12, color: 'var(--text-primary)' }}>
          About to {action} — confirm?
        </span>
      </div>

      {/* Right: actions */}
      <div className="flex items-center" style={{ gap: 8, flexShrink: 0 }}>
        <button
          onClick={onDeny}
          style={{
            border: '1px solid var(--border-strong)',
            background: 'transparent',
            color: 'var(--text-secondary)',
            borderRadius: 4,
            padding: '4px 14px',
            fontSize: 12,
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
            borderRadius: 4,
            padding: '4px 14px',
            fontSize: 12,
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
