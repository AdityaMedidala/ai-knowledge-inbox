import { useState, type ReactNode } from 'react'

import { AskPanel } from '@/components/ask/AskPanel'
import { IngestForm } from '@/components/inbox/IngestForm'
import { ItemList } from '@/components/inbox/ItemList'
import { AppHeader } from '@/components/layout/AppHeader'
import { cn } from '@/lib/utils'

/** Desktop: a fixed-width Inbox column and Ask filling the rest, both exactly the viewport height
 * below the header; the item list and the answer scroll inside their panes, never the page.
 * Narrow screens: the panes stack and the page scrolls as usual. */
export function AppShell() {
  const [highlightedItemId, setHighlightedItemId] = useState<string | null>(null)

  return (
    <div className="flex min-h-svh flex-col lg:h-svh lg:overflow-hidden">
      <AppHeader />
      <main className="mx-auto grid w-full max-w-[1400px] grid-cols-[minmax(0,1fr)] gap-6 p-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[400px_minmax(0,1fr)]">
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
      className={cn('surface-card relative flex flex-col gap-4 p-5 lg:min-h-0', glow && 'overflow-hidden')}
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
