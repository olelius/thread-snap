import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createHashHistory, RouterProvider } from '@tanstack/react-router'
import { ThemeProvider } from '@/context/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import { EventBridge } from '@/components/event-bridge'
import { router } from '@/router'
import '@/styles/index.css'
import './tactile.css'

// 保留历史预览链接；Hash 路由使刷新、深链和前进后退始终留在此入口。
router.update({ history: createHashHistory() })

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider defaultTheme='system'>
      <QueryClientProvider client={queryClient}>
        <EventBridge />
        <RouterProvider router={router} />
        <Toaster richColors closeButton position='top-right' customAriaLabel='通知' containerAriaLabel='通知' toastOptions={{ closeButtonAriaLabel: '关闭通知' }} />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
