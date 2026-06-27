import { useState, useCallback } from 'react'
import './App.css'

import { useTaskRunner } from './hooks/useTaskRunner'
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
  const { state: taskState, start, sendApproval, reset } = useTaskRunner()
  const { history, refetch } = useTaskHistory()
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [replayState, setReplayState] = useState(null) // synthetic state for historical tasks
  const [activeGoal, setActiveGoal] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)

  // The active displayed state: live task or loaded replay
  const displayState = selectedTaskId && replayState ? replayState : taskState
  const liveRunning =
    taskState.status === 'connecting' || taskState.status === 'planning' || taskState.status === 'running'

  const handleSubmitGoal = useCallback(async (goal) => {
    setSelectedTaskId(null)
    setReplayState(null)
    setActiveGoal(goal)
    const taskId = await start(goal)
    if (taskId) {
      setTimeout(refetch, 2000)
      setSelectedTaskId(taskId)
    }
  }, [start, refetch])

  const handleSelectTask = useCallback(async (taskId) => {
    setHistoryOpen(false)
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
    reset()
  }, [reset])

  const handleStop = useCallback(() => {
    reset()
    setSelectedTaskId(null)
    setReplayState(null)
    setActiveGoal('')
  }, [reset])

  const handleApprove = useCallback(() => sendApproval(true), [sendApproval])
  const handleDeny = useCallback(() => sendApproval(false), [sendApproval])

  const pageUrl = extractUrl(displayState.steps)

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
      <div style={{ position: 'relative', display: 'flex', height: 'calc(100vh - 40px)', overflow: 'hidden' }}>
        <TaskPanel
          goal={activeGoal}
          status={displayState.status}
          plan={displayState.plan}
          steps={displayState.steps}
          finalAnswer={displayState.finalAnswer}
          metrics={displayState.metrics}
          onSubmitGoal={handleSubmitGoal}
          onToggleHistory={() => setHistoryOpen(o => !o)}
        />

        {/* Right: browser hero */}
        <div style={{ flex: 1, minWidth: 0, background: 'var(--bg-page)' }}>
          <BrowserViewport
            screenshotUrl={displayState.latestScreenshot}
            pageUrl={pageUrl}
            approval={taskState.pendingApproval}
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
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: 0,
            zIndex: 31,
            height: '100%',
            transform: historyOpen ? 'translateX(0)' : 'translateX(-100%)',
            transition: 'transform 200ms ease',
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
