import { CircleX, Loader2 } from 'lucide-react'
import { useMemo, useState, type FormEvent, type KeyboardEvent } from 'react'

import { AnswerView } from '@/components/ask/AnswerView'
import { CitationList } from '@/components/ask/CitationList'
import { ModeBanner } from '@/components/ask/ModeBanner'
import { VerificationView } from '@/components/ask/VerificationView'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useAsk, type AskState } from '@/hooks/useAsk'
import { QUESTION_MAX_CHARS } from '@/lib/limits'

const STATUS_TEXT: Partial<Record<AskState['status'], string>> = {
  retrieving: 'Searching your items…',
  streaming: 'Writing answer…',
  cancelled: 'Cancelled.',
}

export function AskPanel() {
  const { state, ask, cancel, isActive } = useAsk()
  const [question, setQuestion] = useState('')
  const [activeRef, setActiveRef] = useState<number | null>(null)
  const validRefs = useMemo(() => new Set(state.sources.map((s) => s.ref)), [state.sources])

  const trimmed = question.trim()
  const tooLong = question.length > QUESTION_MAX_CHARS
  const canSubmit = trimmed.length > 0 && !tooLong && !isActive

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!canSubmit) return
    setActiveRef(null)
    void ask(trimmed)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit()
  }

  const done = state.status === 'done'
  const statusText = STATUS_TEXT[state.status]

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-2">
        <Textarea
          placeholder="Ask a question about your saved items…"
          value={question}
          rows={3}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          aria-invalid={tooLong}
        />
        <div className="flex items-center gap-2">
          {isActive ? (
            <Button type="button" variant="outline" onClick={cancel}>
              Cancel
            </Button>
          ) : (
            <Button type="submit" disabled={!canSubmit}>
              Ask
            </Button>
          )}
          <span className="text-xs text-muted-foreground">
            {tooLong
              ? `Questions are limited to ${QUESTION_MAX_CHARS} characters.`
              : 'Ctrl/⌘ + Enter to ask'}
          </span>
        </div>
      </form>

      {statusText && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          {isActive && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {statusText}
        </p>
      )}

      <ModeBanner mode={state.mode} />

      {state.answer && state.mode !== 'none' && (
        <AnswerView
          markdown={state.answer}
          validRefs={validRefs}
          activeRef={activeRef}
          onSelect={setActiveRef}
        />
      )}

      {state.verification && <VerificationView verification={state.verification} />}

      {state.error && (
        <Alert variant="destructive">
          <CircleX aria-hidden />
          <AlertTitle>{state.answer ? 'The answer was interrupted' : "Couldn't answer"}</AlertTitle>
          <AlertDescription>
            <p>{state.error.message}</p>
            {state.error.requestId && (
              <p className="font-mono text-xs">request_id: {state.error.requestId}</p>
            )}
          </AlertDescription>
        </Alert>
      )}

      <CitationList
        heading={done ? 'Cited sources' : 'Sources'}
        citations={done ? state.citations : state.sources}
        activeRef={activeRef}
        onSelect={setActiveRef}
      />

      {done && state.timings && (
        <p className="text-xs text-muted-foreground">
          Answered in {Math.round(state.timings.total)} ms
          {state.requestId && <span className="font-mono"> · request_id {state.requestId}</span>}
        </p>
      )}
    </div>
  )
}
