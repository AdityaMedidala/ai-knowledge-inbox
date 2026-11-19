import { useItems } from '@/hooks/useItems'

const MAX_EXAMPLES = 4
// Page titles often carry a subtitle or site name: "PEP 8 – Style Guide … | peps.python.org".
const TITLE_SUFFIX = /\s+[—–|-]\s+.*$/

function subjectOf(title: string): string {
  return title.replace(TITLE_SUFFIX, '').trim() || title
}

interface ExampleQuestionsProps {
  onPick: (question: string) => void
}

/** Starter questions built from the titles of ready items; a nudge to save first when empty. */
export function ExampleQuestions({ onPick }: ExampleQuestionsProps) {
  const { items, isPending } = useItems()
  if (isPending) return null
  if (items.length === 0) {
    return <p className="text-sm font-medium text-foreground">Save something first.</p>
  }
  const questions = items
    .filter((item) => item.status === 'ready' && item.title)
    .slice(0, MAX_EXAMPLES)
    .map((item) => `What is ${subjectOf(item.title ?? '')} about?`)
  if (questions.length === 0) return null

  return (
    <ul className="flex flex-wrap gap-2" aria-label="Example questions">
      {questions.map((question) => (
        <li key={question} className="max-w-full">
          <button
            type="button"
            title={question}
            onClick={() => onPick(question)}
            className="surface-frost block max-w-full truncate rounded-full px-3 py-1.5 text-left text-sm text-foreground transition-colors hover:bg-muted"
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  )
}
