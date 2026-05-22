import { useState, useEffect, useRef } from 'react'

const API_URL = 'http://localhost:8000'

function App() {
  const [view, setView] = useState('run') // 'run' or 'replay'
  const [goal, setGoal] = useState('')
  const [taskId, setTaskId] = useState('')
  const [events, setEvents] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [replayTaskId, setReplayTaskId] = useState('')
  const [replayData, setReplayData] = useState(null)
  const [currentStep, setCurrentStep] = useState(0)
  const wsRef = useRef(null)

  // Run Task
  const handleRunTask = async () => {
    if (!goal.trim()) return
    
    setIsRunning(true)
    setEvents([])
    
    try {
      const response = await fetch(`${API_URL}/run-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal })
      })
      const data = await response.json()
      setTaskId(data.task_id)
      
      // Connect WebSocket
      wsRef.current = new WebSocket(`ws://localhost:8000/ws/task/${data.task_id}`)
      
      wsRef.current.onmessage = (event) => {
        const message = JSON.parse(event.data)
        setEvents(prev => [...prev, message])
        
        if (message.event === 'completed' || message.event === 'error') {
          setIsRunning(false)
          wsRef.current.close()
        }
      }
      
      wsRef.current.onerror = () => {
        setIsRunning(false)
        setEvents(prev => [...prev, { event: 'error', data: { message: 'WebSocket connection failed' } }])
      }
      
    } catch (error) {
      setIsRunning(false)
      setEvents(prev => [...prev, { event: 'error', data: { message: error.message } }])
    }
  }

  // Replay
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

  const nextStep = () => {
    if (replayData && currentStep < replayData.step_results.length - 1) {
      setCurrentStep(prev => prev + 1)
    }
  }

  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(prev => prev - 1)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-4xl mx-auto px-4 py-4">
          <h1 className="text-xl font-semibold text-gray-800">AgentFlow — Multi-Agent Web Executor</h1>
        </div>
      </header>

      {/* Navigation */}
      <nav className="max-w-4xl mx-auto px-4 py-4">
        <div className="flex gap-2">
          <button
            onClick={() => setView('run')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              view === 'run' 
                ? 'bg-blue-600 text-white' 
                : 'bg-white text-gray-700 hover:bg-gray-100'
            }`}
          >
            Run Task
          </button>
          <button
            onClick={() => setView('replay')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              view === 'replay' 
                ? 'bg-blue-600 text-white' 
                : 'bg-white text-gray-700 hover:bg-gray-100'
            }`}
          >
            Replay
          </button>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 py-6">
        {view === 'run' ? (
          <div className="space-y-6">
            {/* Input */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="Describe your goal... e.g. Find the top 5 AI tools launched this month and compare their prices"
                className="w-full h-32 p-3 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={isRunning}
              />
              <button
                onClick={handleRunTask}
                disabled={isRunning || !goal.trim()}
                className={`mt-4 px-6 py-2 rounded-lg font-medium transition-colors ${
                  isRunning || !goal.trim()
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
              >
                {isRunning ? 'Running...' : 'Run task'}
              </button>
            </div>

            {/* Live Step Log */}
            {events.length > 0 && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-800 mb-4">Execution Log</h2>
                <div className="space-y-2 font-mono text-sm">
                  {events.map((event, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      {event.event === 'planned' && (
                        <>
                          <span className="w-2 h-2 rounded-full bg-yellow-500 mt-1.5 flex-shrink-0"></span>
                          <div>
                            <div className="text-gray-800">Plan created — {event.data.estimated_steps} steps</div>
                            {event.data.steps?.map((step, sIdx) => (
                              <div key={sIdx} className="text-gray-600 ml-4 mt-1">
                                Step {step.step_number}: {step.tool} {step.target}
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                      {event.event === 'step_done' && (
                        <>
                          <span className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${event.data.success ? 'bg-green-500' : 'bg-red-500'}`}></span>
                          <div className="text-gray-800">
                            Step {event.data.step_number}: {event.data.observation} — {event.data.success ? 'success' : 'failed'}
                          </div>
                        </>
                      )}
                      {event.event === 'completed' && (
                        <>
                          <span className="w-2 h-2 rounded-full bg-green-500 mt-1.5 flex-shrink-0"></span>
                          <div className="text-gray-800">Task completed</div>
                        </>
                      )}
                      {event.event === 'error' && (
                        <>
                          <span className="w-2 h-2 rounded-full bg-red-500 mt-1.5 flex-shrink-0"></span>
                          <div className="text-red-600">Error: {event.data.message}</div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
                
                {/* Final Answer */}
                {events.find(e => e.event === 'completed') && (
                  <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
                    <h3 className="font-semibold text-green-800 mb-2">Final Answer</h3>
                    <p className="text-green-700 whitespace-pre-wrap">
                      {events.find(e => e.event === 'completed')?.data?.final_answer}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {/* Replay Input */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <input
                type="text"
                value={replayTaskId}
                onChange={(e) => setReplayTaskId(e.target.value)}
                placeholder="Enter task ID..."
                className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <button
                onClick={handleLoadReplay}
                disabled={!replayTaskId.trim()}
                className={`mt-4 px-6 py-2 rounded-lg font-medium transition-colors ${
                  !replayTaskId.trim()
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
              >
                Load replay
              </button>
            </div>

            {/* Replay Slideshow */}
            {replayData && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-800 mb-4">Task Replay</h2>
                
                {currentStep < replayData.step_results.length ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <button
                        onClick={prevStep}
                        disabled={currentStep === 0}
                        className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Previous
                      </button>
                      <span className="text-gray-600">
                        Step {currentStep + 1} of {replayData.step_results.length}
                      </span>
                      <button
                        onClick={nextStep}
                        disabled={currentStep === replayData.step_results.length - 1}
                        className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Next
                      </button>
                    </div>

                    <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${replayData.step_results[currentStep].success ? 'bg-green-500' : 'bg-red-500'}`}></span>
                          <span className="font-medium text-gray-800">
                            Step {replayData.step_results[currentStep].step_number}
                          </span>
                          <span className={`text-sm ${replayData.step_results[currentStep].success ? 'text-green-600' : 'text-red-600'}`}>
                            {replayData.step_results[currentStep].success ? 'Success' : 'Failed'}
                          </span>
                        </div>
                        <div className="text-gray-700">
                          <span className="font-medium">Instruction:</span> {replayData.step_results[currentStep].instruction || 'N/A'}
                        </div>
                        <div className="text-gray-700">
                          <span className="font-medium">Observation:</span> {replayData.step_results[currentStep].observation}
                        </div>
                        {replayData.step_results[currentStep].extracted_data && Object.keys(replayData.step_results[currentStep].extracted_data).length > 0 && (
                          <div className="text-gray-700">
                            <span className="font-medium">Extracted Data:</span>
                            <pre className="mt-1 text-xs bg-gray-100 p-2 rounded overflow-auto">
                              {JSON.stringify(replayData.step_results[currentStep].extracted_data, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
                    <h3 className="font-semibold text-green-800 mb-2">Final Answer</h3>
                    <p className="text-green-700 whitespace-pre-wrap">{replayData.final_answer}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

export default App
