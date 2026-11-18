import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ITEMS_KEY } from '@/hooks/useItems'
import { api, ApiError } from '@/lib/api'

export function useDeleteItem() {
  const queryClient = useQueryClient()
  return useMutation<void, ApiError, string>({
    mutationFn: api.deleteItem,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ITEMS_KEY }),
    onError: (error) => {
      if (error.isNetworkError || error.status >= 500) return // the global toast covers these
      toast.error(`Couldn't delete: ${error.message}`, {
        description: error.requestId ? `request_id: ${error.requestId}` : undefined,
      })
    },
  })
}
