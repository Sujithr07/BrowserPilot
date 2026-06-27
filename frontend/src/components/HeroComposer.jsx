import { useState, useRef, useEffect } from 'react'

export default function HeroComposer({ onSubmit }) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const textareaRef = useRef(null)

  // Auto-grow up to ~5 lines.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  }, [value])

  const submit = () => {
    const g = value.trim()
    if (!g) return
    onSubmit?.(g)
    setValue('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const canSend = value.trim().length > 0

  return (
    <div
      className="flex flex-col items-center justify-center"
      style={{ width: '100%', height: '100%', padding: 24 }}
    >
      <div style={{ width: '100%', maxWidth: 560, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {/* Logo mark */}
        <div style={{ width: 36, height: 36, background: '#f0f0f0', borderRadius: 9, marginBottom: 20 }} />

        <h1 style={{ fontSize: 26, fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.02em', margin: 0 }}>
          What should I do?
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginTop: 10, marginBottom: 24, textAlign: 'center' }}>
          Describe a task and I'll browse the web to get it done.
        </p>

        {/* Composer */}
        <div
          style={{
            position: 'relative',
            width: '100%',
            background: 'var(--bg-card)',
            border: `1px solid ${focused ? 'var(--border-strong)' : 'var(--border)'}`,
            borderRadius: 16,
            padding: '14px 56px 14px 16px',
            transition: 'border-color 120ms ease',
          }}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            rows={1}
            autoFocus
            placeholder="e.g. Find the price of the iPhone 16 on Amazon"
            style={{
              width: '100%',
              resize: 'none',
              border: 'none',
              outline: 'none',
              background: 'transparent',
              color: 'var(--text-primary)',
              fontSize: 15,
              lineHeight: 1.5,
              fontFamily: 'inherit',
              display: 'block',
            }}
          />
          <button
            onClick={submit}
            disabled={!canSend}
            aria-label="Start task"
            style={{
              position: 'absolute',
              right: 12,
              bottom: 12,
              width: 32,
              height: 32,
              borderRadius: '50%',
              border: 'none',
              background: canSend ? 'var(--accent)' : 'var(--border-strong)',
              color: canSend ? '#fff' : 'var(--text-muted)',
              cursor: canSend ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background 120ms ease',
            }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" style={{ width: 16, height: 16 }}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>

        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 12 }}>
          Enter to start · Shift+Enter for a new line
        </p>
      </div>
    </div>
  )
}
