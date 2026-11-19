import { ExternalLink, FileText } from 'lucide-react'
import { useEffect, useRef } from 'react'

import type { Citation } from '@/lib/api'
import { cn } from '@/lib/utils'

interface CitationCardProps {
  citation: Citation
  active: boolean
}

function citationCardId(ref: number): string {
  return `cite-${ref}`
}

function ScoreText({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span
        className="shrink-0 text-xs text-muted-foreground"
        title="Found by keyword search only; no similarity score."
      >
        keyword match
      </span>
    )
  }
  return (
    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
      score {score.toFixed(2)}
    </span>
  )
}

export function CitationCard({ citation, active }: CitationCardProps) {
  const ref = useRef<HTMLLIElement>(null)

  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [active])

  const title = citation.title ?? citation.source_url ?? 'Untitled'
  return (
    <li
      ref={ref}
      id={citationCardId(citation.ref)}
      className={cn(
        'surface-card space-y-2 p-4 text-sm transition-colors',
        active && 'border-primary ring-1 ring-primary',
      )}
    >
      <div className="flex items-start gap-2">
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary-soft px-1.5 text-xs font-semibold text-primary">
          {citation.ref}
        </span>
        <div className="min-w-0 flex-1">
          {citation.item_type === 'url' && citation.source_url ? (
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-medium text-foreground hover:underline"
            >
              {title} <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : (
            <span className="inline-flex items-center gap-1 font-medium text-foreground">
              <FileText className="size-3" aria-hidden /> {title}
            </span>
          )}
          {citation.section && (
            <p className="text-xs text-muted-foreground">{citation.section}</p>
          )}
        </div>
        <ScoreText score={citation.score} />
      </div>
      <p className="leading-relaxed text-foreground">{citation.snippet}</p>
    </li>
  )
}
