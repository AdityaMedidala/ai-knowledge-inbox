import { Inbox } from 'lucide-react'
import { useEffect } from 'react'

import { ItemRow } from '@/components/inbox/ItemRow'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useItems } from '@/hooks/useItems'

interface ItemListProps {
  highlightedId: string | null
}

const SKELETON_ROWS = 3
const itemElementId = (id: string) => `item-${id}`

export function ItemList({ highlightedId }: ItemListProps) {
  const { items, isPending, isError, error, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useItems()

  useEffect(() => {
    if (!highlightedId) return
    document
      .getElementById(itemElementId(highlightedId))
      ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [highlightedId])

  if (isPending) {
    return (
      <ul className="space-y-2" aria-busy="true" aria-label="Loading items">
        {Array.from({ length: SKELETON_ROWS }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full rounded-2xl" />
        ))}
      </ul>
    )
  }
  if (isError && items.length === 0) {
    return <p className="text-sm text-destructive">Couldn't load your items: {error.message}</p>
  }
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-card border border-dashed p-8 text-center text-sm text-muted-foreground">
        <Inbox className="size-6" aria-hidden />
        <p>Your inbox is empty.</p>
        <p>Save a note or a URL above, then ask questions about it.</p>
      </div>
    )
  }
  return (
    <section className="space-y-2" aria-labelledby="saved-items-heading">
      <h3 id="saved-items-heading" className="section-label">
        Saved items
      </h3>
      <ul className="space-y-2">
        {items.map((item) => (
          <ItemRow
            key={item.id}
            item={item}
            elementId={itemElementId(item.id)}
            highlighted={item.id === highlightedId}
          />
        ))}
      </ul>
      {hasNextPage && (
        <Button
          variant="outline"
          className="w-full"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          {isFetchingNextPage ? 'Loading…' : 'Load more'}
        </Button>
      )}
    </section>
  )
}
