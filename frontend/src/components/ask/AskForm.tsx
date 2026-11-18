import { useState, type FormEvent, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { QUESTION_MAX_CHARS } from '@/lib/limits'

interface AskFormProps {
  busy: boolean
  onAsk: (question: string) => void
  onCancel: () => void
}

export function AskForm({ busy, onAsk, onCancel }: AskFormProps) {
  const [question, setQuestion] = useState('')
  const trimmed = question.trim()
  const tooLong = question.length > QUESTION_MAX_CHARS
  const canSubmit = trimmed.length > 0 && !tooLong && !busy

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (canSubmit) onAsk(trimmed)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit()
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <label htmlFor="question" className="sr-only">
        Question
      </label>
      <Textarea
        id="question"
        placeholder="Ask a question about your saved items…"
        value={question}
        rows={3}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={onKeyDown}
        aria-invalid={tooLong}
        aria-describedby="question-hint"
      />
      <div className="flex items-center gap-3">
        {busy ? (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        ) : (
          <Button type="submit" disabled={!canSubmit}>
            Ask
          </Button>
        )}
        <span
          id="question-hint"
          className={tooLong ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}
        >
          {tooLong
            ? `Questions are limited to ${QUESTION_MAX_CHARS} characters.`
            : 'Ctrl/⌘ + Enter to ask'}
        </span>
      </div>
    </form>
  )
}
