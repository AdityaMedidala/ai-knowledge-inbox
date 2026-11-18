import { apiFetch } from '@/lib/api'

export interface SseMessage {
  event: string
  data: string
}

interface StreamOptions {
  signal: AbortSignal
  onMessage: (message: SseMessage) => void
}

/**
 * POST a JSON body and parse the text/event-stream response (EventSource can't POST).
 * Resolves when the server closes the stream; non-2xx responses throw ApiError.
 */
export async function streamSse(
  path: string,
  body: unknown,
  { signal, onMessage }: StreamOptions,
): Promise<void> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.body) return
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value.replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const message = parseBlock(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      if (message) onMessage(message)
      boundary = buffer.indexOf('\n\n')
    }
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  return data.length > 0 ? { event, data: data.join('\n') } : null
}
