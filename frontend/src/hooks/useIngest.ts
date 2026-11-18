import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ITEMS_KEY } from '@/hooks/useItems'
import { api, type ApiError, type IngestRequest, type IngestResponse } from '@/lib/api'

export function useIngest() {
  const queryClient = useQueryClient()
  return useMutation<IngestResponse, ApiError, IngestRequest>({
    mutationFn: api.ingest,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ITEMS_KEY }),
  })
}

/** `details.existing_id` of a 409 DUPLICATE_ITEM, else null. */
export function duplicateItemId(error: ApiError | null): string | null {
  if (error?.code !== 'DUPLICATE_ITEM') return null
  const id = error.details?.existing_id
  return typeof id === 'string' ? id : null
}
