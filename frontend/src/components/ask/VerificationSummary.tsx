import { ShieldCheck } from 'lucide-react'

import { VerdictLegend } from '@/components/ask/VerdictMarker'
import type { Verification } from '@/lib/api'

/** Summary line + legend; the per-sentence markers sit inline in the answer (AnswerView). */
export function VerificationSummary({ verification }: { verification: Verification }) {
  const { supported, total } = verification.summary
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border bg-muted px-4 py-2.5">
      <p className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground">
        <ShieldCheck className="size-4 text-muted-foreground" aria-hidden />
        {supported} of {total} {total === 1 ? 'sentence' : 'sentences'} supported by their sources
      </p>
      <VerdictLegend />
    </div>
  )
}
