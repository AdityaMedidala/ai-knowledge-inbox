import { CheckCircle2, Loader2, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { ItemSummary } from '@/lib/api'

interface StatusBadgeProps {
  status: ItemSummary['status']
  error: ItemSummary['error']
}

export function StatusBadge({ status, error }: StatusBadgeProps) {
  if (status === 'ready') {
    return (
      <Badge variant="secondary">
        <CheckCircle2 aria-hidden /> Ready
      </Badge>
    )
  }
  if (status === 'failed') {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="destructive" tabIndex={0}>
            <XCircle aria-hidden /> Failed
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          {error ? `${error.message} (${error.code})` : 'Processing failed.'}
        </TooltipContent>
      </Tooltip>
    )
  }
  return (
    <Badge variant="outline">
      <Loader2 className="animate-spin" aria-hidden />
      {status === 'pending' ? 'Pending' : 'Processing'}
    </Badge>
  )
}
