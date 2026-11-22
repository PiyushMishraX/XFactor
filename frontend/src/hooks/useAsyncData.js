import { useCallback, useEffect, useState } from 'react'

/**
 * Load an API payload with explicit loading, error and refresh states.
 *
 * @param {() => Promise<unknown>} loader
 * @param {unknown[]} deps
 * @param {{enabled?: boolean}} [options]
 */
export function useAsyncData(loader, deps = [], options = {}) {
  const { enabled = true } = options
  const [state, setState] = useState({ status: 'loading', data: null, error: '' })

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const refresh = useCallback(async () => {
    if (!enabled) {
      setState({ status: 'idle', data: null, error: '' })
      return
    }
    setState((current) => ({ ...current, status: 'loading', error: '' }))
    try {
      const data = await loader()
      setState({ status: 'success', data, error: '' })
    } catch (error) {
      setState({ status: 'error', data: null, error: error.message })
    }
  }, deps)

  useEffect(() => {
    refresh()
  }, [refresh])

  return { ...state, refresh }
}
