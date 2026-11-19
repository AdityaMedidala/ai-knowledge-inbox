import { ShieldCheck } from 'lucide-react'

import { VerdictLegend } from '@/components/ask/VerdictMarker'
import type { Verification } from '@/lib/api'
import { summarizeVerdicts } from '@/lib/verdicts'

function summaryText(verification: Verification): string {
  const { cited, supported, uncited } = summarizeVerdicts(verification.sentences)
  const parts = [`${supported} of ${cited} cited ${cited === 1 ? 'sentence' : 'sentences'} supported`]
  if (uncited > 0) parts.push(`${uncited} without citation`)
  return parts.join(' · ')
}

/** Summary line + legend; the per-sentence markers sit inline in the answer (AnswerView). */
export function VerificationSummary({ verification }: { verification: Verification }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border bg-muted px-4 py-2.5">
      <p className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground">
        <ShieldCheck className="size-4 text-muted-foreground" aria-hidden />
        {summaryText(verification)}
      </p>
      <VerdictLegend />
    </div>
  )
}
