import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createHashHistory, RouterProvider } from '@tanstack/react-router'
import { ThemeProvider } from '@/context/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import { EventBridge } from '@/components/event-bridge'
import { router } from '@/router'
import { TactileShell } from './tactile-shell'
import '@/styles/index.css'
import './tactile.css'

// 此入口独占一个 HTML 文档；只更新本页路由实例的外壳，不修改原入口和路由源码。
// Hash 路由使刷新、深链和前进后退始终留在 tactile.html，而不是落回默认 UI。
router.routeTree.update({ component: TactileShell })
router.update({ history: createHashHistory() })

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider defaultTheme='light' storageKey='threadsnap-tactile-theme'>
      <QueryClientProvider client={queryClient}>
        <EventBridge />
        <RouterProvider router={router} />
        <Toaster richColors closeButton position='top-right' customAriaLabel='通知' containerAriaLabel='通知' toastOptions={{ closeButtonAriaLabel: '关闭通知' }} />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
