import { Clock, Loader2, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { ItemSummary } from '@/lib/api'

/** Icon + word, so colour is never the only signal. Ready items show no badge: ready is the
 * normal state, and only the exceptions need calling out. */
export function StatusBadge({ status }: { status: ItemSummary['status'] }) {
  switch (status) {
    case 'ready':
      return null
    case 'failed':
      return (
        <Badge variant="destructive">
          <XCircle aria-hidden /> Failed
        </Badge>
      )
    case 'pending':
      return (
        <Badge variant="outline">
          <Clock aria-hidden /> Pending
        </Badge>
      )
    default:
      return (
        <Badge variant="outline">
          <Loader2 className="animate-spin" aria-hidden /> Processing
        </Badge>
      )
  }
}
