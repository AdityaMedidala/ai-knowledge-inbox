import { useState, type ReactNode } from 'react'

import { AskPanel } from '@/components/ask/AskPanel'
import { IngestForm } from '@/components/inbox/IngestForm'
import { ItemList } from '@/components/inbox/ItemList'

/** Inbox (save + list) on the left, Ask on the right on desktop; stacked on narrow screens. */
export function AppShell() {
  const [highlightedItemId, setHighlightedItemId] = useState<string | null>(null)

  return (
    <div className="min-h-svh bg-muted/30 text-foreground">
      <header className="border-b bg-background">
        <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6">
          <h1 className="text-lg font-semibold">AI Knowledge Inbox</h1>
          <p className="text-sm text-muted-foreground">
            Save notes and links, then ask questions answered from them with sources.
          </p>
        </div>
      </header>
      <main className="mx-auto grid max-w-6xl grid-cols-[minmax(0,1fr)] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
        <Pane id="inbox-heading" title="Inbox">
          <IngestForm onShowItem={setHighlightedItemId} />
          <ItemList highlightedId={highlightedItemId} />
        </Pane>
        <Pane id="ask-heading" title="Ask">
          <AskPanel />
        </Pane>
      </main>
    </div>
  )
}

function Pane({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-4 rounded-xl border bg-background p-4 sm:p-5">
      <h2 id={id} className="text-base font-semibold">
        {title}
      </h2>
      {children}
    </section>
  )
}
