import { CircleCheck, CircleDashed, CircleX } from 'lucide-react'

import type { SentenceVerdict, Verification } from '@/lib/api'

const VERDICTS = {
  supported: { Icon: CircleCheck, label: 'Supported', className: 'text-green-600' },
  partial: { Icon: CircleDashed, label: 'Partly supported', className: 'text-amber-600' },
  unsupported: { Icon: CircleX, label: 'Unsupported', className: 'text-destructive' },
} as const

function describe(sentence: SentenceVerdict): string {
  if (sentence.decided_by === 'no_citation') return 'no citation'
  return `${sentence.decided_by}, ${Math.round(sentence.confidence * 100)}%`
}

/** One line per answer sentence: verdict marker, text, and who decided. */
export function VerificationView({ verification }: { verification: Verification }) {
  const { supported, total } = verification.summary
  return (
    <section aria-label="Verification" className="space-y-2 text-sm">
      <h3 className="font-semibold">
        {supported} of {total} {total === 1 ? 'sentence' : 'sentences'} supported
      </h3>
      <ul className="space-y-1">
        {verification.sentences.map((sentence) => {
          const { Icon, label, className } = VERDICTS[sentence.verdict]
          return (
            <li key={sentence.index} className="flex items-start gap-2">
              <Icon className={`mt-0.5 size-4 shrink-0 ${className}`} aria-label={label} />
              <span>
                {sentence.sentence}{' '}
                <span className="text-xs text-muted-foreground">
                  ({label.toLowerCase()} · {describe(sentence)})
                </span>
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
