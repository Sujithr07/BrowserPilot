import { useReducer, useRef, useCallback } from 'react'

const API_URL = 'http://localhost:8000'

// Persisted handle to an in-flight task so a page refresh can reconnect to it.
const ACTIVE_TASK_KEY = 'agentflow:activeTask'
// Replay-polling fallback used while reconnecting (see resume()).
const RESUME_POLL_MS = 4000
const RESUME_POLL_MAX = 8 // ~32s of total socket silence before we give up

export function readActiveTask() {
  try {
    return JSON.parse(localStorage.getItem(ACTIVE_TASK_KEY) || 'null')
  } catch {
    return null
  }
}

function persistActiveTask(taskId, goal) {
  try {
    localStorage.setItem(ACTIVE_TASK_KEY, JSON.stringify({ taskId, goal }))
  } catch {
    /* localStorage unavailable (private mode) — reconnect just won't persist */
  }
}

function clearActiveTask() {
  try {
    localStorage.removeItem(ACTIVE_TASK_KEY)
  } catch {
    /* ignore */
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Pull the last screenshot out of a step list and make it an absolute URL.
function lastScreenshot(steps) {
  const s = [...steps].reverse().find((x) => x.screenshot_path)
  return s ? `${API_URL}/${s.screenshot_path}` : null
}

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
    case 'RESUMING':
      // Reconnecting to a task that was already running before a refresh.
      return { ...initialState, status: 'connecting' }
    case 'RESTORE': {
      // Rebuild state from a saved report (task finished while we were away).
      const d = action.data
      const steps = d.step_results ?? []
      return {
        ...initialState,
        status: d.status ?? 'completed',
        plan: d.plan ?? null,
        steps,
        latestScreenshot: lastScreenshot(steps),
        metrics: d.metrics ?? null,
        finalAnswer: d.final_answer ?? null,
        error: d.status === 'failed' ? (d.final_answer || 'Task failed') : null,
      }
    }
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
    case 'STOPPED': {
      // Interrupt the run but keep steps/screenshots/plan visible. When the
      // backend confirms with a final report, fold in its answer/metrics — and
      // backfill any steps we missed if this arrived over a reconnected socket.
      const d = action.data
      const reportSteps = d?.step_results ?? []
      const useReport = reportSteps.length > state.steps.length
      return {
        ...state,
        status: 'stopped',
        plan: state.plan ?? d?.plan ?? null,
        steps: useReport ? reportSteps : state.steps,
        latestScreenshot: useReport ? lastScreenshot(reportSteps) : state.latestScreenshot,
        pendingApproval: null,
        finalAnswer: d?.final_answer ?? state.finalAnswer,
        metrics: d?.metrics ?? state.metrics,
      }
    }
    case 'METRICS':
      return { ...state, metrics: action.data }
    case 'COMPLETED': {
      const d = action.data
      // Backfill the full step history from the report when our live log is
      // short (e.g. we reconnected mid-run and missed the earlier steps).
      const reportSteps = d.step_results ?? []
      const useReport = reportSteps.length > state.steps.length
      return {
        ...state,
        status: 'completed',
        plan: state.plan ?? d.plan ?? null,
        steps: useReport ? reportSteps : state.steps,
        latestScreenshot: useReport ? lastScreenshot(reportSteps) : state.latestScreenshot,
        finalAnswer: d.final_answer,
        metrics: d.metrics ?? state.metrics,
        pendingApproval: null,
      }
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
  // Tracks whether the current socket has delivered anything yet — resume()
  // uses it to tell a live (but quiet) task from one whose backend is gone.
  const gotMessageRef = useRef(false)

  const closeSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  // Open a socket for a task and stream its events into the reducer. Shared by
  // start() (fresh task) and resume() (reconnect after a refresh).
  const attachSocket = useCallback((taskId) => {
    const ws = new WebSocket(`ws://localhost:8000/ws/task/${taskId}`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      gotMessageRef.current = true
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
          clearActiveTask()
          ws.close()
          break
        case 'stopped':
          dispatch({ type: 'STOPPED', data: msg.data })
          clearActiveTask()
          ws.close()
          break
        case 'error':
          dispatch({ type: 'ERROR', data: msg.data })
          clearActiveTask()
          ws.close()
          break
        default:
          break
      }
    }

    ws.onerror = () => {
      dispatch({ type: 'ERROR', data: { message: 'WebSocket connection failed' } })
    }

    return ws
  }, [])

  const start = useCallback(async (goal) => {
    closeSocket()
    gotMessageRef.current = false
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

    // Remember the task so a refresh can reconnect to it; cleared on terminal.
    persistActiveTask(taskId, goal)
    attachSocket(taskId)
    return taskId
  }, [attachSocket, closeSocket])

  // Reconnect to a task that was already running before a page refresh.
  // Resolves to the task id when reconnected/restored, or null if the task
  // turned out to be gone (so the caller can drop its selection).
  const resume = useCallback(async (taskId) => {
    closeSocket()
    gotMessageRef.current = false
    dispatch({ type: 'RESUMING' })

    // Attach the live socket up front so we don't miss the tail of the run. Its
    // final report backfills any steps that streamed while we were away.
    attachSocket(taskId)

    // Fallback: poll the saved report. This restores a task that finished while
    // we were away (its terminal event is long gone) and, after a stretch of
    // total socket silence, self-clears a task whose backend no longer exists.
    for (let i = 0; i < RESUME_POLL_MAX; i++) {
      // Live events are flowing — the socket carries the rest. Stop polling.
      if (gotMessageRef.current) return taskId
      try {
        const res = await fetch(`${API_URL}/replay/${taskId}`)
        if (res.ok) {
          const data = await res.json()
          // A real report is an object with a status; a missing task serializes
          // as an array ([{error}, 404]) — ignore that and keep waiting.
          if (data && !Array.isArray(data) && data.status && data.task_id) {
            closeSocket()
            dispatch({ type: 'RESTORE', data })
            clearActiveTask()
            return taskId
          }
        }
      } catch {
        /* network blip — keep trying */
      }
      await sleep(RESUME_POLL_MS)
    }

    // Never heard from the socket and no saved report exists: the task is gone.
    if (!gotMessageRef.current) {
      closeSocket()
      clearActiveTask()
      dispatch({ type: 'RESET' })
      return null
    }
    return taskId
  }, [attachSocket, closeSocket])

  const sendApproval = useCallback((approved) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'approval_response', approved }))
    }
    dispatch({ type: 'APPROVAL_CLEARED' })
  }, [])

  const stop = useCallback(() => {
    // Ask the backend to cancel; keep the socket open so it can finish the
    // current step and send back the final 'stopped' report (which closes it).
    // Optimistically flip the UI to 'stopped' right away.
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }))
    }
    clearActiveTask()
    dispatch({ type: 'STOPPED' })
  }, [])

  const reset = useCallback(() => {
    closeSocket()
    clearActiveTask()
    dispatch({ type: 'RESET' })
  }, [closeSocket])

  return { state, start, resume, sendApproval, stop, reset }
}
