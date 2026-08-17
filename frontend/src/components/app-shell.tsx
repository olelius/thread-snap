import { useEffect, useState } from 'react'
import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { Cable, LayoutList, Settings2, Sparkles } from 'lucide-react'
import { ThemeToggle } from './theme-toggle'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { TooltipProvider } from '@/components/ui/tooltip'

const navigation = [
  { to: '/runs' as const, search: { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, from: undefined, to: undefined }, label: '提取列表', description: '批次与结果', icon: LayoutList },
  { to: '/config' as const, search: { tab: 'plan' as const }, label: '配置管理', description: '计划与来源', icon: Settings2 },
]

export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const reduceMotion = useReducedMotion()
  const [connected, setConnected] = useState(document.documentElement.dataset.backendConnected === 'true')
  useEffect(() => {
    const update = (event: Event) => setConnected(Boolean((event as CustomEvent<boolean>).detail))
    window.addEventListener('threadsnap:connection', update)
    return () => window.removeEventListener('threadsnap:connection', update)
  }, [])
  return (
    <TooltipProvider delayDuration={150}>
      <SidebarProvider defaultOpen>
        <Sidebar collapsible='icon' variant='inset'>
          <SidebarHeader className='border-b border-sidebar-border/70 p-3 transition-[padding] duration-200 ease-out motion-reduce:transition-none group-data-[collapsible=icon]:p-2!'>
            <div className='flex h-11 items-center gap-3 overflow-hidden rounded-lg bg-gradient-to-br from-primary/15 to-cyan-400/10 px-2 ring-1 ring-primary/10 transition-[width,height,padding,gap] duration-200 ease-out motion-reduce:transition-none group-data-[collapsible=icon]:size-10! group-data-[collapsible=icon]:self-center group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0! group-data-[collapsible=icon]:px-0!'>
              <div className='grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground shadow-lg shadow-primary/20 transition-[width,height,border-radius] duration-200 ease-out motion-reduce:transition-none group-data-[collapsible=icon]:size-7! group-data-[collapsible=icon]:rounded-md!'>
                <Sparkles className='size-4 transition-[width,height] duration-200 ease-out motion-reduce:transition-none group-data-[collapsible=icon]:size-3.5!' />
              </div>
              <div className='min-w-0 group-data-[collapsible=icon]:hidden'>
                <div className='truncate text-sm font-semibold tracking-wide'>ThreadSnap</div>
                <div className='truncate text-[11px] text-muted-foreground'>链接快照提取控制台</div>
              </div>
            </div>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupLabel>工作区</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {navigation.map((item) => (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton
                        asChild
                        isActive={pathname === item.to || pathname.startsWith(`${item.to}/`)}
                        tooltip={item.label}
                        className='h-11 transition-[background-color,color,transform] duration-200'
                      >
                        <Link to={item.to} search={item.search}>
                          <item.icon />
                          <span className='flex min-w-0 flex-col'>
                            <span className='truncate'>{item.label}</span>
                            <span className='truncate text-[10px] text-muted-foreground'>{item.description}</span>
                          </span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter className='p-3'>
            <div className='flex items-center gap-2 rounded-lg border border-sidebar-border bg-background/50 p-2 text-xs text-muted-foreground group-data-[collapsible=icon]:justify-center'>
              <Cable className={`size-4 shrink-0 ${connected ? 'text-cyan-500' : 'text-amber-500'}`} />
              <span className='truncate group-data-[collapsible=icon]:hidden'>{connected ? '后端服务已连接' : '正在连接后端服务'}</span>
            </div>
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset className='min-w-0 overflow-hidden bg-transparent'>
          <header className='sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border/65 bg-background/82 px-4 backdrop-blur-xl sm:px-6'>
            <SidebarTrigger className='-ml-1 transition-transform duration-200 hover:scale-105' />
            <Separator orientation='vertical' className='h-5' />
            <div className='min-w-0 flex-1 truncate text-sm font-medium text-muted-foreground'>
              {pathname.startsWith('/config') ? '配置管理' : pathname.includes('/runs/') ? '批次链接详情' : '提取列表'}
            </div>
            <div className='hidden items-center gap-2 text-xs text-muted-foreground sm:flex'>
              <span className='relative flex size-2'>
                {connected && <span className='absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60' />}
                <span className={`relative inline-flex size-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              </span>
              {connected ? '实时状态在线' : '实时状态重连中'}
            </div>
            <ThemeToggle />
          </header>
          <motion.main
            key={pathname}
            initial={reduceMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className='min-w-0 flex-1 p-4 sm:p-6 lg:p-8'
          >
            <Outlet />
          </motion.main>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
