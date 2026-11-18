import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { duplicateItemId, useIngest } from '@/hooks/useIngest'
import type { ApiError, IngestRequest } from '@/lib/api'
import { NOTE_MAX_CHARS, TITLE_MAX_CHARS, URL_MAX_CHARS } from '@/lib/limits'

type Kind = 'note' | 'url'

interface IngestFormProps {
  onShowItem: (id: string) => void
}

function validate(kind: Kind, content: string, title: string, url: string): string | null {
  if (kind === 'note') {
    if (!content.trim()) return 'Write something to save.'
    if (content.length > NOTE_MAX_CHARS) return `Notes are limited to ${NOTE_MAX_CHARS} characters.`
    if (title.length > TITLE_MAX_CHARS) return `Titles are limited to ${TITLE_MAX_CHARS} characters.`
    return null
  }
  const trimmed = url.trim()
  if (!/^https?:\/\/\S+$/i.test(trimmed)) return 'Enter an http:// or https:// URL.'
  if (trimmed.length > URL_MAX_CHARS) return `URLs are limited to ${URL_MAX_CHARS} characters.`
  return null
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
  const [clientError, setClientError] = useState<string | null>(null)

  const existingId = duplicateItemId(ingest.error)
  const serverError = ingest.error && !ingest.error.isNetworkError ? ingest.error : null

  function submit(event: FormEvent) {
    event.preventDefault()
    const problem = validate(kind, content, title, url)
    setClientError(problem)
    if (problem) return
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

  function switchKind(next: string) {
    setKind(next as Kind)
    setClientError(null)
    ingest.reset()
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <Tabs value={kind} onValueChange={switchKind}>
        <TabsList>
          <TabsTrigger value="note">Note</TabsTrigger>
          <TabsTrigger value="url">URL</TabsTrigger>
        </TabsList>
        <TabsContent value="note" className="space-y-2">
          <Input
            placeholder="Title (optional)"
            value={title}
            maxLength={TITLE_MAX_CHARS}
            onChange={(e) => setTitle(e.target.value)}
            disabled={ingest.isPending}
          />
          <Textarea
            placeholder="Paste or write a note…"
            value={content}
            rows={5}
            onChange={(e) => setContent(e.target.value)}
            disabled={ingest.isPending}
          />
        </TabsContent>
        <TabsContent value="url">
          <Input
            type="url"
            placeholder="https://example.com/article"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={ingest.isPending}
          />
        </TabsContent>
      </Tabs>
      {clientError && <p className="text-sm text-destructive">{clientError}</p>}
      {existingId ? (
        <p className="text-sm text-amber-700 dark:text-amber-400">
          Already saved.{' '}
          <button type="button" className="underline" onClick={() => onShowItem(existingId)}>
            Show it
          </button>
        </p>
      ) : (
        serverError && <p className="text-sm text-destructive">{serverMessage(serverError)}</p>
      )}
      <Button type="submit" disabled={ingest.isPending}>
        {ingest.isPending ? 'Saving…' : 'Save'}
      </Button>
    </form>
  )
}
