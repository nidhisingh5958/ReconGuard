import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { api } from '@/lib/api'
import type { Health, RunSummary } from '@/types'

interface RunContextValue {
  runs: RunSummary[]
  activeRunId: string | null
  activeRun: RunSummary | null
  health: Health | null
  loading: boolean
  running: boolean
  error: string | null
  setActiveRunId: (runId: string) => void
  startRun: (label?: string) => Promise<void>
  reload: () => Promise<void>
}

const RunContext = createContext<RunContextValue | null>(null)

/**
 * Holds the currently selected reconciliation run.
 *
 * Every page reads its data for one run, so the selection lives once here
 * rather than being threaded through each route. Starting a run refreshes the
 * list and selects the new run, which is what makes the whole UI update at
 * once after a run completes.
 */
export function RunProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [runsResponse, healthResponse] = await Promise.all([
        api.runs(50),
        api.health(),
      ])
      setRuns(runsResponse.runs)
      setHealth(healthResponse)
      setError(null)
      setActiveRunId((current) => {
        if (current && runsResponse.runs.some((r) => r.run_id === current)) {
          return current
        }
        return runsResponse.runs[0]?.run_id ?? null
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach the API')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const startRun = useCallback(
    async (label = '') => {
      setRunning(true)
      setError(null)
      try {
        const run = await api.startRun({ label })
        const runsResponse = await api.runs(50)
        setRuns(runsResponse.runs)
        setActiveRunId(run.run_id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Reconciliation run failed')
      } finally {
        setRunning(false)
      }
    },
    [],
  )

  const value = useMemo<RunContextValue>(
    () => ({
      runs,
      activeRunId,
      activeRun: runs.find((r) => r.run_id === activeRunId) ?? null,
      health,
      loading,
      running,
      error,
      setActiveRunId,
      startRun,
      reload,
    }),
    [runs, activeRunId, health, loading, running, error, startRun, reload],
  )

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>
}

export function useRunContext(): RunContextValue {
  const context = useContext(RunContext)
  if (!context) throw new Error('useRunContext must be used inside a RunProvider')
  return context
}
