import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CreditDashboardPage } from './credit-dashboard-page'
import '@/styles/index.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

document.documentElement.classList.add('dark')
document.documentElement.style.overflow = 'auto'
document.body.style.overflow = 'auto'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <div style={{ padding: '32px', minHeight: '100vh', background: '#15151d' }}>
        <CreditDashboardPage />
      </div>
    </QueryClientProvider>
  </StrictMode>,
)
