import { useItemStats } from '@/hooks/useItemStats'

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/** One compact row: title, subtitle beside it (below on narrow screens), inbox totals right. */
export function AppHeader() {
  const { data: stats } = useItemStats()
  return (
    <header className="shrink-0 border-b">
      <div className="mx-auto flex min-h-16 max-w-[1400px] items-center gap-4 px-6 py-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h1 className="text-xl font-normal tracking-heading text-foreground">AI Knowledge Inbox</h1>
          <p className="text-sm text-muted-foreground">
            Save notes and links, then ask questions answered from them with sources.
          </p>
        </div>
        {stats && (
          <p className="shrink-0 text-sm text-muted-foreground tabular-nums">
            {plural(stats.items, 'item')} · {plural(stats.chunks, 'chunk')}
          </p>
        )}
      </div>
    </header>
  )
}
