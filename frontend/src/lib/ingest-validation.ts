import { NOTE_MAX_CHARS, TITLE_MAX_CHARS, URL_MAX_CHARS } from './limits.ts'

export type Kind = 'note' | 'url'
export type Field = 'content' | 'title' | 'url'

export interface Problem {
  field: Field
  message: string
}

export function validateIngest(kind: Kind, content: string, title: string, url: string): Problem | null {
  if (kind === 'note') {
    if (!content.trim()) return { field: 'content', message: 'Write something to save.' }
    if (content.length > NOTE_MAX_CHARS)
      return { field: 'content', message: `Notes are limited to ${NOTE_MAX_CHARS} characters.` }
    if (title.length > TITLE_MAX_CHARS)
      return { field: 'title', message: `Titles are limited to ${TITLE_MAX_CHARS} characters.` }
    return null
  }
  const trimmed = url.trim()
  if (!/^https?:\/\/\S+$/i.test(trimmed))
    return { field: 'url', message: 'Enter an http:// or https:// URL.' }
  if (trimmed.length > URL_MAX_CHARS)
    return { field: 'url', message: `URLs are limited to ${URL_MAX_CHARS} characters.` }
  return null
}
