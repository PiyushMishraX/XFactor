/**
 * Thin wrapper around the X FACTOR backend API.
 *
 * The base URL is configurable through `VITE_API_BASE_URL` and defaults to
 * `/api`, which the Vite dev server proxies to the FastAPI backend
 * (see vite.config.js).
 *
 * Approval calls require an approver bearer token. The token is supplied by the
 * user at runtime and is only ever sent in the `Authorization` header; no
 * credential is stored in the bundle.
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
  const { headers, ...rest } = options
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
  })

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // The backend did not return JSON; keep the status message.
    }
    throw new Error(detail)
  }

  return response.json()
}

/** Fetch backend health and dependency status. */
export function getHealth() {
  return request('/health')
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` }
}

/** List proposals waiting for an authenticated approver's decision. */
export function getPendingApprovals(token) {
  return request('/approvals/pending', { headers: authHeaders(token) })
}

/** Read one approval item, including its decision history. */
export function getApproval(threadId, token) {
  return request(`/approvals/${encodeURIComponent(threadId)}`, {
    headers: authHeaders(token),
  })
}

/** Submit an approve / reject / request-modifications decision. */
export function decideApproval(threadId, decision, token) {
  return request(`/approvals/${encodeURIComponent(threadId)}/decision`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(decision),
  })
}

/** Read the execution report produced after an approval. */
export function getApprovalExecution(threadId, token) {
  return request(`/approvals/${encodeURIComponent(threadId)}/execution`, {
    headers: authHeaders(token),
  })
}

/** Start a supervisor workflow. Used by the demo controls. */
export function startWorkflow(requestBody) {
  return request('/orchestration/workflows', {
    method: 'POST',
    body: JSON.stringify(requestBody),
  })
}
