import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AppShell } from '@/components/layout/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { notifyIfServerError } from '@/lib/notify'

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: notifyIfServerError }),
  mutationCache: new MutationCache({ onError: notifyIfServerError }),
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AppShell />
        <Toaster richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
