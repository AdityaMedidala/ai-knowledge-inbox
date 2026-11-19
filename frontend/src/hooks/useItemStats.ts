import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { ITEMS_KEY, useItems } from '@/hooks/useItems'
import { api } from '@/lib/api'

/** Inbox totals. Refetched whenever the item list changes (a save, a delete, a status poll),
 * because chunk counts only move when items do; the previous totals stay up meanwhile. */
export function useItemStats() {
  const { dataUpdatedAt } = useItems()
  return useQuery({
    queryKey: [...ITEMS_KEY, 'stats', dataUpdatedAt],
    queryFn: api.itemStats,
    placeholderData: keepPreviousData,
  })
}
