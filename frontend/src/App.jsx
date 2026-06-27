import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

import { useTaskRunner, readActiveTask } from './hooks/useTaskRunner'
import { useTaskHistory } from './hooks/useTaskHistory'

import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import TaskPanel from './components/TaskPanel'
import BrowserViewport from './components/BrowserViewport'

const API_URL = 'http://localhost:8000'

// Derive the current page URL from step data (last navigate target / url field).
function extractUrl(steps) {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    if (s.url) return s.url
    if (s.tool === 'navigate' && s.target) return s.target
  }
  return null
}

export default function App() {
  const { state: taskState, start, resume, sendApproval, stop, reset } = useTaskRunner()
  const { history, refetch } = useTaskHistory()
  // Seed from any task that was running before a refresh (see resume effect).
  const [selectedTaskId, setSelectedTaskId] = useState(() => readActiveTask()?.taskId ?? null)
  const [replayState, setReplayState] = useState(null) // synthetic state for historical tasks
  const [activeGoal, setActiveGoal] = useState(() => readActiveTask()?.goal ?? '')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [selectedStepIdx, setSelectedStepIdx] = useState(null) // pinned step screenshot (null = follow latest)
  const drawerRef = useRef(null)

  // On mount, reconnect to a task that was still running before a page refresh.
  useEffect(() => {
    const active = readActiveTask()
    if (!active?.taskId) return
    resume(active.taskId).then((resumedId) => {
      if (!resumedId) {
        // The task turned out to be gone — clear the stale selection.
        setSelectedTaskId(null)
        setActiveGoal('')
      } else {
        setTimeout(refetch, 2000)
      }
    })
  }, [resume, refetch])

  // History drawer: close on Esc and trap focus inside it while open.
  useEffect(() => {
    if (!historyOpen) return
    const node = drawerRef.current
    if (!node) return

    const previouslyFocused = document.activeElement
    const focusablesIn = () =>
      node.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )

    const first = focusablesIn()[0]
    ;(first ?? node).focus()

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        setHistoryOpen(false)
        return
      }
      if (e.key !== 'Tab') return
      const items = focusablesIn()
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const firstEl = items[0]
      const lastEl = items[items.length - 1]
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault()
        lastEl.focus()
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault()
        firstEl.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus()
    }
  }, [historyOpen])

  // The active displayed state: live task or loaded replay
  const displayState = selectedTaskId && replayState ? replayState : taskState
  const liveRunning =
    taskState.status === 'connecting' || taskState.status === 'planning' || taskState.status === 'running'

  const handleSubmitGoal = useCallback(async (goal) => {
    setSelectedTaskId(null)
    setReplayState(null)
    setSelectedStepIdx(null)
    setActiveGoal(goal)
    const taskId = await start(goal)
    if (taskId) {
      setTimeout(refetch, 2000)
      setSelectedTaskId(taskId)
    }
  }, [start, refetch])

  const handleSelectTask = useCallback(async (taskId) => {
    setHistoryOpen(false)
    setSelectedStepIdx(null)
    if (taskId === selectedTaskId && !replayState) return

    try {
      const res = await fetch(`${API_URL}/replay/${taskId}`)
      if (!res.ok) return
      const data = await res.json()

      const syntheticState = {
        status: data.status ?? 'completed',
        plan: data.plan ?? null,
        steps: data.step_results ?? [],
        latestScreenshot: (() => {
          const lastWithShot = [...(data.step_results ?? [])].reverse().find(s => s.screenshot_path)
          return lastWithShot ? `${API_URL}/${lastWithShot.screenshot_path}` : null
        })(),
        pendingApproval: null,
        metrics: data.metrics ?? null,
        finalAnswer: data.final_answer ?? null,
        error: null,
      }
      setReplayState(syntheticState)
      setSelectedTaskId(taskId)
      const fromHistory = history.find(t => t.task_id === taskId)
      setActiveGoal(data.goal ?? fromHistory?.goal ?? '')
    } catch {
      // ignore
    }
  }, [selectedTaskId, replayState, history])

  const handleNewTask = useCallback(() => {
    setSelectedTaskId(null)
    setReplayState(null)
    setActiveGoal('')
    setHistoryOpen(false)
    setSelectedStepIdx(null)
    reset()
  }, [reset])

  // Interrupt the live run but keep the task on screen.
  const handleStop = useCallback(() => {
    stop()
  }, [stop])

  const handleSelectStep = useCallback((idx) => {
    setSelectedStepIdx(cur => (cur === idx ? null : idx))
  }, [])

  const handleApprove = useCallback(() => sendApproval(true), [sendApproval])
  const handleDeny = useCallback(() => sendApproval(false), [sendApproval])

  const pageUrl = extractUrl(displayState.steps)

  // Hero shows the pinned step's screenshot when one is selected, else the latest.
  const pinnedStep = selectedStepIdx != null ? displayState.steps[selectedStepIdx] : null
  const heroScreenshot = pinnedStep?.screenshot_path
    ? `${API_URL}/${pinnedStep.screenshot_path}`
    : displayState.latestScreenshot

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: 'var(--bg-page)' }}>
      <TopBar
        taskId={selectedTaskId}
        status={displayState.status}
        stepCount={displayState.steps.length}
        totalSteps={displayState.plan?.estimated_steps}
        isRunning={liveRunning}
        onStop={handleStop}
      />

      {/* Two-panel row */}
      <div style={{ position: 'relative', display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>
        <TaskPanel
          goal={activeGoal}
          status={displayState.status}
          plan={displayState.plan}
          steps={displayState.steps}
          finalAnswer={displayState.finalAnswer}
          error={displayState.error}
          metrics={displayState.metrics}
          selectedStepIdx={selectedStepIdx}
          onSelectStep={handleSelectStep}
          onSubmitGoal={handleSubmitGoal}
          onToggleHistory={() => setHistoryOpen(o => !o)}
        />

        {/* Right: browser hero */}
        <div style={{ flex: 1, minWidth: 0, background: 'var(--bg-page)' }}>
          <BrowserViewport
            screenshotUrl={heroScreenshot}
            pageUrl={pageUrl}
            status={displayState.status}
            approval={taskState.pendingApproval}
            onSubmitGoal={handleSubmitGoal}
            onApprove={handleApprove}
            onDeny={handleDeny}
          />
        </div>

        {/* History drawer overlay */}
        <div
          onClick={() => setHistoryOpen(false)}
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 30,
            background: 'rgba(0,0,0,0.4)',
            opacity: historyOpen ? 1 : 0,
            pointerEvents: historyOpen ? 'auto' : 'none',
            transition: 'opacity 200ms ease',
          }}
        />
        <div
          ref={drawerRef}
          role="dialog"
          aria-modal="true"
          aria-label="Task history"
          tabIndex={-1}
          inert={!historyOpen}
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: 0,
            zIndex: 31,
            height: '100%',
            transform: historyOpen ? 'translateX(0)' : 'translateX(-100%)',
            transition: 'transform 200ms ease',
            outline: 'none',
          }}
        >
          <Sidebar
            history={history}
            selectedTaskId={selectedTaskId}
            onSelectTask={handleSelectTask}
            onNewTask={handleNewTask}
          />
        </div>
      </div>
    </div>
  )
}
