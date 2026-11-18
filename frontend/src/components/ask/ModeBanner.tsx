import { CircleAlert, SearchX } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { RetrievalMode } from '@/lib/api'

export function ModeBanner({ mode }: { mode: RetrievalMode | null }) {
  if (mode === 'partial') {
    return (
      <Alert>
        <CircleAlert aria-hidden />
        <AlertTitle>Partial match</AlertTitle>
        <AlertDescription>Your saved items may only partly answer this.</AlertDescription>
      </Alert>
    )
  }
  if (mode === 'none') {
    return (
      <Alert>
        <SearchX aria-hidden />
        <AlertTitle>Not found in your saved items</AlertTitle>
        <AlertDescription>Nothing saved is relevant enough, so no answer was generated.</AlertDescription>
      </Alert>
    )
  }
  return null
}
