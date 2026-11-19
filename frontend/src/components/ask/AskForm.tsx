import { ArrowUp } from 'lucide-react'
import type { FormEvent, KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { QUESTION_MAX_CHARS } from '@/lib/limits'
import { cn } from '@/lib/utils'

interface AskFormProps {
  question: string
  onQuestionChange: (question: string) => void
  busy: boolean
  onAsk: (question: string) => void
  onCancel: () => void
}

/** A wide pill input with the Ask / Cancel button inside it on the right. */
export function AskForm({ question, onQuestionChange, busy, onAsk, onCancel }: AskFormProps) {
  const trimmed = question.trim()
  const tooLong = question.length > QUESTION_MAX_CHARS
  const canSubmit = trimmed.length > 0 && !tooLong && !busy

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (canSubmit) onAsk(trimmed)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={submit} className="relative shrink-0 space-y-1.5">
      <label htmlFor="question" className="sr-only">
        Question
      </label>
      <div className="relative">
        <Input
          id="question"
          placeholder="Ask anything about your saved items…"
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          onKeyDown={onKeyDown}
          aria-invalid={tooLong}
          aria-describedby="question-hint"
          className="h-12 pr-28 pl-5 shadow-frost"
        />
        <div className="absolute top-1/2 right-1.5 -translate-y-1/2">
          {busy ? (
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          ) : (
            <Button type="submit" disabled={!canSubmit}>
              Ask <ArrowUp aria-hidden />
            </Button>
          )}
        </div>
      </div>
      <p
        id="question-hint"
        className={cn('px-5 text-xs', tooLong ? 'text-destructive' : 'text-muted-foreground')}
      >
        {tooLong ? `Questions are limited to ${QUESTION_MAX_CHARS} characters.` : 'Enter to ask'}
      </p>
    </form>
  )
}
