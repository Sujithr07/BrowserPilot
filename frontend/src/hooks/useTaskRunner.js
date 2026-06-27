import { useReducer, useRef, useCallback } from 'react'

const API_URL = 'http://localhost:8000'

const initialState = {
  status: 'idle', // idle | connecting | planning | running | completed | failed | stopped
  plan: null,
  steps: [],
  latestScreenshot: null,
  pendingApproval: null,
  metrics: null,
  finalAnswer: null,
  error: null,
}

function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return initialState
    case 'CONNECTING':
      return { ...initialState, status: 'connecting' }
    case 'PLANNED':
      return { ...state, status: 'running', plan: action.data }
    case 'REPLANNED':
      return { ...state, plan: action.data }
    case 'STEP_DONE': {
      const screenshot = action.data.screenshot_path
        ? `${API_URL}/${action.data.screenshot_path}`
        : state.latestScreenshot
      return {
        ...state,
        steps: [...state.steps, action.data],
        latestScreenshot: screenshot,
      }
    }
    case 'APPROVAL_REQUIRED':
      return { ...state, pendingApproval: action.data }
    case 'APPROVAL_CLEARED':
      return { ...state, pendingApproval: null }
    case 'STOPPED':
      // Interrupt the run but keep steps/screenshots/plan visible.
      return { ...state, status: 'stopped', pendingApproval: null }
    case 'METRICS':
      return { ...state, metrics: action.data }
    case 'COMPLETED':
      return {
        ...state,
        status: 'completed',
        finalAnswer: action.data.final_answer,
        metrics: action.data.metrics ?? state.metrics,
        pendingApproval: null,
      }
    case 'ERROR':
      return { ...state, status: 'failed', error: action.data.message, pendingApproval: null }
    default:
      return state
  }
}

export function useTaskRunner() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const wsRef = useRef(null)

  const start = useCallback(async (goal) => {
    // Close any existing socket
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    dispatch({ type: 'CONNECTING' })

    let taskId
    try {
      const res = await fetch(`${API_URL}/run-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal }),
      })
      const data = await res.json()
      taskId = data.task_id
    } catch (err) {
      dispatch({ type: 'ERROR', data: { message: err.message } })
      return null
    }

    const ws = new WebSocket(`ws://localhost:8000/ws/task/${taskId}`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      switch (msg.event) {
        case 'planned':
          dispatch({ type: 'PLANNED', data: msg.data })
          break
        case 'replanned':
          dispatch({ type: 'REPLANNED', data: msg.data })
          break
        case 'step_done':
          dispatch({ type: 'STEP_DONE', data: msg.data })
          break
        case 'approval_required':
          dispatch({ type: 'APPROVAL_REQUIRED', data: msg.data })
          break
        case 'metrics':
          dispatch({ type: 'METRICS', data: msg.data })
          break
        case 'completed':
          dispatch({ type: 'COMPLETED', data: msg.data })
          ws.close()
          break
        case 'error':
          dispatch({ type: 'ERROR', data: msg.data })
          ws.close()
          break
        default:
          break
      }
    }

    ws.onerror = () => {
      dispatch({ type: 'ERROR', data: { message: 'WebSocket connection failed' } })
    }

    return taskId
  }, [])

  const sendApproval = useCallback((approved) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'approval_response', approved }))
    }
    dispatch({ type: 'APPROVAL_CLEARED' })
  }, [])

  const stop = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    dispatch({ type: 'STOPPED' })
  }, [])

  const reset = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    dispatch({ type: 'RESET' })
  }, [])

  return { state, start, sendApproval, stop, reset }
}
