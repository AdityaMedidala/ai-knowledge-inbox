import { CitationCard } from '@/components/ask/CitationCard'
import type { Citation } from '@/lib/api'

interface CitationListProps {
  heading: string
  citations: Citation[]
  activeRef: number | null
  onSelect: (ref: number) => void
}

export function CitationList({ heading, citations, activeRef, onSelect }: CitationListProps) {
  if (citations.length === 0) return null
  return (
    <section className="space-y-2" aria-label={heading}>
      <h3 className="text-sm font-semibold">{heading}</h3>
      <ol className="space-y-2">
        {citations.map((citation) => (
          <CitationCard
            key={citation.ref}
            citation={citation}
            active={citation.ref === activeRef}
            onSelect={onSelect}
          />
        ))}
      </ol>
    </section>
  )
}
