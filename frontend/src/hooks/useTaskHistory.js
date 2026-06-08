import { useState, useEffect, useCallback } from 'react'

const API_URL = 'http://localhost:8000'

export function useTaskHistory() {
  const [history, setHistory] = useState([])

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/tasks`)
      if (res.ok) setHistory(await res.json())
    } catch {
      // silently ignore — backend may not be up yet
    }
  }, [])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // Refresh every 30s to catch tasks from other sessions
  useEffect(() => {
    const id = setInterval(fetchHistory, 30_000)
    return () => clearInterval(id)
  }, [fetchHistory])

  return { history, refetch: fetchHistory }
}
