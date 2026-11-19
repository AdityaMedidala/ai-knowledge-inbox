import { useState, type ReactNode } from 'react'

import { AskPanel } from '@/components/ask/AskPanel'
import { IngestForm } from '@/components/inbox/IngestForm'
import { ItemList } from '@/components/inbox/ItemList'
import { cn } from '@/lib/utils'

/** Inbox (save + list) on the left, Ask on the right on desktop; stacked on narrow screens. */
export function AppShell() {
  const [highlightedItemId, setHighlightedItemId] = useState<string | null>(null)

  return (
    <div className="min-h-svh">
      <header className="border-b">
        <div className="mx-auto max-w-6xl space-y-1 px-4 py-6 sm:px-6">
          <h1 className="text-3xl font-normal tracking-heading text-foreground">AI Knowledge Inbox</h1>
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
        <Pane id="ask-heading" title="Ask" glow>
          <AskPanel />
        </Pane>
      </main>
    </div>
  )
}

interface PaneProps {
  id: string
  title: string
  glow?: boolean
  children: ReactNode
}

function Pane({ id, title, glow = false, children }: PaneProps) {
  return (
    <section
      aria-labelledby={id}
      className={cn('surface-card relative space-y-5 p-5 sm:p-6', glow && 'overflow-hidden')}
    >
      {glow && (
        <div
          aria-hidden
          className="glow-accent pointer-events-none absolute -top-20 left-1/2 h-44 w-4/5 -translate-x-1/2"
        />
      )}
      <h2 id={id} className="section-label relative">
        {title}
      </h2>
      {children}
    </section>
  )
}
