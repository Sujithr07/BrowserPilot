import { useState, useRef } from 'react'

const API_URL = 'http://localhost:8000'

// Parallel branches execute with strided step numbers (branch i -> i*1000 + n)
// and carry a 1-based `branch` tag. Derive a readable label, falling back to
// inferring the branch from the number for older saved reports without the tag.
const BRANCH_STRIDE = 1000
function stepLabel(step) {
  const n = step.step_number
  const branch = step.branch ?? (n >= BRANCH_STRIDE ? Math.floor(n / BRANCH_STRIDE) + 1 : null)
  const local = n >= BRANCH_STRIDE ? n % BRANCH_STRIDE : n
  return { branch, local }
}

function BranchBadge({ n }) {
  if (!n) return null
  return (
    <span
      style={{
        background: '#6366f1', color: '#fff', borderRadius: 4,
        padding: '0 6px', fontSize: '0.72em', fontWeight: 600, marginRight: 6,
      }}
    >
      Branch {n}
    </span>
  )
}

function App() {
  const [view, setView] = useState('run') // 'run' or 'replay'
  const [goal, setGoal] = useState('')
  const [events, setEvents] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [pendingApproval, setPendingApproval] = useState(null)
  const [replayTaskId, setReplayTaskId] = useState('')
  const [replayData, setReplayData] = useState(null)
  const [currentStep, setCurrentStep] = useState(0)
  const wsRef = useRef(null)

  const handleRunTask = async () => {
    if (!goal.trim()) return
    setIsRunning(true)
    setEvents([])

    try {
      const response = await fetch(`${API_URL}/run-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal }),
      })
      const data = await response.json()

      wsRef.current = new WebSocket(`ws://localhost:8000/ws/task/${data.task_id}`)

      wsRef.current.onmessage = (event) => {
        const message = JSON.parse(event.data)
        if (message.event === 'approval_required') {
          setPendingApproval(message.data)
        }
        setEvents((prev) => [...prev, message])
        if (message.event === 'completed' || message.event === 'error') {
          setIsRunning(false)
          wsRef.current.close()
        }
      }

      wsRef.current.onerror = () => {
        setIsRunning(false)
        setEvents((prev) => [...prev, { event: 'error', data: { message: 'WebSocket connection failed' } }])
      }
    } catch (error) {
      setIsRunning(false)
      setEvents((prev) => [...prev, { event: 'error', data: { message: error.message } }])
    }
  }

  const handleLoadReplay = async () => {
    if (!replayTaskId.trim()) return
    try {
      const response = await fetch(`${API_URL}/replay/${replayTaskId}`)
      if (response.status === 404) {
        alert('Task not found')
        return
      }
      const data = await response.json()
      setReplayData(data)
      setCurrentStep(0)
    } catch (error) {
      alert('Failed to load replay')
    }
  }

  const handleApproval = (approved) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'approval_response', approved }))
    }
    setPendingApproval(null)
  }

  const completed = events.find((e) => e.event === 'completed')

  return (
    <div className="container">
      {/* Approval modal */}
      {pendingApproval && (
        <div className="overlay">
          <div className="modal">
            <h2>⚠ Approval required</h2>
            <p>The agent wants to perform a potentially irreversible action:</p>
            <div className="instruction">{pendingApproval.instruction}</div>
            <div className="meta">
              Step {pendingApproval.step_number} · Tool: {pendingApproval.tool}
            </div>
            <div className="modal-actions">
              <button className="btn btn-approve" onClick={() => handleApproval(true)}>Approve</button>
              <button className="btn btn-deny" onClick={() => handleApproval(false)}>Deny</button>
            </div>
          </div>
        </div>
      )}

      <div className="header">
        <h1>AgentFlow — Multi-Agent Web Executor</h1>
      </div>

      <div className="tabs">
        <button className={`tab ${view === 'run' ? 'active' : ''}`} onClick={() => setView('run')}>Run Task</button>
        <button className={`tab ${view === 'replay' ? 'active' : ''}`} onClick={() => setView('replay')}>Replay</button>
      </div>

      {view === 'run' ? (
        <>
          <div className="card">
            <textarea
              className="textarea"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="Describe your goal… e.g. Go to Amazon and Flipkart and compare the price of iPhone 16"
              disabled={isRunning}
            />
            <button
              className="btn btn-primary"
              onClick={handleRunTask}
              disabled={isRunning || !goal.trim()}
            >
              {isRunning ? 'Running…' : 'Run task'}
            </button>
          </div>

          {events.length > 0 && (
            <div className="card">
              <h2>Execution Log</h2>
              <div className="log">
                {events.map((event, idx) => (
                  <LogRow key={idx} event={event} />
                ))}
              </div>

              {completed && (
                <div className="final">
                  <h3>Final Answer</h3>
                  <p>{completed.data?.final_answer}</p>
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="card">
            <input
              className="input"
              type="text"
              value={replayTaskId}
              onChange={(e) => setReplayTaskId(e.target.value)}
              placeholder="Enter task ID…"
            />
            <button className="btn btn-primary" onClick={handleLoadReplay} disabled={!replayTaskId.trim()}>
              Load replay
            </button>
          </div>

          {replayData && (
            <div className="card">
              <h2>Task Replay</h2>
              {currentStep < replayData.step_results.length ? (
                <>
                  <div className="replay-nav">
                    <button
                      className="btn btn-secondary"
                      onClick={() => setCurrentStep((s) => Math.max(0, s - 1))}
                      disabled={currentStep === 0}
                    >
                      Previous
                    </button>
                    <span>Step {currentStep + 1} of {replayData.step_results.length}</span>
                    <button
                      className="btn btn-secondary"
                      onClick={() => setCurrentStep((s) => Math.min(replayData.step_results.length - 1, s + 1))}
                      disabled={currentStep === replayData.step_results.length - 1}
                    >
                      Next
                    </button>
                  </div>

                  <div className="step-box">
                    <div>
                      <BranchBadge n={stepLabel(replayData.step_results[currentStep]).branch} />
                      <b>Step {stepLabel(replayData.step_results[currentStep]).local}</b>{' '}
                      <span className={replayData.step_results[currentStep].success ? 'text-blue' : 'text-red'}>
                        {replayData.step_results[currentStep].success ? 'Success' : 'Failed'}
                      </span>
                    </div>
                    <div className="field">
                      <b>Instruction:</b> {replayData.step_results[currentStep].instruction || 'N/A'}
                    </div>
                    <div className="field">
                      <b>Observation:</b> {replayData.step_results[currentStep].observation}
                    </div>
                    {replayData.step_results[currentStep].extracted_data &&
                      Object.keys(replayData.step_results[currentStep].extracted_data).length > 0 && (
                        <div className="field">
                          <b>Extracted Data:</b>
                          <pre>{JSON.stringify(replayData.step_results[currentStep].extracted_data, null, 2)}</pre>
                        </div>
                      )}
                  </div>
                </>
              ) : (
                <div className="final">
                  <h3>Final Answer</h3>
                  <p>{replayData.final_answer}</p>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function LogRow({ event }) {
  const { event: type, data } = event

  if (type === 'planned' || type === 'replanned') {
    const isReplan = type === 'replanned'
    return (
      <div className="log-row">
        <span className={`dot ${isReplan ? 'dot-blue' : 'dot-yellow'}`}></span>
        <div>
          <div className={isReplan ? 'text-blue' : ''}>
            {isReplan ? 'Re-planning' : 'Plan created'} — {data.estimated_steps} {isReplan ? 'recovery ' : ''}steps
          </div>
          {data.steps?.map((step, i) => (
            <div className="sub" key={i}>
              Step {step.step_number}: {step.tool} {step.target}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (type === 'approval_required') {
    return (
      <div className="log-row">
        <span className="dot dot-amber"></span>
        <div className="text-amber">
          Step {data.step_number}: Approval requested — {data.instruction}
        </div>
      </div>
    )
  }

  if (type === 'step_done') {
    const { branch, local } = stepLabel(data)
    return (
      <div className="log-row">
        <span className={`dot ${data.success ? 'dot-green' : 'dot-red'}`}></span>
        <div>
          <div>
            <BranchBadge n={branch} />
            Step {local}: {data.observation || (data.success ? 'done' : 'no observation')} — {data.success ? 'success' : 'failed'}
          </div>
          {!data.success && data.error && (
            <div className="sub text-red">{data.error}</div>
          )}
        </div>
      </div>
    )
  }

  if (type === 'completed') {
    return (
      <div className="log-row">
        <span className="dot dot-green"></span>
        <div>Task completed</div>
      </div>
    )
  }

  if (type === 'error') {
    return (
      <div className="log-row">
        <span className="dot dot-red"></span>
        <div className="text-red">Error: {data.message}</div>
      </div>
    )
  }

  return null
}

export default App
