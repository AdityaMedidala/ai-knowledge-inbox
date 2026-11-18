import type { components } from '@/lib/api-types'

type Schemas = components['schemas']
export type ItemSummary = Schemas['ItemSummary']
export type ItemList = Schemas['ItemList']
export type IngestRequest = Schemas['NoteIngest'] | Schemas['UrlIngest']
export type IngestResponse = Schemas['IngestResponse']
export type Citation = Schemas['Citation']
export type QueryTimings = Schemas['QueryTimings']
export type RetrievalMode = Schemas['QueryResponse']['mode']
type ErrorEnvelope = Schemas['ErrorEnvelope']

/** Vite proxies /api to the backend (stripping the prefix). */
const API_BASE = '/api'
const REQUEST_ID_HEADER = 'X-Request-ID'

/** Client-side code, in addition to the server's ErrorCode values. */
export const NETWORK_ERROR = 'NETWORK_ERROR'

interface ApiErrorInit {
  status: number
  code: string
  message: string
  details: Record<string, unknown> | null
  requestId: string | null
}

/** Any non-2xx response or failed request. `status` 0 means the server was never reached. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown> | null
  readonly requestId: string | null

  constructor(init: ApiErrorInit) {
    super(init.message)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.details = init.details
    this.requestId = init.requestId
  }

  get isNetworkError(): boolean {
    return this.code === NETWORK_ERROR
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/**
 * fetch with a client-generated X-Request-ID (the backend adopts it), so even a request that
 * never reached the server has an id to quote. Non-2xx responses throw ApiError.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const requestId = crypto.randomUUID()
  const headers = new Headers(init.headers)
  headers.set(REQUEST_ID_HEADER, requestId)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  } catch (error) {
    if (isAbortError(error)) throw error
    throw unreachable(requestId)
  }
  if (!response.ok) throw await toApiError(response, requestId)
  return response
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, init)
  return (await response.json()) as T
}

function unreachable(requestId: string | null): ApiError {
  return new ApiError({
    status: 0,
    code: NETWORK_ERROR,
    message: "Can't reach the server. Is the backend running?",
    details: null,
    requestId,
  })
}

async function toApiError(response: Response, requestId: string): Promise<ApiError> {
  const headerId = response.headers.get(REQUEST_ID_HEADER) ?? requestId
  try {
    const body = (await response.json()) as Partial<ErrorEnvelope>
    if (body.error) {
      return new ApiError({
        status: response.status,
        code: body.error.code,
        message: body.error.message,
        details: body.error.details ?? null,
        requestId: body.request_id ?? headerId,
      })
    }
  } catch {
    // Not our JSON envelope: the dev proxy answers this way when the backend is down.
  }
  return unreachable(headerId)
}

export const api = {
  listItems: (cursor: string | null) =>
    requestJson<ItemList>(
      `/items?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
    ),
  ingest: (body: IngestRequest) =>
    requestJson<IngestResponse>('/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteItem: async (id: string) => {
    await apiFetch(`/items/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
}
