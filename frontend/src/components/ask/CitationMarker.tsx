import { cn } from '@/lib/utils'

interface CitationMarkerProps {
  refNumber: number
  active: boolean
  onSelect: (ref: number) => void
}

export function CitationMarker({ refNumber, active, onSelect }: CitationMarkerProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(refNumber)}
      aria-label={`Show source ${refNumber}`}
      className={cn(
        'mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded px-1 align-super text-[0.7rem] font-semibold',
        active ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground hover:bg-primary/20',
      )}
    >
      {refNumber}
    </button>
  )
}
