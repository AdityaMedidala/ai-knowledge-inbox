import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { CitationMarker } from '@/components/ask/CitationMarker'
import { VerdictMarker } from '@/components/ask/VerdictMarker'
import type { SentenceVerdict } from '@/lib/api'
import { CITE_HREF, linkCitations, markerParts } from '@/lib/citations'
import { insertVerdictMarkers, VERDICT_HREF } from '@/lib/verdicts'

interface AnswerViewProps {
  markdown: string
  validRefs: ReadonlySet<number>
  verdicts: readonly SentenceVerdict[] | null
  activeRef: number | null
  onSelect: (ref: number) => void
}

export function AnswerView({ markdown, validRefs, verdicts, activeRef, onSelect }: AnswerViewProps) {
  const byIndex = new Map((verdicts ?? []).map((v) => [v.index, v]))
  const components: Components = {
    a: ({ href, children }) => {
      if (href?.startsWith(CITE_HREF)) {
        const { ref, trailing } = markerParts(typeof children === 'string' ? children : '')
        return (
          <span className="whitespace-nowrap">
            <CitationMarker refNumber={ref} active={ref === activeRef} onSelect={onSelect} />
            {trailing}
          </span>
        )
      }
      if (href?.startsWith(VERDICT_HREF)) {
        const verdict = byIndex.get(Number(href.slice(VERDICT_HREF.length)))
        return verdict ? <VerdictMarker sentence={verdict} /> : null
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-foreground underline underline-offset-2">
          {children}
        </a>
      )
    },
  }
  const withVerdicts = verdicts ? insertVerdictMarkers(markdown, verdicts) : markdown

  return (
    <div className="space-y-3 text-sm leading-relaxed text-body [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_li]:ml-5 [&_ol]:list-decimal [&_strong]:font-semibold [&_ul]:list-disc">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(withVerdicts, validRefs)}
      </Markdown>
    </div>
  )
}
