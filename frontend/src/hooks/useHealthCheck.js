import { useCallback, useEffect, useState } from 'react'

import { getHealth } from '../services/api'

/**
 * Poll-free hook that reports backend connectivity for the overview page.
 *
 * @returns {{status: 'loading'|'success'|'error', data: object|null,
 *            error: string|null, refresh: () => void}}
 */
export function useHealthCheck() {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })

  const refresh = useCallback(async () => {
    setState({ status: 'loading', data: null, error: null })
    try {
      const data = await getHealth()
      setState({ status: 'success', data, error: null })
    } catch (error) {
      setState({ status: 'error', data: null, error: error.message })
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { ...state, refresh }
}
