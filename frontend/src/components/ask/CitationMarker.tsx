import { cn } from '@/lib/utils'

interface CitationMarkerProps {
  refNumber: number
  active: boolean
  onSelect: (ref: number) => void
}

/** Inline source pill; clicking it scrolls to and highlights the matching source card. */
export function CitationMarker({ refNumber, active, onSelect }: CitationMarkerProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(refNumber)}
      aria-label={`Source ${refNumber}`}
      aria-pressed={active}
      className={cn(
        'mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full border px-1.5 align-middle text-[0.65rem] font-semibold leading-none transition-colors',
        active
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-muted text-foreground hover:border-primary',
      )}
    >
      {refNumber}
    </button>
  )
}
