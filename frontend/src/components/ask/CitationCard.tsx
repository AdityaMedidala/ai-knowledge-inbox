import { ExternalLink, FileText } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Badge } from '@/components/ui/badge'
import type { Citation } from '@/lib/api'
import { cn } from '@/lib/utils'

interface CitationCardProps {
  citation: Citation
  active: boolean
  onSelect: (ref: number) => void
}

function citationCardId(ref: number): string {
  return `cite-${ref}`
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <Badge variant="outline" title="Found by keyword search only; no similarity score.">
        keyword match
      </Badge>
    )
  }
  return <Badge variant="outline">score {score.toFixed(2)}</Badge>
}

export function CitationCard({ citation, active, onSelect }: CitationCardProps) {
  const ref = useRef<HTMLLIElement>(null)

  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [active])

  const title = citation.title ?? citation.source_url ?? 'Untitled'
  return (
    <li
      ref={ref}
      id={citationCardId(citation.ref)}
      onClick={() => onSelect(citation.ref)}
      className={cn(
        'cursor-pointer space-y-1.5 rounded-lg border p-3 text-sm transition-colors',
        active ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted/50',
      )}
    >
      <div className="flex items-start gap-2">
        <span className="font-semibold text-muted-foreground">[{citation.ref}]</span>
        <div className="min-w-0 flex-1">
          {citation.item_type === 'url' && citation.source_url ? (
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 font-medium hover:underline"
            >
              {title} <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : (
            <span className="inline-flex items-center gap-1 font-medium">
              <FileText className="size-3" aria-hidden /> {title}
            </span>
          )}
          {citation.section && (
            <p className="text-xs text-muted-foreground">{citation.section}</p>
          )}
        </div>
        <ScoreBadge score={citation.score} />
      </div>
      <p className="text-muted-foreground">{citation.snippet}</p>
    </li>
  )
}
