import { CircleCheck, CircleDashed, CircleX } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SentenceVerdict } from '@/lib/api'
import { cn } from '@/lib/utils'

type VerdictName = SentenceVerdict['verdict']

const VERDICTS: Record<VerdictName, { Icon: typeof CircleCheck; label: string; tone: string }> = {
  supported: { Icon: CircleCheck, label: 'supported', tone: 'text-emerald-700 dark:text-emerald-400' },
  partial: { Icon: CircleDashed, label: 'partly supported', tone: 'text-amber-700 dark:text-amber-400' },
  unsupported: { Icon: CircleX, label: 'unsupported', tone: 'text-destructive' },
}

function detail(sentence: SentenceVerdict): string {
  if (sentence.decided_by === 'no_citation') return 'No citation, so it was not checked.'
  return `Checked by ${sentence.decided_by} (${Math.round(sentence.confidence * 100)}% confident).`
}

/** Small inline marker after a sentence: icon + word, details on hover/focus. */
export function VerdictMarker({ sentence }: { sentence: SentenceVerdict }) {
  const { Icon, label, tone } = VERDICTS[sentence.verdict]
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          aria-label={`Verification: ${label}. ${detail(sentence)}`}
          className={cn(
            'ml-1 inline-flex items-center gap-0.5 rounded px-1 align-middle text-[0.7rem] leading-4',
            tone,
          )}
        >
          <Icon className="size-3" aria-hidden />
          <span aria-hidden>{label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{detail(sentence)}</TooltipContent>
    </Tooltip>
  )
}

export function VerdictLegend() {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
      {Object.values(VERDICTS).map(({ Icon, label, tone }) => (
        <li key={label} className={cn('inline-flex items-center gap-1', tone)}>
          <Icon className="size-3" aria-hidden /> {label}
        </li>
      ))}
    </ul>
  )
}
