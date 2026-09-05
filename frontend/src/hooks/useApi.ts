import { useCallback, useEffect, useRef, useState } from 'react'

interface State<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/**
 * Minimal async data hook.
 *
 * Deliberately small: this app reads a handful of endpoints and re-reads them
 * when a run completes. A cache layer would add more behaviour to reason about
 * than it would save.
 *
 * `deps` controls refetching. The request is versioned so a slow response from
 * a superseded query can never overwrite a newer one.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: { enabled?: boolean } = {},
): State<T> & { refetch: () => void } {
  const enabled = options.enabled ?? true
  const [state, setState] = useState<State<T>>({
    data: null,
    error: null,
    loading: enabled,
  })
  const [nonce, setNonce] = useState(0)
  const version = useRef(0)

  const refetch = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: null, loading: false })
      return
    }
    const current = ++version.current
    let cancelled = false
    setState((prev) => ({ ...prev, loading: true, error: null }))

    fetcher()
      .then((data) => {
        if (cancelled || current !== version.current) return
        setState({ data, error: null, loading: false })
      })
      .catch((error: unknown) => {
        if (cancelled || current !== version.current) return
        setState({
          data: null,
          error: error instanceof Error ? error.message : 'Request failed',
          loading: false,
        })
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled])

  return { ...state, refetch }
}
