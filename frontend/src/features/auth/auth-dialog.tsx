import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Expand, Loader2, LogIn, LogOut, RefreshCw, ShieldCheck, Wifi, WifiOff } from 'lucide-react'
import { toast } from 'sonner'
import { api, errorMessage } from '@/lib/api'
import type { AuthTask } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'

type FrameMessage = {
  type: string
  data?: string
  width?: number
  height?: number
  url?: string
  message?: string
  code?: string
  http_status?: number
  page_status?: string
}

type PageStatus = 'idle' | 'starting' | 'loading' | 'ready' | 'validating' | 'failed' | 'completed'

const pageStatusNames: Record<PageStatus, string> = {
  idle: '等待启动',
  starting: '启动浏览器',
  loading: '加载平台页面',
  ready: '页面可操作',
  validating: '校验会话',
  failed: '页面加载失败',
  completed: '认证完成',
}

export function AuthDialog({
  open,
  onOpenChange,
  platformCode = 'dongchedi',
  platformName = '懂车帝',
  runId,
  freshOnOpen = false,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  platformCode?: string
  platformName?: string
  runId?: string
  freshOnOpen?: boolean
}) {
  const queryClient = useQueryClient()
  const socketRef = useRef<WebSocket | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const pointerFrameRef = useRef<number | undefined>(undefined)
  const pendingPointerRef = useRef<Record<string, unknown> | undefined>(undefined)
  const lastPointerRef = useRef({ x: 0, y: 0 })
  const [task, setTask] = useState<AuthTask | null>(null)
  const [frame, setFrame] = useState<string>()
  const [pageUrl, setPageUrl] = useState('')
  const [connection, setConnection] = useState<'connecting' | 'online' | 'offline'>('offline')
  const [pageStatus, setPageStatus] = useState<PageStatus>('idle')
  const [pageError, setPageError] = useState<{ code?: string; message: string; httpStatus?: number }>()
  const [validationFailed, setValidationFailed] = useState(false)
  const [remaining, setRemaining] = useState(0)
  const [browserSize, setBrowserSize] = useState({ width: 1280, height: 800 })

  const createTask = useCallback(async (fresh = false) => {
    setConnection('connecting')
    setPageStatus('starting')
    setPageError(undefined)
    setValidationFailed(false)
    setFrame(undefined)
    const next = await api<AuthTask>(`/platforms/${platformCode}/auth/tasks${fresh ? '?fresh=true' : ''}`, { method: 'POST' })
    setTask(next)
    return next
  }, [platformCode])

  const connect = useCallback((current: AuthTask) => {
    socketRef.current?.close()
    if (!current.ticket) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(
      `${protocol}//${location.host}${current.websocket_path}`,
      ['threadsnap-auth', `threadsnap-ticket.${current.ticket}`],
    )
    socketRef.current = socket
    setConnection('connecting')
    socket.onopen = () => { if (socketRef.current === socket) setConnection('online') }
    socket.onclose = () => { if (socketRef.current === socket) setConnection('offline') }
    socket.onerror = () => { if (socketRef.current === socket) setConnection('offline') }
    socket.onmessage = async (event) => {
      if (socketRef.current !== socket) return
      const message = JSON.parse(event.data) as FrameMessage
      if (message.type === 'browser_starting') {
        setPageStatus('starting')
        setPageError(undefined)
      } else if (message.type === 'ready') {
        setBrowserSize({ width: message.width ?? 1280, height: message.height ?? 800 })
        setPageUrl(message.url ?? '')
        setPageStatus('ready')
      } else if (message.type === 'frame' && message.data) {
        const source = `data:image/jpeg;base64,${message.data}`
        if (imageRef.current) imageRef.current.src = source
        else setFrame(source)
        setPageUrl(message.url ?? '')
        setPageStatus((current) => current === 'validating' ? current : 'ready')
      } else if (message.type === 'validating') {
        setPageStatus('validating')
      } else if (message.type === 'completed') {
        setPageStatus('completed')
        await queryClient.invalidateQueries()
        toast.success('平台认证成功', { description: message.message })
        onOpenChange(false)
      } else if (message.type === 'validation_failed') {
        setPageStatus('ready')
        setValidationFailed(true)
        toast.error('认证状态校验未通过', { description: message.message })
      } else if (message.type === 'page_failed' || message.type === 'error') {
        setPageStatus('failed')
        setPageError({ code: message.code, message: message.message ?? '平台认证页面加载失败。', httpStatus: message.http_status })
        setFrame(undefined)
      }
    }
  }, [onOpenChange, queryClient])

  const start = useCallback((fresh = freshOnOpen) => {
    createTask(fresh).then(connect).catch((error) => {
      setConnection('offline')
      setPageStatus('failed')
      setPageError({ message: errorMessage(error) })
      toast.error('认证窗口启动失败', { description: errorMessage(error) })
    })
  }, [connect, createTask, freshOnOpen])

  useEffect(() => {
    if (!open) return
    start()
    return () => {
      const socket = socketRef.current
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'close' }))
        window.setTimeout(() => {
          if (socket.readyState !== WebSocket.CLOSED) socket.close()
        }, 250)
      } else {
        socket?.close()
      }
      socketRef.current = null
      if (pointerFrameRef.current !== undefined) window.cancelAnimationFrame(pointerFrameRef.current)
      pointerFrameRef.current = undefined
      pendingPointerRef.current = undefined
      setFrame(undefined)
      setTask(null)
      setPageStatus('idle')
      setPageError(undefined)
      setValidationFailed(false)
    }
  }, [open, start])

  useEffect(() => {
    if (!task) return
    const update = () => setRemaining(Math.max(0, Math.floor((new Date(task.expires_at).getTime() - Date.now()) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [task])

  const endRun = useMutation({
    mutationFn: () => api(`/runs/${runId}/end-auth-wait`, { method: 'POST' }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['runs'] }); toast.success('本次等待已结束'); onOpenChange(false) },
    onError: (error) => toast.error('操作未完成', { description: errorMessage(error) }),
  })

  function send(command: Record<string, unknown>) {
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify(command))
  }

  function pointerCoordinates(event: React.PointerEvent<HTMLImageElement> | React.WheelEvent<HTMLImageElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = {
      x: ((event.clientX - bounds.left) / bounds.width) * browserSize.width,
      y: ((event.clientY - bounds.top) / bounds.height) * browserSize.height,
    }
    lastPointerRef.current = point
    return point
  }

  function pointerButton(button: number) {
    return ['left', 'middle', 'right', 'back', 'forward'][button] ?? 'none'
  }

  function modifiers(event: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) {
    return (event.altKey ? 1 : 0) | (event.ctrlKey ? 2 : 0) | (event.metaKey ? 4 : 0) | (event.shiftKey ? 8 : 0)
  }

  function pointerMove(event: React.PointerEvent<HTMLImageElement>) {
    if (pageStatus !== 'ready') return
    const point = pointerCoordinates(event)
    pendingPointerRef.current = {
      type: 'pointer_move',
      ...point,
      button: pointerButton(event.button),
      buttons: event.buttons,
      modifiers: modifiers(event),
    }
    if (pointerFrameRef.current !== undefined) return
    pointerFrameRef.current = window.requestAnimationFrame(() => {
      pointerFrameRef.current = undefined
      const command = pendingPointerRef.current
      pendingPointerRef.current = undefined
      if (command && (socketRef.current?.bufferedAmount ?? 0) < 64 * 1024) send(command)
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='flex h-[94vh] w-[96vw] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none'>
        <DialogHeader className='border-b bg-background/90 px-5 py-4 backdrop-blur'>
          <div className='flex flex-wrap items-center gap-3 pr-10'>
            <div className='grid size-10 place-items-center rounded-xl bg-primary/10 text-primary'><ShieldCheck className='size-5' /></div>
            <div className='min-w-0 flex-1'><DialogTitle>{platformName}平台认证</DialogTitle><DialogDescription className='mt-1 truncate'>{pageUrl || '正在连接服务器浏览器…'}</DialogDescription></div>
            <StatusBadge value={pageStatus} label={pageStatusNames[pageStatus]} />
            {task?.fresh_profile && <span className='rounded-full border border-primary/25 bg-primary/5 px-2 py-1 text-xs text-primary'>全新登录环境</span>}
            <div className='flex items-center gap-1.5 text-xs text-muted-foreground'>{connection === 'online' ? <Wifi className='size-4 text-emerald-500' /> : <WifiOff className='size-4 text-red-500' />}中继{connection === 'online' ? '已连接' : connection === 'connecting' ? '连接中' : '已断开'}</div>
            <div className='font-mono text-xs text-muted-foreground'>剩余 {String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}</div>
          </div>
        </DialogHeader>
        <div
          className='relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-[#080d1d] p-2 outline-none sm:p-4'
          tabIndex={0}
          aria-label='服务器浏览器操作区域'
          onKeyDown={(event) => {
            if (pageStatus !== 'ready') return
            event.preventDefault()
            if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) send({ type: 'type', text: event.key })
            else send({ type: 'key_down', key: event.key })
          }}
          onKeyUp={(event) => {
            if (pageStatus !== 'ready') return
            if (event.key.length > 1 || event.ctrlKey || event.metaKey || event.altKey) {
              event.preventDefault()
              send({ type: 'key_up', key: event.key })
            }
          }}
          onPaste={(event) => { if (pageStatus !== 'ready') return; event.preventDefault(); send({ type: 'type', text: event.clipboardData.getData('text') }) }}
        >
          {pageError ? (
            <Alert variant='destructive' className='max-w-xl border-red-400/40 bg-background/95 shadow-2xl'>
              <AlertCircle className='size-4' />
              <AlertTitle>平台页面加载失败</AlertTitle>
              <AlertDescription className='space-y-2'>
                <p>{pageError.message}</p>
                <p className='font-mono text-xs'>错误码：{pageError.code ?? 'AUTH_BROWSER_FAILED'}{pageError.httpStatus ? ` · HTTP ${pageError.httpStatus}` : ''}</p>
              </AlertDescription>
            </Alert>
          ) : frame ? <img
            ref={imageRef}
            src={frame}
            draggable={false}
            alt='服务器浏览器实时画面'
            className='max-h-full max-w-full touch-none cursor-default select-none rounded-md object-contain shadow-2xl ring-1 ring-white/10'
            onPointerMove={pointerMove}
            onPointerDown={(event) => {
              if (pageStatus !== 'ready') return
              event.preventDefault()
              event.currentTarget.setPointerCapture(event.pointerId)
              event.currentTarget.parentElement?.focus()
              send({ type: 'pointer_down', ...pointerCoordinates(event), button: pointerButton(event.button), buttons: event.buttons, modifiers: modifiers(event), click_count: 1 })
            }}
            onPointerUp={(event) => {
              if (pageStatus !== 'ready') return
              event.preventDefault()
              send({ type: 'pointer_up', ...pointerCoordinates(event), button: pointerButton(event.button), buttons: event.buttons, modifiers: modifiers(event), click_count: 1 })
              if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
            }}
            onPointerCancel={(event) => {
              if (pageStatus !== 'ready') return
              send({ type: 'pointer_up', ...lastPointerRef.current, button: pointerButton(event.button), buttons: 0, modifiers: modifiers(event), click_count: 0 })
            }}
            onWheel={(event) => {
              if (pageStatus !== 'ready') return
              event.preventDefault()
              send({ type: 'scroll', ...pointerCoordinates(event), dx: event.deltaX, dy: event.deltaY, buttons: 0, modifiers: modifiers(event) })
            }}
            onContextMenu={(event) => event.preventDefault()}
          /> : <div className='flex flex-col items-center gap-3 text-slate-300'><Loader2 className='size-8 animate-spin text-cyan-400' /><span className='text-sm'>{pageStatusNames[pageStatus]}</span></div>}
          <div className='pointer-events-none absolute right-4 bottom-4 flex items-center gap-2 rounded-full bg-black/55 px-3 py-1.5 text-[11px] text-slate-300 backdrop-blur'><Expand className='size-3.5' />1280 × 800 交互画布</div>
        </div>
        <div className='flex flex-wrap items-center justify-between gap-3 border-t bg-background px-5 py-3'>
          <div className={`text-xs ${validationFailed ? 'font-medium text-amber-700 dark:text-amber-300' : 'text-muted-foreground'}`}>{validationFailed ? '当前旧登录状态未通过采集校验，可使用全新登录环境重新登录。' : task?.fresh_profile && freshOnOpen ? '检测到批次中途认证失效，已启动全新登录环境，请重新完成平台登录。' : '画面支持悬停、点击、拖动、滚动和键盘输入；剪贴板文本会发送到当前页面焦点。'}</div>
          <div className='flex items-center gap-2'>
            {!task?.fresh_profile && <Button variant={validationFailed ? 'default' : 'outline'} disabled={pageStatus === 'starting' || pageStatus === 'loading' || pageStatus === 'validating'} onClick={() => start(true)}><LogIn className='size-4' />使用全新登录环境</Button>}
            <Button variant='outline' onClick={() => pageStatus === 'failed' || !task?.ticket ? start() : connect(task)}><RefreshCw className='size-4' />{pageStatus === 'failed' ? '重新创建认证浏览器' : '重新连接'}</Button>
            <Button variant='outline' onClick={() => onOpenChange(false)}>关闭窗口</Button>
            {runId && <AlertDialog><AlertDialogTrigger asChild><Button variant='destructive' disabled={endRun.isPending}><LogOut className='size-4' />结束本次提取</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>结束本次提取？</AlertDialogTitle><AlertDialogDescription>已有结果将保留，批次按实际结果结束并释放平台队列。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => endRun.mutate()}>确认结束</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}
            <Button disabled={pageStatus !== 'ready'} onClick={() => send({ type: 'finish' })}><ShieldCheck className='size-4' />完成并校验</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
