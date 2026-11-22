/**
 * Thin wrapper around the X FACTOR backend API.
 *
 * The base URL is configurable through `VITE_API_BASE_URL` and defaults to
 * `/api`, which the Vite dev server proxies to the FastAPI backend
 * (see vite.config.js).
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

/**
 * Perform a JSON request against the backend.
 *
 * @param {string} path Path relative to the API base URL, e.g. `/health`.
 * @param {RequestInit} [options] Optional fetch overrides.
 * @returns {Promise<unknown>} Parsed JSON response.
 */
async function request(path, options = {}) {
  const url = `${API_BASE_URL}${path}`
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    ...options,
  })

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status} (${url})`)
  }

  return response.json()
}

/** Fetch backend health and dependency status. */
export function getHealth() {
  return request('/health')
}
