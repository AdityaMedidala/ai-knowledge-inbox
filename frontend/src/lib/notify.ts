import { toast } from 'sonner'

import { ApiError } from '@/lib/api'

/** Toast for errors the user can't fix in a form: unreachable server or a 5xx. */
export function notifyIfServerError(error: unknown): void {
  if (!(error instanceof ApiError)) return
  if (!error.isNetworkError && error.status < 500) return
  toast.error(error.message, {
    id: error.code, // one toast per kind, not one per polling retry
    description: error.requestId ? `request_id: ${error.requestId}` : undefined,
  })
}
