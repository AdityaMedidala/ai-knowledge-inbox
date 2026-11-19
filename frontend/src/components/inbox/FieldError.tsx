import type { Field, Problem } from '@/lib/ingest-validation'

/** The inline message under a field, linked to it by aria-describedby. */
export function FieldError({ id, problem, field }: { id: string; problem: Problem | null; field: Field }) {
  if (problem?.field !== field) return null
  return (
    <p id={id} className="px-4 text-xs text-destructive">
      {problem.message}
    </p>
  )
}
