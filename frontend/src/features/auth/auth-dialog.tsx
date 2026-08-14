import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Expand, Loader2, LogOut, RefreshCw, ShieldCheck, Wifi, WifiOff } from 'lucide-react'
import { toast } from 'sonner'
import { api, errorMessage } from '@/lib/api'
import type { AuthTask } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { StatusBadge } from '@/components/status-badge'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'

type FrameMessage = { type: string; data?: string; width?: number; height?: number; url?: string; message?: string }

export function AuthDialog({
  open,
  onOpenChange,
  platformCode = 'dongchedi',
  platformName = '懂车帝',
  runId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  platformCode?: string
  platformName?: string
  runId?: string
}) {
  const queryClient = useQueryClient()
  const socketRef = useRef<WebSocket | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const [task, setTask] = useState<AuthTask | null>(null)
  const [frame, setFrame] = useState<string>()
  const [pageUrl, setPageUrl] = useState('')
  const [connection, setConnection] = useState<'connecting' | 'online' | 'offline'>('offline')
  const [remaining, setRemaining] = useState(0)
  const [browserSize, setBrowserSize] = useState({ width: 1280, height: 800 })

  const createTask = useCallback(async () => {
    setConnection('connecting')
    const next = await api<AuthTask>(`/platforms/${platformCode}/auth/tasks`, { method: 'POST' })
    setTask(next)
    return next
  }, [platformCode])

  const connect = useCallback((current: AuthTask) => {
    socketRef.current?.close()
    if (!current.ticket) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${location.host}${current.websocket_path}?ticket=${encodeURIComponent(current.ticket)}`)
    socketRef.current = socket
    setConnection('connecting')
    socket.onopen = () => setConnection('online')
    socket.onclose = () => setConnection('offline')
    socket.onerror = () => setConnection('offline')
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as FrameMessage
      if (message.type === 'ready') {
        setBrowserSize({ width: message.width ?? 1280, height: message.height ?? 800 })
        setPageUrl(message.url ?? '')
      } else if (message.type === 'frame' && message.data) {
        setFrame(`data:image/jpeg;base64,${message.data}`)
        setPageUrl(message.url ?? '')
      } else if (message.type === 'completed') {
        toast.success('平台认证成功', { description: message.message })
        queryClient.invalidateQueries()
        onOpenChange(false)
      } else if (message.type === 'validation_failed' || message.type === 'error') {
        toast.error('认证状态校验未通过', { description: message.message })
      }
    }
  }, [onOpenChange, queryClient])

  useEffect(() => {
    if (!open) return
    createTask().then(connect).catch((error) => {
      setConnection('offline')
      toast.error('认证窗口启动失败', { description: errorMessage(error) })
    })
    return () => {
      socketRef.current?.send(JSON.stringify({ type: 'close' }))
      socketRef.current?.close()
      socketRef.current = null
      setFrame(undefined)
      setTask(null)
    }
  }, [open, createTask, connect])

  useEffect(() => {
    if (!task) return
    const update = () => setRemaining(Math.max(0, Math.floor((new Date(task.expires_at).getTime() - Date.now()) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [task])

  const endRun = useMutation({
    mutationFn: () => api(`/runs/${runId}/end-auth-wait`, { method: 'POST' }),
    onSuccess: () => { toast.success('本次等待已结束'); onOpenChange(false); queryClient.invalidateQueries({ queryKey: ['runs'] }) },
    onError: (error) => toast.error('操作未完成', { description: errorMessage(error) }),
  })

  function send(command: Record<string, unknown>) {
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify(command))
  }

  function click(event: React.MouseEvent<HTMLImageElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    send({ type: 'click', x: ((event.clientX - bounds.left) / bounds.width) * browserSize.width, y: ((event.clientY - bounds.top) / bounds.height) * browserSize.height })
    event.currentTarget.parentElement?.focus()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='flex h-[94vh] w-[96vw] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none'>
        <DialogHeader className='border-b bg-background/90 px-5 py-4 backdrop-blur'>
          <div className='flex flex-wrap items-center gap-3 pr-10'>
            <div className='grid size-10 place-items-center rounded-xl bg-primary/10 text-primary'><ShieldCheck className='size-5' /></div>
            <div className='min-w-0 flex-1'><DialogTitle>{platformName}平台认证</DialogTitle><DialogDescription className='mt-1 truncate'>{pageUrl || '正在连接服务器浏览器…'}</DialogDescription></div>
            <StatusBadge value={task?.status ?? 'queued'} label={task?.status_name ?? '准备中'} />
            <div className='flex items-center gap-1.5 text-xs text-muted-foreground'>{connection === 'online' ? <Wifi className='size-4 text-emerald-500' /> : <WifiOff className='size-4 text-red-500' />}{connection === 'online' ? '已连接' : connection === 'connecting' ? '连接中' : '已断开'}</div>
            <div className='font-mono text-xs text-muted-foreground'>剩余 {String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}</div>
          </div>
        </DialogHeader>
        <div
          className='relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-[#080d1d] p-2 outline-none sm:p-4'
          tabIndex={0}
          aria-label='服务器浏览器操作区域'
          onKeyDown={(event) => {
            if (event.ctrlKey || event.metaKey || event.altKey) return
            event.preventDefault()
            if (event.key.length === 1) send({ type: 'type', text: event.key })
            else send({ type: 'key', key: event.key })
          }}
          onPaste={(event) => { event.preventDefault(); send({ type: 'type', text: event.clipboardData.getData('text') }) }}
          onWheel={(event) => { event.preventDefault(); send({ type: 'scroll', dx: event.deltaX, dy: event.deltaY }) }}
        >
          {frame ? <img ref={imageRef} src={frame} onClick={click} draggable={false} alt='服务器浏览器实时画面' className='max-h-full max-w-full cursor-default select-none rounded-md object-contain shadow-2xl ring-1 ring-white/10' /> : <div className='flex flex-col items-center gap-3 text-slate-300'><Loader2 className='size-8 animate-spin text-cyan-400' /><span className='text-sm'>正在加载服务器浏览器画面</span></div>}
          <div className='pointer-events-none absolute right-4 bottom-4 flex items-center gap-2 rounded-full bg-black/55 px-3 py-1.5 text-[11px] text-slate-300 backdrop-blur'><Expand className='size-3.5' />1280 × 800 交互画布</div>
        </div>
        <div className='flex flex-wrap items-center justify-between gap-3 border-t bg-background px-5 py-3'>
          <div className='text-xs text-muted-foreground'>点击画面后可直接输入；剪贴板文本会发送到当前页面焦点。</div>
          <div className='flex items-center gap-2'>
            <Button variant='outline' onClick={() => task ? connect(task) : createTask().then(connect)}><RefreshCw className='size-4' />重新连接</Button>
            <Button variant='outline' onClick={() => onOpenChange(false)}>关闭窗口</Button>
            {runId && <AlertDialog><AlertDialogTrigger asChild><Button variant='destructive' disabled={endRun.isPending}><LogOut className='size-4' />结束本次提取</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>结束本次提取？</AlertDialogTitle><AlertDialogDescription>已有结果将保留，批次按实际结果结束并释放平台队列。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => endRun.mutate()}>确认结束</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}
            <Button onClick={() => send({ type: 'finish' })}><ShieldCheck className='size-4' />完成并校验</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
