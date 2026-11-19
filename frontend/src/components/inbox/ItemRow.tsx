import { FileText, Link2, Trash2 } from 'lucide-react'

import { StatusBadge } from '@/components/inbox/StatusBadge'
import { Button } from '@/components/ui/button'
import { useDeleteItem } from '@/hooks/useDeleteItem'
import type { ItemSummary } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'

interface ItemRowProps {
  item: ItemSummary
  elementId: string
  highlighted: boolean
}

function domainOf(url: string | null): string | null {
  if (!url) return null
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

/** Title, else the note's first line, else the URL without its scheme. */
function headingOf(item: ItemSummary): string {
  const firstLine = item.preview?.split('\n').find((line) => line.trim())
  const bareUrl = item.source_url?.replace(/^https?:\/\/(www\.)?/, '')
  return item.title ?? (item.type === 'note' ? firstLine : bareUrl) ?? firstLine ?? 'Untitled'
}

export function ItemRow({ item, elementId, highlighted }: ItemRowProps) {
  const remove = useDeleteItem()
  const isUrl = item.type === 'url'
  const TypeIcon = isUrl ? Link2 : FileText
  const heading = headingOf(item)
  const domain = isUrl ? domainOf(item.source_url) : null

  return (
    <li
      id={elementId}
      className={cn(
        'flex items-start gap-3 rounded-2xl border bg-background p-3 transition-colors',
        item.status === 'failed' && 'border-unsupported/30',
        highlighted && 'border-foreground/40 bg-muted',
      )}
    >
      <TypeIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="truncate text-sm font-medium text-foreground" title={heading}>
          <span className="sr-only">{isUrl ? 'Link: ' : 'Note: '}</span>
          {heading}
        </p>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <StatusBadge status={item.status} />
          {domain && item.source_url && (
            <a href={item.source_url} target="_blank" rel="noopener noreferrer" className="hover:underline">
              {domain}
            </a>
          )}
          <span>{relativeTime(item.created_at)}</span>
          {item.status === 'ready' && (
            <span>
              {item.chunk_count} {item.chunk_count === 1 ? 'chunk' : 'chunks'}
            </span>
          )}
        </div>
        {item.status === 'failed' && (
          <p className="text-xs text-destructive">
            {item.error?.message ?? 'Processing failed.'}
            {item.error?.code && <span className="ml-1 font-mono opacity-80">({item.error.code})</span>}
          </p>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Delete ${heading}`}
        disabled={remove.isPending}
        onClick={() => remove.mutate(item.id)}
      >
        <Trash2 />
      </Button>
    </li>
  )
}
