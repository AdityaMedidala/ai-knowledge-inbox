import { useState } from 'react'

import { AskPanel } from '@/components/ask/AskPanel'
import { IngestForm } from '@/components/inbox/IngestForm'
import { ItemList } from '@/components/inbox/ItemList'

/** Two panes: Inbox (save + list) on the left, Ask on the right; stacked on narrow screens. */
export function AppShell() {
  const [highlightedItemId, setHighlightedItemId] = useState<string | null>(null)

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="border-b px-4 py-3 sm:px-6">
        <h1 className="text-lg font-semibold">AI Knowledge Inbox</h1>
      </header>
      <main className="grid gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-labelledby="inbox-heading" className="space-y-4">
          <h2 id="inbox-heading" className="text-base font-semibold">
            Inbox
          </h2>
          <IngestForm onShowItem={setHighlightedItemId} />
          <ItemList highlightedId={highlightedItemId} />
        </section>
        <section aria-labelledby="ask-heading" className="space-y-4">
          <h2 id="ask-heading" className="text-base font-semibold">
            Ask
          </h2>
          <AskPanel />
        </section>
      </main>
    </div>
  )
}
