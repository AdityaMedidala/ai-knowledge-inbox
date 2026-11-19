import { CircleCheck, CircleX, Contrast, type LucideIcon } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SentenceVerdict } from '@/lib/api'
import { cn } from '@/lib/utils'
import { verdictKind, type VerdictKind } from '@/lib/verdicts'

interface KindStyle {
  Icon: LucideIcon | null // null: a small neutral dot
  label: string
  tone: string
}

const KINDS: Record<VerdictKind, KindStyle> = {
  supported: { Icon: CircleCheck, label: 'supported', tone: 'text-supported' },
  partial: { Icon: Contrast, label: 'partly supported', tone: 'text-partial' },
  unsupported: { Icon: CircleX, label: 'unsupported', tone: 'text-unsupported' },
  uncited: { Icon: null, label: 'no citation — not checked', tone: 'text-muted-foreground' },
}

function KindIcon({ Icon }: { Icon: LucideIcon | null }) {
  if (Icon) return <Icon className="size-3.5" aria-hidden />
  return <span className="size-1.5 rounded-full bg-current" aria-hidden />
}

function detail(sentence: SentenceVerdict, kind: VerdictKind): string {
  const { label } = KINDS[kind]
  if (kind === 'uncited') return label
  return `${label[0]?.toUpperCase()}${label.slice(1)} · checked by ${sentence.decided_by}, ${Math.round(sentence.confidence * 100)}% confident`
}

/** Icon-only marker after a sentence; the words are in its tooltip, aria-label and the legend. */
export function VerdictMarker({ sentence }: { sentence: SentenceVerdict }) {
  const kind = verdictKind(sentence)
  const { Icon, tone } = KINDS[kind]
  const text = detail(sentence, kind)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          role="img"
          aria-label={`Verification: ${text}`}
          className={cn(
            'ml-1 inline-flex size-4 items-center justify-center rounded-full align-middle',
            tone,
          )}
        >
          <KindIcon Icon={Icon} />
        </span>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  )
}

export function VerdictLegend() {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
      {Object.values(KINDS).map(({ Icon, label, tone }) => (
        <li key={label} className="inline-flex items-center gap-1">
          <span className={cn('inline-flex size-3.5 items-center justify-center', tone)}>
            <KindIcon Icon={Icon} />
          </span>
          {label}
        </li>
      ))}
    </ul>
  )
}
