import { Fragment, useEffect, useMemo, useState } from 'react'
import { Dialog, DialogPanel, DialogTitle, Transition, TransitionChild } from '@headlessui/react'
import { useNavigate } from '@tanstack/react-router'
import { Command, FileSearch, LayoutList, Repeat2, Search, Settings2, Sparkles, X } from 'lucide-react'
import { useReducedMotion } from 'motion/react'

const commands = [
  { id: 'runs', label: '任务管理', description: '打开批次与队列工作台', icon: LayoutList, to: '/runs', search: {} },
  { id: 'recurring', label: '循环计划', description: '查看周期触发的独立批次', icon: Repeat2, to: '/recurring-runs', search: {} },
  { id: 'reputation', label: '口碑巡检', description: '查看排名和页面证据', icon: FileSearch, to: '/reputation', search: { tab: 'runs' } },
  { id: 'config', label: '配置中心', description: '维护规则、计划与来源', icon: Settings2, to: '/config', search: { tab: 'rules' } },
] as const

export function GlobalCommandMenu() {
  const navigate = useNavigate()
  const reduceMotion = useReducedMotion()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [instantTransition, setInstantTransition] = useState(false)
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return commands
    return commands.filter((item) => `${item.label} ${item.description}`.toLocaleLowerCase().includes(normalized))
  }, [query])

  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setInstantTransition(true)
        setOpen(true)
      }
      if (event.key === 'Escape' && open) {
        setInstantTransition(true)
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  function close(instant = false) {
    if (instant) setInstantTransition(true)
    setOpen(false)
    setQuery('')
    setSelectedIndex(0)
  }

  function go(item: (typeof commands)[number], instant = false) {
    navigate({ to: item.to as never, search: item.search as never })
    close(instant)
  }

  const enter = reduceMotion || instantTransition ? '' : 'ease-[cubic-bezier(0.16,1,0.3,1)] duration-200'
  const leave = reduceMotion || instantTransition ? '' : 'ease-[cubic-bezier(0.16,1,0.3,1)] duration-150'

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setSelectedIndex((index) => filtered.length ? (index + 1) % filtered.length : 0)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setSelectedIndex((index) => filtered.length ? (index - 1 + filtered.length) % filtered.length : 0)
    } else if (event.key === 'Enter' && filtered[selectedIndex]) {
      event.preventDefault()
      go(filtered[selectedIndex], true)
    }
  }

  return (
    <>
      <button type='button' className='workspace-topbar-search hidden min-w-56 items-center gap-2 lg:flex' onClick={() => setOpen(true)} aria-label='打开工作区入口搜索'>
        <Search className='size-3.5' />
        <span>搜索工作区入口</span>
        <kbd>⌘K</kbd>
      </button>
      <button type='button' className='workspace-topbar-search-trigger lg:hidden' onClick={() => setOpen(true)} aria-label='打开工作区入口搜索'>
        <Search className='size-4' />
      </button>

      <Transition show={open} as={Fragment} afterEnter={() => setInstantTransition(false)} afterLeave={() => { setInstantTransition(false); setQuery('') }}>
        <Dialog onClose={() => close(true)} className='relative z-[80]'>
          <TransitionChild as={Fragment} enter={enter} enterFrom='opacity-0' enterTo='opacity-100' leave={leave} leaveFrom='opacity-100' leaveTo='opacity-0'>
            <div className='fixed inset-0 bg-slate-950/65 backdrop-blur-sm' aria-hidden='true' />
          </TransitionChild>
          <div className='fixed inset-0 flex items-start justify-center p-4 pt-[12vh] sm:p-8 sm:pt-[16vh]'>
            <TransitionChild as={Fragment} enter={enter} enterFrom='translate-y-2 scale-[0.98] opacity-0' enterTo='translate-y-0 scale-100 opacity-100' leave={leave} leaveFrom='translate-y-0 scale-100 opacity-100' leaveTo='translate-y-2 scale-[0.98] opacity-0'>
              <DialogPanel className='workspace-command-panel w-full max-w-xl overflow-hidden' aria-label='工作区入口搜索面板'>
                <div className='workspace-command-panel__header'>
                  <DialogTitle className='flex items-center gap-2 text-sm font-semibold'><Sparkles className='size-4 text-emerald-400' />全局搜索</DialogTitle>
                  <button type='button' className='workspace-command-panel__close' onClick={() => close()} aria-label='关闭全局搜索'><X className='size-4' /></button>
                </div>
                <div className='workspace-command-panel__input-wrap'>
                  <Command className='size-4 text-muted-foreground' />
                  <input autoFocus role='combobox' aria-controls='workspace-command-results' aria-expanded='true' value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleInputKeyDown} placeholder='搜索任务、计划、巡检或配置' aria-label='搜索任务、计划、巡检或配置' aria-activedescendant={filtered[selectedIndex] ? `command-${filtered[selectedIndex].id}` : undefined} />
                  <kbd>ESC</kbd>
                </div>
                <div id='workspace-command-results' className='workspace-command-list' role='listbox' aria-label='导航结果'>
                  {filtered.length ? filtered.map((item, index) => {
                    const Icon = item.icon
                    return <button key={item.id} id={`command-${item.id}`} type='button' className={`workspace-command-item ${selectedIndex === index ? 'is-active' : ''}`} onMouseEnter={() => setSelectedIndex(index)} onClick={() => go(item)} role='option' aria-selected={selectedIndex === index}>
                      <span className='workspace-command-item__icon'><Icon className='size-4' /></span>
                      <span><strong>{item.label}</strong><small>{item.description}</small></span>
                      <span className='workspace-command-item__arrow'>↵</span>
                    </button>
                  }) : <div className='workspace-command-empty'>没有匹配的工作区入口</div>}
                </div>
                <div className='workspace-command-panel__footer'><span><kbd>↑↓</kbd>选择</span><span><kbd>Enter</kbd>打开</span><span><kbd>Esc</kbd>关闭</span></div>
              </DialogPanel>
            </TransitionChild>
          </div>
        </Dialog>
      </Transition>
    </>
  )
}
