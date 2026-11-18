import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { CitationMarker } from '@/components/ask/CitationMarker'

interface AnswerViewProps {
  markdown: string
  validRefs: ReadonlySet<number>
  activeRef: number | null
  onSelect: (ref: number) => void
}

const CITE_HREF = '#cite-'
// [1], [1, 2], [1][2] and fullwidth 【1】 (some models emit it); not markdown links like [1](…)
const MARKER = /[[【](\d+(?:\s*,\s*\d+)*)[\]】](?!\()/g

/** Turn [n] markers that point at a real source into `[n](#cite-n)` links; leave others as text. */
function linkCitations(markdown: string, validRefs: ReadonlySet<number>): string {
  return markdown.replace(MARKER, (whole, refs: string) => {
    const numbers = refs.split(',').map((n) => Number(n.trim()))
    if (!numbers.every((n) => validRefs.has(n))) return whole
    return numbers.map((n) => `[${n}](${CITE_HREF}${n})`).join('')
  })
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
