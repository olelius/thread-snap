import { useEffect, useState } from 'react'
import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { ChartNoAxesCombined, ChevronRight, House, Layers3, LayoutList, Repeat2, Settings2, Waves } from 'lucide-react'
import { ThemeToggle } from '@/components/theme-toggle'
import { GlobalCommandMenu } from '@/components/global-command-menu'
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent,
  SidebarGroupLabel, SidebarHeader, SidebarInset, SidebarMenu, SidebarMenuButton,
  SidebarMenuItem, SidebarProvider, SidebarRail, SidebarTrigger, useSidebar,
} from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { getCookie, setCookie } from '@/lib/cookies'

const emptyRunsSearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, listOrder: undefined, from: undefined, to: undefined }
const navigation = [
  { to: '/' as const, search: undefined, label: '首页', subtitle: '概览与近期工作', icon: House, number: '00' },
  { to: '/runs' as const, search: emptyRunsSearch, label: '提取列表', subtitle: '批次与快照', icon: LayoutList, number: '01' },
  { to: '/recurring-runs' as const, search: emptyRunsSearch, label: '循环计划', subtitle: '独立周期批次', icon: Repeat2, number: '02' },
  { to: '/reputation' as const, search: { tab: 'runs' as const, page: undefined }, label: '口碑巡检', subtitle: '排名与页面证据', icon: ChartNoAxesCombined, number: '03' },
  { to: '/config' as const, search: { tab: 'rules' as const }, label: '配置管理', subtitle: '规则、计划与来源', icon: Settings2, number: '04' },
]

/** 默认触感外壳；导航记忆独立保存，业务页面和提交路径沿用现有实现。 */
export function TactileShell() {
  const [open, setOpen] = useState(() => getCookie('threadsnap-tactile-sidebar') !== 'false')
  const saveOpen = (next: boolean) => {
    setOpen(next)
    setCookie('threadsnap-tactile-sidebar', String(next), 60 * 60 * 24 * 365)
  }
  return (
    <TooltipProvider delayDuration={150}>
      <SidebarProvider open={open} onOpenChange={saveOpen} className='tactile-root h-svh min-h-0 overflow-hidden'>
        <TactileNavigation />
      </SidebarProvider>
    </TooltipProvider>
  )
}

/** 导航沿用 Sidebar 原语，窄屏点击后收起 Sheet；不重写焦点和键盘机制。 */
function TactileNavigation() {
  const { isMobile, setOpenMobile } = useSidebar()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const reduceMotion = useReducedMotion()
  const current = navigation.find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`)) ?? navigation[0]
  const [connected, setConnected] = useState(document.documentElement.dataset.backendConnected === 'true')
  useEffect(() => {
    const update = (event: Event) => setConnected(Boolean((event as CustomEvent<boolean>).detail))
    window.addEventListener('threadsnap:connection', update)
    return () => window.removeEventListener('threadsnap:connection', update)
  }, [])

  return (
    <>
      <a className='tactile-skip-link' href='#tactile-content' onClick={(event) => { event.preventDefault(); document.getElementById('tactile-content')?.focus() }}>跳至主要内容</a>
      <Sidebar collapsible='icon' variant='inset' className='tactile-sidebar'>
        <SidebarHeader className='tactile-brand'>
          <div className='tactile-brand-mark' aria-hidden='true'><Layers3 size={23} strokeWidth={1.65} /></div>
          <div className='tactile-brand-copy group-data-[collapsible=icon]:hidden'><strong>ThreadSnap</strong><small>让每次讨论，有迹可循。</small></div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className='tactile-nav-label'>工作空间 <span>WORKSPACE</span></SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className='tactile-nav'>
                {navigation.map((item) => {
                  const active = current.to === item.to
                  return (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton asChild isActive={active} tooltip={item.label} className='tactile-nav-item'>
                        <Link to={item.to} search={item.search} aria-label={item.label} onClick={() => { if (isMobile) setOpenMobile(false) }} aria-current={active ? 'page' : undefined}>
                          {active && <motion.span layoutId='tactile-navigation' className='tactile-nav-surface' transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 380, damping: 29 }} aria-hidden='true' />}
                          <span className='tactile-nav-icon'><item.icon size={20} strokeWidth={1.7} /></span>
                          <span className='tactile-nav-copy group-data-[collapsible=icon]:hidden'><strong>{item.label}</strong><small>{item.subtitle}</small></span>
                          <span className='tactile-nav-number group-data-[collapsible=icon]:hidden'>{item.number}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className='tactile-sidebar-footer'>
          <div className='tactile-connection' role='status'><span className={connected ? 'is-connected' : ''} /><span className='group-data-[collapsible=icon]:hidden'>{connected ? '业务服务已连接' : '业务服务连接中'}</span></div>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset className='tactile-inset min-h-0 min-w-0 overflow-hidden'>
        <header className='tactile-topbar'>
          <SidebarTrigger aria-label='展开或收起导航' />
          <span className='tactile-breadcrumb-parent'>工作空间</span><ChevronRight size={13} className='tactile-breadcrumb-parent' />
          <span className='tactile-breadcrumb'>{current.label}{/\/(?:runs|recurring-runs)\//.test(pathname) ? ' / 批次详情' : ''}</span>
          <span className='tactile-preview-label'><Waves size={13} />触感工作台</span>
          <GlobalCommandMenu />
          <ThemeToggle />
          <span className='tactile-avatar' title='ThreadSnap 单用户工作空间'>TS</span>
        </header>
        <motion.main id='tactile-content' tabIndex={-1} key={pathname} initial={reduceMotion ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className='tactile-content'>
          <Outlet />
        </motion.main>
        <footer className='tactile-shell-footer'><span><Waves size={13} /> Tactile Digital / Deformable UI</span><span>独立批次 · 冻结快照</span></footer>
      </SidebarInset>
    </>
  )
}
