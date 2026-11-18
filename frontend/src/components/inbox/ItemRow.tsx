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

export function ItemRow({ item, elementId, highlighted }: ItemRowProps) {
  const remove = useDeleteItem()
  const TypeIcon = item.type === 'url' ? Link2 : FileText
  const heading = item.title ?? item.preview ?? item.source_url ?? 'Untitled'

  return (
    <li
      id={elementId}
      className={cn(
        'flex items-start gap-3 rounded-lg border p-3 transition-colors',
        highlighted && 'border-primary bg-primary/5',
      )}
    >
      <TypeIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-label={item.type} />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="truncate font-medium" title={heading}>
          {heading}
        </p>
        {item.type === 'url' && item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block truncate text-xs text-muted-foreground hover:underline"
          >
            {item.source_url}
          </a>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <StatusBadge status={item.status} error={item.error} />
          <span>{relativeTime(item.created_at)}</span>
          {item.status === 'ready' && (
            <span>
              {item.chunk_count} {item.chunk_count === 1 ? 'chunk' : 'chunks'}
            </span>
          )}
        </div>
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
