import { useCallback, useEffect, useReducer, useRef } from 'react'

import {
  ApiError,
  isAbortError,
  type Citation,
  type QueryTimings,
  type RetrievalMode,
} from '@/lib/api'
import { notifyIfServerError } from '@/lib/notify'
import { streamSse, type SseMessage } from '@/lib/sse'

export type AskStatus = 'idle' | 'retrieving' | 'streaming' | 'done' | 'error' | 'cancelled'

export interface AskError {
  code: string
  message: string
  requestId: string | null
}

export interface AskState {
  status: AskStatus
  requestId: string | null
  mode: RetrievalMode | null
  sources: Citation[] // every numbered source; [n] markers resolve against these
  answer: string
  citations: Citation[] // only the cited ones, known once `done` arrives
  timings: QueryTimings | null
  error: AskError | null
}

type Action =
  | { type: 'start' }
  | { type: 'meta'; requestId: string }
  | { type: 'sources'; mode: RetrievalMode; sources: Citation[] }
  | { type: 'token'; text: string }
  | { type: 'done'; citations: Citation[]; timings: QueryTimings }
  | { type: 'fail'; error: AskError }
  | { type: 'cancel' }

const INITIAL: AskState = {
  status: 'idle',
  requestId: null,
  mode: null,
  sources: [],
  answer: '',
  citations: [],
  timings: null,
  error: null,
}

const isActive = (status: AskStatus) => status === 'retrieving' || status === 'streaming'

function reducer(state: AskState, action: Action): AskState {
  switch (action.type) {
    case 'start':
      return { ...INITIAL, status: 'retrieving' }
    case 'meta':
      return { ...state, requestId: action.requestId }
    case 'sources':
      return { ...state, status: 'streaming', mode: action.mode, sources: action.sources }
    case 'token':
      return { ...state, answer: state.answer + action.text }
    case 'done':
      return { ...state, status: 'done', citations: action.citations, timings: action.timings }
    case 'fail':
      return { ...state, status: 'error', error: action.error }
    case 'cancel':
      return isActive(state.status) ? { ...state, status: 'cancelled' } : state
  }
}

/** Server events of POST /query/stream, in order: meta → sources → token… → done | error. */
function toAction(message: SseMessage, requestId: string | null): Action | null {
  const data = JSON.parse(message.data)
  switch (message.event) {
    case 'meta':
      return { type: 'meta', requestId: data.request_id }
    case 'sources':
      return { type: 'sources', mode: data.mode, sources: data.sources }
    case 'token':
      return { type: 'token', text: data.text }
    case 'done':
      return { type: 'done', citations: data.citations, timings: data.timings_ms }
    case 'error':
      return { type: 'fail', error: { code: data.code, message: data.message, requestId } }
    default:
      return null
  }
}

const STREAM_ENDED: Omit<AskError, 'requestId'> = {
  code: 'STREAM_ENDED',
  message: 'The answer stream ended unexpectedly.',
}

export function useAsk() {
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const controllerRef = useRef<AbortController | null>(null)

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    dispatch({ type: 'cancel' })
  }, [])

  const ask = useCallback(async (question: string) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    dispatch({ type: 'start' })
    let requestId: string | null = null
    let finished = false
    try {
      await streamSse('/query/stream', { question }, {
        signal: controller.signal,
        onMessage: (message) => {
          const action = toAction(message, requestId)
          if (!action) return
          if (action.type === 'meta') requestId = action.requestId
          if (action.type === 'done' || action.type === 'fail') finished = true
          dispatch(action)
        },
      })
      if (!finished) dispatch({ type: 'fail', error: { ...STREAM_ENDED, requestId } })
    } catch (error) {
      if (isAbortError(error)) return
      notifyIfServerError(error)
      const failure =
        error instanceof ApiError
          ? { code: error.code, message: error.message, requestId: error.requestId ?? requestId }
          : { ...STREAM_ENDED, requestId }
      dispatch({ type: 'fail', error: failure })
    }
  }, [])

  useEffect(() => () => controllerRef.current?.abort(), [])

  return { state, ask, cancel, isActive: isActive(state.status) }
}
