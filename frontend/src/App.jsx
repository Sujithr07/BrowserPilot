import { useState, useCallback } from 'react'
import './App.css'

import { useTaskRunner } from './hooks/useTaskRunner'
import { useTaskHistory } from './hooks/useTaskHistory'

import Sidebar from './components/Sidebar'
import BrowserViewport from './components/BrowserViewport'
import ActivityFeed from './components/ActivityFeed'
import GoalInput from './components/GoalInput'
import ApprovalModal from './components/ApprovalModal'
import StatusBadge from './components/StatusBadge'

const API_URL = 'http://localhost:8000'

function MainPanel({ taskState, replan, onSubmitGoal, onApprove, onDeny }) {
  const isRunning = taskState.status === 'connecting' || taskState.status === 'planning' || taskState.status === 'running'
  const lastStep = taskState.steps[taskState.steps.length - 1]
  const currentTool = isRunning && lastStep ? lastStep.tool : null

  return (
    <div className="flex flex-col flex-1 min-w-0 min-h-0 h-full bg-[#111111]">
      {/* Top bar */}
      <div className="flex-shrink-0 flex items-center justify-between px-4 py-2 border-b border-[#2a2a2a] bg-[#161616]">
        <div className="flex items-center gap-2">
          <span className="text-gray-400 text-xs">
            {taskState.status === 'idle' ? 'Ready' : ''}
          </span>
        </div>
        <StatusBadge
          status={taskState.pendingApproval ? 'waiting_approval' : taskState.status}
        />
      </div>

      {/* Split: viewport (top) + feed (bottom) */}
      <div className="flex flex-col flex-1 min-h-0">
        {/* Browser viewport — 45% of available height */}
        <div className="flex-shrink-0" style={{ height: '45%' }}>
          <BrowserViewport
            screenshotUrl={taskState.latestScreenshot}
            status={taskState.status}
            currentTool={currentTool}
          />
        </div>

        {/* Divider */}
        <div className="flex-shrink-0 h-px bg-[#2a2a2a]" />

        {/* Activity feed — fills remaining space */}
        <div className="flex flex-col flex-1 min-h-0">
          {/* Feed header */}
          <div className="flex-shrink-0 flex items-center px-4 py-2 border-b border-[#1e1e1e]">
            <span className="text-gray-600 text-xs font-medium uppercase tracking-wider">Activity</span>
          </div>

          <ActivityFeed
            status={taskState.status}
            plan={taskState.plan}
            replan={replan}
            steps={taskState.steps}
            finalAnswer={taskState.finalAnswer}
            metrics={taskState.metrics}
          />
        </div>
      </div>

      {/* Goal input bar */}
      <GoalInput onSubmit={onSubmitGoal} isRunning={isRunning} />
    </div>
  )
}

export default function App() {
  const { state: taskState, start, sendApproval, reset } = useTaskRunner()
  const { history, refetch } = useTaskHistory()
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [replayState, setReplayState] = useState(null) // synthetic state for historical tasks
  const [replan, setReplan] = useState(null)

  // The active displayed state: live task or loaded replay
  const displayState = selectedTaskId && replayState ? replayState : taskState

  const handleSubmitGoal = useCallback(async (goal) => {
    setSelectedTaskId(null)
    setReplayState(null)
    setReplan(null)
    const taskId = await start(goal)
    if (taskId) {
      // After task completes, the history hook polls; also trigger immediately
      // We'll refetch after a short delay to let the DB write complete
      setTimeout(refetch, 2000)
      setSelectedTaskId(taskId)
    }
  }, [start, refetch])

  const handleSelectTask = useCallback(async (taskId) => {
    // If this is the current live task, just select it
    if (taskId === selectedTaskId && !replayState) {
      return
    }

    // Load from replay endpoint
    try {
      const res = await fetch(`${API_URL}/replay/${taskId}`)
      if (!res.ok) return
      const data = await res.json()

      // Build synthetic task state from the replay report
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
      setReplan(null)
    } catch {
      // ignore
    }
  }, [selectedTaskId, replayState])

  const handleNewTask = useCallback(() => {
    setSelectedTaskId(null)
    setReplayState(null)
    setReplan(null)
    reset()
  }, [reset])

  const handleApprove = useCallback(() => sendApproval(true), [sendApproval])
  const handleDeny = useCallback(() => sendApproval(false), [sendApproval])

  return (
    <div className="flex h-full overflow-hidden bg-[#0f0f0f]">
      <Sidebar
        history={history}
        selectedTaskId={selectedTaskId}
        onSelectTask={handleSelectTask}
        onNewTask={handleNewTask}
      />

      <MainPanel
        taskState={displayState}
        replan={replan}
        onSubmitGoal={handleSubmitGoal}
        onApprove={handleApprove}
        onDeny={handleDeny}
      />

      {/* Approval modal — only shown for live tasks */}
      {taskState.pendingApproval && (
        <ApprovalModal
          approval={taskState.pendingApproval}
          onApprove={handleApprove}
          onDeny={handleDeny}
        />
      )}
    </div>
  )
}
