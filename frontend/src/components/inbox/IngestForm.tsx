import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { FieldError } from '@/components/inbox/FieldError'
import { duplicateItemId, useIngest } from '@/hooks/useIngest'
import type { ApiError, IngestRequest } from '@/lib/api'
import { validateIngest, type Field, type Kind, type Problem } from '@/lib/ingest-validation'

interface IngestFormProps {
  onShowItem: (id: string) => void
}

function serverMessage(error: ApiError): string {
  const fields = error.details?.fields
  if (Array.isArray(fields) && fields.length > 0) {
    const first = fields[0] as { message?: string }
    if (first.message) return first.message
  }
  return error.message
}

export function IngestForm({ onShowItem }: IngestFormProps) {
  const ingest = useIngest()
  const [kind, setKind] = useState<Kind>('note')
  const [content, setContent] = useState('')
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [problem, setProblem] = useState<Problem | null>(null)

  const existingId = duplicateItemId(ingest.error)
  const serverError = ingest.error && !ingest.error.isNetworkError ? ingest.error : null
  const invalid = (field: Field) => problem?.field === field

  function submit(event: FormEvent) {
    event.preventDefault()
    const found = validateIngest(kind, content, title, url)
    setProblem(found)
    if (found) return
    const body: IngestRequest =
      kind === 'note'
        ? { type: 'note', content, title: title.trim() || null }
        : { type: 'url', url: url.trim() }
    ingest.mutate(body, {
      onSuccess: () => {
        setContent('')
        setTitle('')
        setUrl('')
      },
    })
  }

  function edit(setter: (value: string) => void, value: string) {
    setter(value)
    setProblem(null)
  }

  function switchKind(next: string) {
    setKind(next as Kind)
    setProblem(null)
    ingest.reset()
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <Tabs value={kind} onValueChange={switchKind}>
        <TabsList aria-label="What to save">
          <TabsTrigger value="note">Note</TabsTrigger>
          <TabsTrigger value="url">URL</TabsTrigger>
        </TabsList>
        <TabsContent value="note" className="space-y-2 pt-1">
          <Input
            aria-label="Title (optional)"
            placeholder="Title (optional)"
            value={title}
            onChange={(e) => edit(setTitle, e.target.value)}
            aria-invalid={invalid('title')}
            aria-describedby="title-error"
            disabled={ingest.isPending}
          />
          <FieldError id="title-error" problem={problem} field="title" />
          <Textarea
            aria-label="Note"
            placeholder="Paste or write a note…"
            value={content}
            rows={5}
            onChange={(e) => edit(setContent, e.target.value)}
            aria-invalid={invalid('content')}
            aria-describedby="content-error"
            disabled={ingest.isPending}
          />
          <FieldError id="content-error" problem={problem} field="content" />
        </TabsContent>
        <TabsContent value="url" className="space-y-2 pt-1">
          <Input
            type="url"
            aria-label="URL"
            placeholder="https://example.com/article"
            value={url}
            onChange={(e) => edit(setUrl, e.target.value)}
            aria-invalid={invalid('url')}
            aria-describedby="url-error"
            disabled={ingest.isPending}
          />
          <FieldError id="url-error" problem={problem} field="url" />
        </TabsContent>
      </Tabs>
      {existingId ? (
        <p className="text-sm text-partial" role="status">
          Already saved ·{' '}
          <button type="button" className="font-medium underline" onClick={() => onShowItem(existingId)}>
            Show it
          </button>
        </p>
      ) : (
        serverError && (
          <p className="text-sm text-destructive" role="alert">
            {serverMessage(serverError)}
          </p>
        )
      )}
      <Button type="submit" disabled={ingest.isPending}>
        {ingest.isPending ? 'Saving…' : 'Save'}
      </Button>
    </form>
  )
}
