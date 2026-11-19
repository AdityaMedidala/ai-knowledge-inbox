import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

/** Server facts that do not change while the page is open (e.g. demo mode). */
export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: Infinity })
}
