import { useInfiniteQuery } from '@tanstack/react-query'

import { api, type ItemList, type ItemSummary } from '@/lib/api'

export const ITEMS_KEY = ['items'] as const
const POLL_MS = 1500

function isInFlight(item: ItemSummary): boolean {
  return item.status === 'pending' || item.status === 'processing'
}

/** Newest-first inbox; polls only while some loaded item is still pending/processing. */
export function useItems() {
  const query = useInfiniteQuery({
    queryKey: ITEMS_KEY,
    queryFn: ({ pageParam }) => api.listItems(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last: ItemList) => last.next_cursor,
    refetchInterval: (q) =>
      q.state.data?.pages.some((page) => page.items.some(isInFlight)) ? POLL_MS : false,
  })
  const items = query.data?.pages.flatMap((page) => page.items) ?? []
  return { ...query, items }
}
