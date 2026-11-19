import { CircleX, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { AnswerView } from '@/components/ask/AnswerView'
import { AskForm } from '@/components/ask/AskForm'
import { CitationList } from '@/components/ask/CitationList'
import { ExampleQuestions } from '@/components/ask/ExampleQuestions'
import { ModeBanner } from '@/components/ask/ModeBanner'
import { VerificationSummary } from '@/components/ask/VerificationSummary'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { useAsk, type AskState } from '@/hooks/useAsk'

const STATUS_TEXT: Partial<Record<AskState['status'], string>> = {
  retrieving: 'Searching your items…',
  streaming: 'Writing the answer…',
  cancelled: 'Cancelled. Anything already written is kept below.',
}

export function AskPanel() {
  const { state, ask, cancel, isActive } = useAsk()
  const [question, setQuestion] = useState('')
  const [activeRef, setActiveRef] = useState<number | null>(null)
  const validRefs = useMemo(() => new Set(state.sources.map((s) => s.ref)), [state.sources])

  const done = state.status === 'done'
  const statusText = STATUS_TEXT[state.status]
  const showAnswer = state.answer !== '' && state.mode !== 'none'

  function onAsk(next: string) {
    setActiveRef(null)
    void ask(next)
  }

  function onPickExample(example: string) {
    setQuestion(example)
    onAsk(example)
  }

  return (
    <div className="relative flex flex-col gap-4 lg:min-h-0 lg:flex-1">
      <AskForm
        question={question}
        onQuestionChange={setQuestion}
        busy={isActive}
        onAsk={onAsk}
        onCancel={cancel}
      />

      {/* Scrolls inside the pane on desktop; focusable so keyboard users can scroll it too.
          The padding keeps focus outlines from being clipped. */}
      <div
        tabIndex={0}
        aria-label="Answer and sources"
        className="-mx-1 space-y-4 px-1 py-1 lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
      >
        {/* Always mounted, so screen readers announce each status change. */}
        <p className="flex items-center gap-2 text-sm text-muted-foreground empty:hidden" role="status">
          {isActive && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {statusText}
        </p>

        {state.status === 'idle' && (
          <div className="space-y-3">
            <ExampleQuestions onPick={onPickExample} />
            <p className="text-sm text-muted-foreground">
              Answers come only from your saved items. Each claim links to its source, and when
              verification is on, each sentence shows whether its sources support it.
            </p>
          </div>
        )}

        <ModeBanner mode={state.mode} />

        {state.verification && <VerificationSummary verification={state.verification} />}

        <div aria-live="polite" aria-busy={state.status === 'streaming'} aria-label="Answer">
          {showAnswer && (
            <AnswerView
              markdown={state.answer}
              validRefs={validRefs}
              verdicts={state.verification?.sentences ?? null}
              activeRef={activeRef}
              onSelect={setActiveRef}
            />
          )}
        </div>

        {state.error && (
          <Alert variant="destructive" className="border-unsupported/30 bg-unsupported-soft">
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
        />

        {done && state.timings && (
          <p className="text-xs text-muted-foreground">
            Answered in {Math.round(state.timings.total)} ms
            {state.requestId && <span className="font-mono"> · request_id {state.requestId}</span>}
          </p>
        )}
      </div>
    </div>
  )
}
