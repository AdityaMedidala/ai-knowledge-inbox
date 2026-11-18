import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { CitationMarker } from '@/components/ask/CitationMarker'
import { CITE_HREF, linkCitations } from '@/lib/citations'

interface AnswerViewProps {
  markdown: string
  validRefs: ReadonlySet<number>
  activeRef: number | null
  onSelect: (ref: number) => void
}

export function AnswerView({ markdown, validRefs, activeRef, onSelect }: AnswerViewProps) {
  const components: Components = {
    a: ({ href, children }) => {
      if (href?.startsWith(CITE_HREF)) {
        const ref = Number(href.slice(CITE_HREF.length))
        return <CitationMarker refNumber={ref} active={ref === activeRef} onSelect={onSelect} />
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
          {children}
        </a>
      )
    },
  }

  return (
    <div className="space-y-3 text-sm leading-relaxed [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_li]:ml-5 [&_ol]:list-decimal [&_strong]:font-semibold [&_ul]:list-disc">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(markdown, validRefs)}
      </Markdown>
    </div>
  )
}
