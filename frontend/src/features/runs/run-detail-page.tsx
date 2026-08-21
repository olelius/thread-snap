import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ArrowLeft, BrainCircuit, CircleAlert, CircleCheckBig, CircleStop, ChevronLeft, ChevronRight, Copy, Download, ExternalLink, Gauge, KeyRound, Layers3, ListTree, LoaderCircle, PencilLine, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { AuthDialog } from '@/features/auth/auth-dialog'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { api, errorMessage, formatDate, platformName, queryString } from '@/lib/api'
import type { AnalysisStatus, PageResult, Post, PostNavigation, Run, RunTask, SentimentResult, Template } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

type SearchState = { page?: number; pageSize?: 20 | 50 | 100; title?: string; circle?: string; visibility?: 'visible' | 'hidden' | 'unknown'; sentiment?: SentimentResult; analysisStatus?: AnalysisStatus; sort?: 'source' | 'published_at' | 'reply_count' | 'like_count'; direction?: 'asc' | 'desc'; post?: string }
type PostSwitch = { id: string; direction: 'previous' | 'next' }

export function RunDetailPage() {
  const { runId } = useParams({ strict: false }) as { runId: string }
  const rawSearch = useSearch({ strict: false }) as SearchState
  const navigate = useNavigate({ from: '/runs/$runId' })
  const client = useQueryClient()
  const search = {
    ...rawSearch,
    page: rawSearch.page ?? 1,
    pageSize: rawSearch.pageSize ?? 50,
    sort: rawSearch.sort ?? 'source',
    direction: rawSearch.direction ?? 'asc',
  }
  const [authOpen, setAuthOpen] = useState(false)
  const [tasksOpen, setTasksOpen] = useState(false)
  const [manualCopy, setManualCopy] = useState<string>()
  const [manualCorrectionOpen, setManualCorrectionOpen] = useState(false)
  const [postSwitch, setPostSwitch] = useState<PostSwitch>()
  const [selectionRevealPostId, setSelectionRevealPostId] = useState<string>()
  const [lastViewedPostId, setLastViewedPostId] = useState<string>()
  const reduceMotion = useReducedMotion()
  const detailBackgroundScroll = useRef(0)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const currentDetailPostId = useRef<string | undefined>(undefined)
  const closeHighlightTimer = useRef<number | undefined>(undefined)
  const closeFocusFrame = useRef<number | undefined>(undefined)
  const debouncedTitle = useDebouncedValue(search.title)
  const debouncedCircle = useDebouncedValue(search.circle)
  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api<Run>(`/runs/${runId}`),
    refetchInterval: (current) => isActiveRun(current.state.data) ? 3_000 : 60_000,
  })
  const postQueryValues = { title: debouncedTitle, circle: debouncedCircle, visibility: search.visibility, sentiment_result: search.sentiment, analysis_status: search.analysisStatus, sort_by: search.sort, sort_direction: search.direction }
  const posts = useQuery({
    queryKey: ['posts', runId, { page: search.page, pageSize: search.pageSize, ...postQueryValues }],
    queryFn: () => api<PageResult<Post>>(`/runs/${runId}/posts${queryString({ offset: ((search.page ?? 1) - 1) * (search.pageSize ?? 50), limit: search.pageSize, ...postQueryValues })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (current) => current.state.data?.items.some((post) => ['analysis_queued', 'analysis_running'].includes(post.analysis_status ?? '')) ? 3_000 : false,
  })
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates') })
  const detail = useQuery({
    queryKey: ['post', runId, search.post],
    queryFn: () => api<Post>(`/runs/${runId}/posts/${search.post}`),
    enabled: Boolean(search.post),
    placeholderData: keepPreviousData,
    refetchInterval: (current) => ['analysis_queued', 'analysis_running'].includes(current.state.data?.analysis_status ?? '') ? 3_000 : false,
  })
  const navigation = useQuery({
    queryKey: ['post-navigation', runId, search.post, postQueryValues],
    queryFn: () => api<PostNavigation>(`/runs/${runId}/posts/${search.post}/navigation${queryString(postQueryValues)}`),
    enabled: Boolean(search.post),
    placeholderData: keepPreviousData,
  })

  useEffect(() => {
    if (!postSwitch || search.post !== postSwitch.id) return
    if (!detail.isFetching && !navigation.isFetching) setPostSwitch(undefined)
  }, [detail.isFetching, navigation.isFetching, postSwitch, search.post])

  useEffect(() => {
    if (!selectionRevealPostId || search.post !== selectionRevealPostId) return
    const row = document.getElementById(`post-row-${selectionRevealPostId}`)
    if (!row) return
    const frame = window.requestAnimationFrame(() => {
      row.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' })
      setSelectionRevealPostId(undefined)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [posts.data?.items, reduceMotion, search.post, selectionRevealPostId])

  useEffect(() => {
    if (!search.post) return
    currentDetailPostId.current = search.post
    window.clearTimeout(closeHighlightTimer.current)
    setLastViewedPostId(undefined)
  }, [search.post])

  useEffect(() => () => {
    window.clearTimeout(closeHighlightTimer.current)
    if (closeFocusFrame.current !== undefined) window.cancelAnimationFrame(closeFocusFrame.current)
  }, [])

  function patch(values: Partial<SearchState>, options?: { resetScroll?: boolean }) {
    navigate({
      to: '/runs/$runId',
      params: { runId },
      search: (previous) => ({ ...previous, ...values }),
      replace: true,
      resetScroll: options?.resetScroll ?? false,
    })
  }

  const retry = useMutation({ mutationFn: () => api<Run>(`/runs/${runId}/retry`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }), onSuccess: async (value) => { await client.invalidateQueries({ queryKey: ['runs'] }); toast.success('失败项已重新提交', { description: `新批次 ${value.number}` }) }, onError: (error) => toast.error('重新提取失败', { description: errorMessage(error) }) })
  const exportRun = useMutation({ mutationFn: (templateVersionId: string) => api<{ id: string }>(`/runs/${runId}/exports`, { method: 'POST', body: JSON.stringify({ template_version_id: templateVersionId }) }), onSuccess: (value) => { window.open(`/api/v1/exports/${value.id}/download`, '_blank', 'noopener'); toast.success('Excel 导出已生成') }, onError: (error) => toast.error('导出失败', { description: errorMessage(error) }) })
  const endAuthWait = useMutation({ mutationFn: () => api<Run>(`/runs/${runId}/end-auth-wait`, { method: 'POST' }), onSuccess: async (value) => { client.setQueryData(['run', runId], value); await client.invalidateQueries({ queryKey: ['runs'] }); toast.success('本次提取已结束') }, onError: (error) => toast.error('结束提取失败', { description: errorMessage(error) }) })
  const deleteRun = useMutation({ mutationFn: () => api<{ message: string }>(`/runs/${runId}`, { method: 'DELETE' }), onSuccess: async () => { client.removeQueries({ queryKey: ['run', runId] }); await client.invalidateQueries({ queryKey: ['runs'] }); toast.success('批次及关联快照已永久删除'); navigate({ to: '/runs', search: emptyRunsSearch }) }, onError: (error) => toast.error('删除批次失败', { description: errorMessage(error) }) })

  async function copyText(text: string) {
    try { await navigator.clipboard.writeText(text); toast.success('已复制到剪贴板') }
    catch { setManualCopy(text) }
  }
  async function copyAll() {
    try {
      const result = await api<{ urls: string[]; total: number }>(`/runs/${runId}/posts/urls${queryString(postQueryValues)}`)
      await copyText(result.urls.join('\n'))
    } catch (error) { toast.error('复制准备失败', { description: errorMessage(error) }) }
  }

  function openPost(postId: string, trigger: HTMLElement) {
    window.clearTimeout(closeHighlightTimer.current)
    setLastViewedPostId(undefined)
    detailBackgroundScroll.current = window.scrollY
    detailTrigger.current = trigger
    currentDetailPostId.current = postId
    patch({ post: postId }, { resetScroll: false })
  }

  function handleDetailOpenAutoFocus(event: Event) {
    event.preventDefault()
    if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus({ preventScroll: true })
    window.scrollTo(window.scrollX, detailBackgroundScroll.current)
  }

  function handleDetailCloseAutoFocus(event: Event) {
    event.preventDefault()
    if (closeFocusFrame.current !== undefined) window.cancelAnimationFrame(closeFocusFrame.current)
    closeFocusFrame.current = window.requestAnimationFrame(() => {
      const row = currentDetailPostId.current ? document.getElementById(`post-row-${currentDetailPostId.current}`) : undefined
      const currentTrigger = row?.querySelector<HTMLElement>('[data-post-detail-trigger="true"]')
      const focusTarget = currentTrigger ?? detailTrigger.current
      focusTarget?.focus({ preventScroll: true })
      closeFocusFrame.current = undefined
    })
  }

  function closePostDetail() {
    const postId = currentDetailPostId.current ?? search.post
    if (postId) {
      window.clearTimeout(closeHighlightTimer.current)
      setLastViewedPostId(postId)
      closeHighlightTimer.current = window.setTimeout(() => {
        setLastViewedPostId((current) => current === postId ? undefined : current)
      }, reduceMotion ? 1200 : 1800)
    }
    setPostSwitch(undefined)
    setSelectionRevealPostId(undefined)
    patch({ post: undefined }, { resetScroll: false })
  }
  function moveToPost(postId: string | undefined, position: number, direction: PostSwitch['direction']) {
    if (!postId || postSwitch) return
    window.clearTimeout(closeHighlightTimer.current)
    setLastViewedPostId(undefined)
    setPostSwitch({ id: postId, direction })
    setSelectionRevealPostId(postId)
    currentDetailPostId.current = postId
    const page = Math.ceil(position / (search.pageSize ?? 50))
    patch({ post: postId, page }, { resetScroll: false })
  }

  const totalPages = Math.max(1, Math.ceil((posts.data?.total ?? 0) / (search.pageSize ?? 50)))
  const canRetry = run.data?.status === 'failed' || run.data?.status === 'partial_success'
  const canDelete = ['success', 'partial_success', 'failed'].includes(run.data?.status ?? '')
  const inputModeName = run.data?.input_mode === 'url_list' ? 'URL 清单' : '圈子发现'
  const selectionTransition = reduceMotion ? { duration: 0 } : { type: 'spring' as const, stiffness: 430, damping: 34, mass: 0.55 }
  const viewLabelTransition = reduceMotion ? { duration: 0 } : { duration: 0.18, ease: [0.2, 0, 0, 1] as const }

  return (
    <div className='flex h-full min-h-0 flex-col gap-4 overflow-y-auto xl:overflow-hidden'>
      <div className='shrink-0 space-y-4'>
        <PageHeader
          eyebrow={<Button variant='ghost' size='sm' className='-ml-2 h-7 px-2 text-xs' onClick={() => navigate({ to: '/runs', search: emptyRunsSearch })}><ArrowLeft className='size-3.5' />返回提取列表</Button>}
          title={run.data ? `批次 ${run.data.number}` : '批次链接详情'}
          description='结果按原始来源位置稳定合并；搜索、筛选、排序和分页均由后端对完整结果集执行。'
          actions={<>
            <Button variant='outline' size='sm' onClick={() => { run.refetch(); posts.refetch() }}><RefreshCw className={`size-4 ${run.isFetching || posts.isFetching ? 'animate-spin' : ''}`} />刷新</Button>
            {run.data?.tasks?.length ? <Button variant='outline' size='sm' onClick={() => setTasksOpen(true)}><ListTree className='size-4' />来源任务 <span className='text-xs text-muted-foreground'>{run.data.tasks.length}</span></Button> : null}
            {run.data?.status === 'waiting_for_auth' && <><Button variant='outline' size='sm' onClick={() => setAuthOpen(true)}><KeyRound className='size-4' />去认证</Button><AlertDialog><AlertDialogTrigger asChild><Button variant='outline' size='sm'><CircleStop className='size-4' />结束本次提取</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>结束本次提取？</AlertDialogTitle><AlertDialogDescription>已有结果将保留，批次按实际结果结束并释放平台队列；之后仍可重新提取失败项。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => endAuthWait.mutate()}>确认结束</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></>}
            {canRetry && <AlertDialog><AlertDialogTrigger asChild><Button variant='outline' size='sm'>重新提取失败项</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>重新提取失败项？</AlertDialogTitle><AlertDialogDescription>系统会保留原批次快照，只把失败 URL 创建为关联补提批次。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => retry.mutate()}>确认重新提取</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}
            {canDelete && <AlertDialog><AlertDialogTrigger asChild><Button variant='ghost' size='sm' className='text-destructive hover:text-destructive'><Trash2 className='size-4' />永久删除</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>永久删除该批次？</AlertDialogTitle><AlertDialogDescription>批次、帖子快照、一级评论和已生成导出记录都会一并删除，此操作不可撤回。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => deleteRun.mutate()}>确认永久删除</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}
          </>}
        />
      {run.isLoading ? <Skeleton className='h-20 rounded-xl' /> : run.data && <div className='grid gap-2 sm:grid-cols-2 xl:grid-cols-5'>{[
        ['状态', <StatusBadge key='status' value={run.data.status} label={run.data.status_name} />],
        ['触发方式', `${run.data.trigger_type_name} · ${inputModeName}`],
        ['结果进度', `${run.data.completed_count} / ${run.data.planned_count}`],
        ['失败项', String(run.data.failed_count)],
        ['创建时间', formatDate(run.data.created_at)],
      ].map(([label, value]) => <Card key={String(label)} className='border-border/70 bg-card/88 py-0'><CardContent className='p-3'><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-1 text-sm font-semibold'>{value}</div></CardContent></Card>)}</div>}
      {run.data?.waiting_reason && <Alert><KeyRound className='size-4' /><AlertTitle>等待平台认证</AlertTitle><AlertDescription>{run.data.waiting_reason}</AlertDescription></Alert>}
      {run.data?.error_message && <Alert variant='destructive'><AlertTitle>批次错误</AlertTitle><AlertDescription>{run.data.error_message}</AlertDescription></Alert>}
        <Card className='border-border/70 bg-card/88 py-0'><CardContent className='grid gap-2 p-3 [&>[data-slot=select-trigger]]:w-full [&>[data-slot=select-trigger]]:min-w-0 [&>[data-slot=select-trigger]]:gap-1 [&>[data-slot=select-trigger]]:px-2 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-[minmax(180px,1fr)_135px_125px_130px_130px_100px_88px_auto] [@media(min-width:2000px)]:grid-cols-[minmax(180px,360px)_135px_125px_130px_130px_100px_88px_minmax(0,1fr)_auto]'><Input placeholder='搜索帖子标题' aria-label='搜索帖子标题' value={search.title ?? ''} onChange={(event) => patch({ title: event.target.value || undefined, page: 1 })} /><Input placeholder='搜索圈子' aria-label='搜索圈子' value={search.circle ?? ''} onChange={(event) => patch({ circle: event.target.value || undefined, page: 1 })} /><Select value={search.visibility ?? 'all'} onValueChange={(value) => patch({ visibility: value === 'all' ? undefined : value as SearchState['visibility'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部可见状态</SelectItem><SelectItem value='visible'>可见</SelectItem><SelectItem value='hidden'>不可见</SelectItem><SelectItem value='unknown'>未知</SelectItem></SelectContent></Select><Select value={search.sentiment ?? 'all'} onValueChange={(value) => patch({ sentiment: value === 'all' ? undefined : value as SentimentResult, page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部舆情结果</SelectItem><SelectItem value='negative'>负面</SelectItem><SelectItem value='non_negative'>非负面</SelectItem><SelectItem value='unrelated'>不相关</SelectItem></SelectContent></Select><Select value={search.analysisStatus ?? 'all'} onValueChange={(value) => patch({ analysisStatus: value === 'all' ? undefined : value as AnalysisStatus, page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部分析状态</SelectItem>{Object.entries(analysisStatusNames).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select><Select value={search.sort} onValueChange={(value) => patch({ sort: value as SearchState['sort'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='source'>来源顺序</SelectItem><SelectItem value='published_at'>发布时间</SelectItem><SelectItem value='reply_count'>评论数</SelectItem><SelectItem value='like_count'>点赞数</SelectItem></SelectContent></Select><Select value={search.direction} onValueChange={(value) => patch({ direction: value as SearchState['direction'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='asc'>正序</SelectItem><SelectItem value='desc'>倒序</SelectItem></SelectContent></Select><div className='flex min-w-0 items-center justify-end gap-2 [@media(min-width:2000px)]:col-start-9'><Button className='shrink-0' variant='outline' onClick={copyAll}><Copy className='size-4' />复制全部</Button><Select onValueChange={(value) => exportRun.mutate(value)} disabled={!templates.data?.length || exportRun.isPending}><SelectTrigger className='w-36'><Download className='size-4' /><SelectValue placeholder={templates.data?.length ? '导出 Excel' : '暂无模板'} /></SelectTrigger><SelectContent>{templates.data?.map((item) => item.versions[0] && <SelectItem key={item.versions[0].version_id} value={item.versions[0].version_id}>{item.name}</SelectItem>)}</SelectContent></Select></div></CardContent></Card>
      </div>
      <div className='min-h-[360px] flex-1 xl:min-h-0'>
        <div className='flex h-[min(65svh,640px)] min-h-[360px] flex-col overflow-hidden rounded-xl border border-border/70 bg-card/90 xl:h-full xl:min-h-0'>
        <div className='min-h-0 flex-1 overflow-auto' data-list-viewport='run-posts'>
          <Table className='min-w-[1050px]'>
            <TableHeader><TableRow className='bg-muted/35'><TableHead className='w-16 text-center'>序号</TableHead><TableHead>标题</TableHead><TableHead>来源</TableHead><TableHead>作者</TableHead><TableHead>发布时间</TableHead><TableHead>可见状态</TableHead><TableHead>舆情结果</TableHead><TableHead className='text-right'>评论数</TableHead><TableHead className='text-right'>点赞数</TableHead><TableHead className='text-right'>操作</TableHead></TableRow></TableHeader>
            <TableBody>
              {posts.isLoading ? Array.from({ length: 6 }).map((_, index) => <TableRow key={index}>{Array.from({ length: 10 }).map((__, cell) => <TableCell key={cell}><Skeleton className='h-6 w-full' /></TableCell>)}</TableRow>) : posts.data?.items.length ? posts.data.items.map((post, index) => {
                const isCurrentPost = post.id === search.post
                const isLastViewedPost = !search.post && post.id === lastViewedPostId
                const isHighlightedPost = isCurrentPost || isLastViewedPost
                return <TableRow key={post.id} id={`post-row-${post.id}`} aria-current={isCurrentPost ? 'true' : undefined} className={cn('transition-[background-color,box-shadow] duration-200', isHighlightedPost && 'post-row-active', isLastViewedPost && 'post-row-dismissed')}>
                  <TableCell className='w-16 text-center tabular-nums text-muted-foreground'>{((search.page ?? 1) - 1) * (search.pageSize ?? 50) + index + 1}</TableCell><TableCell className='relative max-w-80'>
                    {isHighlightedPost && <motion.span layoutId='post-row-selection-trail' aria-hidden className='post-row-selection-trail absolute inset-y-1 left-0 w-1 rounded-full' transition={selectionTransition} />}
                    <motion.a
                      href={post.url}
                      target='_blank'
                      rel='noreferrer'
                      className={cn('relative flex min-w-0 items-center font-medium hover:text-primary hover:underline', isHighlightedPost && 'text-primary')}
                      animate={{ paddingLeft: isHighlightedPost ? 12 : 0 }}
                      transition={viewLabelTransition}
                    >
                      <AnimatePresence initial={false}>
                        {isHighlightedPost && <motion.span
                          key='post-view-state'
                          className='inline-flex shrink-0 overflow-hidden'
                          initial={reduceMotion ? false : { width: 0, marginRight: 0, x: -6, opacity: 0.35 }}
                          animate={{ width: 'auto', marginRight: 6, x: 0, opacity: 1 }}
                          exit={reduceMotion ? { width: 0, marginRight: 0 } : { width: 0, marginRight: 0, x: -6, opacity: 0.35 }}
                          transition={viewLabelTransition}
                          data-post-view-label={isCurrentPost ? 'current' : 'recent'}
                        >
                          <span className='whitespace-nowrap rounded-full border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium leading-none text-primary'>
                            {isCurrentPost ? '当前查看' : '刚刚查看'}
                          </span>
                        </motion.span>}
                      </AnimatePresence>
                      <span className='min-w-0 truncate'>{post.title || '无标题'}</span><ExternalLink className='ml-1.5 size-3 shrink-0' />
                    </motion.a>
                  </TableCell><TableCell><div className='flex min-w-0 items-center gap-1.5'><span className='truncate'>{post.source_name || post.circle_name || '—'}</span>{post.list_order_name && <Badge variant='outline' className='h-5 shrink-0 px-1.5 text-[11px] font-normal'>{post.list_order_name}</Badge>}</div></TableCell><TableCell>{post.author || '—'}</TableCell><TableCell className='whitespace-nowrap'>{formatDate(post.published_at)}</TableCell><TableCell><StatusBadge value={post.visibility} label={{ visible: '可见', hidden: '不可见', unknown: '未知' }[post.visibility]} /></TableCell><TableCell><SentimentCell post={post} /></TableCell><TableCell className='text-right tabular-nums'>{post.reply_count ?? '—'}</TableCell><TableCell className='text-right tabular-nums'>{post.like_count ?? '—'}</TableCell><TableCell><div className='flex justify-end gap-1'><Button variant='ghost' size='sm' data-post-detail-trigger='true' onClick={(event) => openPost(post.id, event.currentTarget)}>查看</Button><Button variant='ghost' size='icon' onClick={() => copyText(post.url)} aria-label='复制帖子链接'><Copy className='size-4' /></Button></div></TableCell>
                </TableRow>
              }) : <TableRow><TableCell colSpan={10} className='h-52 text-center text-muted-foreground'>当前筛选条件下没有帖子结果。</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
        <div className='flex shrink-0 flex-col gap-3 border-t bg-card/95 p-4 sm:flex-row sm:items-center sm:justify-between' data-list-footer='run-posts'><div className='text-sm text-muted-foreground'>共 {posts.data?.total ?? 0} 条，第 {search.page} / {totalPages} 页</div><div className='flex gap-2'><Select value={String(search.pageSize)} onValueChange={(value) => patch({ pageSize: Number(value) as 20 | 50 | 100, page: 1 })}><SelectTrigger className='w-28'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='20'>每页 20</SelectItem><SelectItem value='50'>每页 50</SelectItem><SelectItem value='100'>每页 100</SelectItem></SelectContent></Select><Button variant='outline' size='icon' disabled={(search.page ?? 1) <= 1} onClick={() => patch({ page: (search.page ?? 1) - 1 })}><ChevronLeft className='size-4' /></Button><Button variant='outline' size='icon' disabled={(search.page ?? 1) >= totalPages} onClick={() => patch({ page: (search.page ?? 1) + 1 })}><ChevronRight className='size-4' /></Button></div></div>
      </div>
      </div>
      <TaskDialog open={tasksOpen} onOpenChange={setTasksOpen} tasks={run.data?.tasks ?? []} />
      <Sheet open={Boolean(search.post)} onOpenChange={(open) => { if (!open) closePostDetail() }}>
        <SheetContent className='w-full overflow-y-auto p-0 sm:max-w-[58vw]' onOpenAutoFocus={handleDetailOpenAutoFocus} onCloseAutoFocus={handleDetailCloseAutoFocus}>
          <SheetHeader className='sticky top-0 z-10 border-b bg-background/90 p-6 backdrop-blur'>
            <div className='flex items-start justify-between gap-4 pr-8'>
              <div>
                <SheetTitle>{detail.data?.title || '帖子快照详情'}</SheetTitle>
                <SheetDescription className='mt-1'>正文与统计来自数据库快照；含视频时仅刷新播放地址。{navigation.data && ` 当前为筛选结果第 ${navigation.data.position} / ${navigation.data.total} 条。`}</SheetDescription>
              </div>
              <div className='flex gap-1'>
                <Button
                  variant='outline'
                  size='icon'
                  className='transition-colors hover:bg-muted/70 focus-visible:bg-muted/70 aria-disabled:pointer-events-none'
                  disabled={!navigation.data?.previous_id}
                  aria-disabled={Boolean(postSwitch) || !navigation.data?.previous_id}
                  aria-busy={postSwitch?.direction === 'previous'}
                  onClick={() => moveToPost(navigation.data?.previous_id, (navigation.data?.position ?? 1) - 1, 'previous')}
                  aria-label='上一条'
                >
                  {postSwitch?.direction === 'previous' ? <LoaderCircle className='size-4 animate-spin' /> : <ChevronLeft className='size-4' />}
                </Button>
                <Button
                  variant='outline'
                  size='icon'
                  className='transition-colors hover:bg-muted/70 focus-visible:bg-muted/70 aria-disabled:pointer-events-none'
                  disabled={!navigation.data?.next_id}
                  aria-disabled={Boolean(postSwitch) || !navigation.data?.next_id}
                  aria-busy={postSwitch?.direction === 'next'}
                  onClick={() => moveToPost(navigation.data?.next_id, (navigation.data?.position ?? 0) + 1, 'next')}
                  aria-label='下一条'
                >
                  {postSwitch?.direction === 'next' ? <LoaderCircle className='size-4 animate-spin' /> : <ChevronRight className='size-4' />}
                </Button>
              </div>
            </div>
          </SheetHeader>
          {detail.isLoading ? <div className='space-y-4 p-6'><Skeleton className='h-10 w-2/3' /><Skeleton className='h-72 w-full' /></div> : detail.data && <PostDetailContent runId={runId} post={detail.data} onCorrect={() => setManualCorrectionOpen(true)} />}
        </SheetContent>
      </Sheet>
      <ManualSentimentDialog open={manualCorrectionOpen} onOpenChange={setManualCorrectionOpen} runId={runId} post={detail.data} onSaved={async () => { await Promise.all([detail.refetch(), posts.refetch()]) }} />
      <Dialog open={manualCopy !== undefined} onOpenChange={(open) => !open && setManualCopy(undefined)}><DialogContent><DialogHeader><DialogTitle>手动复制</DialogTitle><DialogDescription>当前浏览器上下文未开放剪贴板写入，文本已全选。</DialogDescription></DialogHeader><Textarea readOnly rows={12} value={manualCopy ?? ''} onFocus={(event) => event.currentTarget.select()} autoFocus /></DialogContent></Dialog>
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} runId={runId} freshOnOpen />
    </div>
  )
}

const analysisStatusNames: Record<AnalysisStatus, string> = {
  analysis_queued: '等待分析', analysis_running: '分析中', analysis_completed: '分析成功', analysis_partial: '分析不完整', analysis_failed: '分析失败', analysis_paused: '分析暂停', analysis_disabled: '分析禁用',
}
const sentimentNames: Record<SentimentResult, string> = { negative: '负面', non_negative: '非负面', unrelated: '不相关' }
const sentimentSourceNames = { ai: 'AI', manual: '人工', inherited_manual: '继承人工' }
const categoryNames: Record<string, string> = { product_complaint: '产品客诉', product_criticism: '产品吐槽', service_complaint: '服务投诉', brand_criticism: '品牌吐槽', competitor_attack: '竞品攻击', other: '其他' }
const categories = Object.keys(categoryNames)

function SentimentCell({ post }: { post: Post }) {
  if (post.sentiment_result) return <div className='flex flex-wrap gap-1.5'><StatusBadge value={post.sentiment_result === 'negative' ? 'failed' : post.sentiment_result === 'non_negative' ? 'success' : 'unknown'} label={sentimentNames[post.sentiment_result]} />{post.sentiment_source && <Badge variant='outline' className='font-normal'>{sentimentSourceNames[post.sentiment_source]}</Badge>}</div>
  return post.analysis_status ? <StatusBadge value={post.analysis_status === 'analysis_failed' ? 'failed' : post.analysis_status === 'analysis_running' ? 'running' : 'unknown'} label={analysisStatusNames[post.analysis_status]} /> : <span className='text-muted-foreground'>—</span>
}

function EvidenceList({ values }: { values?: string[] }) {
  return values?.length ? <ul className='list-disc space-y-1 pl-5 text-sm leading-6'>{values.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}</ul> : <div className='text-sm text-muted-foreground'>暂无事实依据。</div>
}

function PostDetailContent({ runId, post, onCorrect }: { runId: string; post: Post; onCorrect: () => void }) {
  const sentiment = post.sentiment
  const manualActionName = post.sentiment_result ? '人工修正' : '人工判定'
  return <div className='space-y-6 p-6'>
    <div className='grid gap-3 rounded-xl border bg-muted/20 p-4 sm:grid-cols-2'><Meta label='来源' value={[post.source_name || post.circle_name, post.list_order_name].filter(Boolean).join(' · ')} /><Meta label='作者' value={post.author} /><Meta label='发布时间' value={formatDate(post.published_at)} /><Meta label='平台帖子 ID' value={post.platform_post_id} /></div>
    <section className='space-y-3 rounded-xl border p-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'><div><div className='flex items-center gap-2'><BrainCircuit className='size-4 text-primary' /><h3 className='text-sm font-semibold'>舆情反馈</h3></div><div className='mt-2 flex flex-wrap gap-1.5'>{post.sentiment_result ? <><StatusBadge value={post.sentiment_result === 'negative' ? 'failed' : post.sentiment_result === 'non_negative' ? 'success' : 'unknown'} label={sentimentNames[post.sentiment_result]} />{post.sentiment_source && <Badge variant='outline'>{sentimentSourceNames[post.sentiment_source]}</Badge>}</> : post.analysis_status ? <StatusBadge value={post.analysis_status === 'analysis_failed' ? 'failed' : post.analysis_status === 'analysis_running' ? 'running' : 'unknown'} label={analysisStatusNames[post.analysis_status]} /> : <Badge variant='outline'>未建立分析任务</Badge>}</div></div>{sentiment?.can_manual_correct && <Button variant='outline' size='sm' onClick={onCorrect}><PencilLine className='size-4' />{manualActionName}</Button>}</div>
      {sentiment?.summary && <div><div className='mb-1 text-xs font-medium text-muted-foreground'>中文总结</div><div className='whitespace-pre-wrap text-sm leading-7'>{sentiment.summary}</div></div>}
      {sentiment?.matched_subjects.length ? <div className='flex flex-wrap gap-1.5'>{sentiment.matched_subjects.map((item) => <Badge key={item} variant='secondary'>{item}</Badge>)}</div> : null}
      {sentiment?.primary_category && <div className='text-sm'>主要类型：<Badge variant='outline'>{categoryNames[sentiment.primary_category] ?? sentiment.primary_category}</Badge>{sentiment.secondary_categories.length ? <span className='ml-2 text-muted-foreground'>次要类型：{sentiment.secondary_categories.map((item) => categoryNames[item] ?? item).join('、')}</span> : null}</div>}
      {sentiment?.modalities && <div className='grid gap-3 md:grid-cols-2'><div className='rounded-lg bg-muted/30 p-3'><div className='mb-2 text-xs font-medium text-muted-foreground'>文字依据 · {sentiment.modalities.text.status}</div><EvidenceList values={sentiment.modalities.text.evidence} /></div>{post.image_urls.map((url, index) => { const item = sentiment.modalities?.image.items.find((value) => value.input_index === index); return <div key={url} className='space-y-2 rounded-lg bg-muted/30 p-3'><div className='text-xs font-medium text-muted-foreground'>图片 {index + 1} · {item?.status ?? '未报告'}</div><img src={url} loading='lazy' referrerPolicy='no-referrer' className='max-h-72 w-full rounded-lg border object-contain' alt={`帖子图片 ${index + 1}`} /><EvidenceList values={item?.evidence} /></div> })}{post.video_urls.length > 0 && <VideoMedia key={post.id} runId={runId} post={post} sentiment={sentiment} />}</div>}
      {(post.image_urls.length > 0 || post.video_urls.length > 0) && !sentiment?.modalities && <div className='grid gap-3 md:grid-cols-2'>{post.image_urls.map((url, index) => <img key={url} src={url} loading='lazy' referrerPolicy='no-referrer' className='max-h-72 w-full rounded-lg border object-contain' alt={`帖子图片 ${index + 1}`} />)}{post.video_urls.length > 0 && <VideoMedia key={post.id} runId={runId} post={post} sentiment={sentiment} />}</div>}
      {sentiment?.error_message && <Alert variant='destructive'><AlertTitle>{analysisStatusNames[sentiment.analysis_status ?? 'analysis_failed']}</AlertTitle><AlertDescription>{sentiment.error_message}</AlertDescription></Alert>}
      {sentiment?.model_code && <div className='text-xs text-muted-foreground'>模型：{sentiment.model_code}{sentiment.updated_at ? ` · 更新时间：${formatDate(sentiment.updated_at)}` : ''}{sentiment.duration_ms !== undefined ? ` · ${sentiment.duration_ms} ms` : ''}</div>}
      <Button variant='link' className='h-auto px-0' asChild><a href={post.url} target='_blank' rel='noreferrer'>媒体无法显示时打开原帖<ExternalLink className='size-3.5' /></a></Button>
    </section>
    <div><h3 className='mb-2 text-sm font-semibold'>正文快照</h3><div className='whitespace-pre-wrap rounded-xl border bg-background p-4 text-sm leading-7'>{post.content || '正文为空'}</div></div>
    <div><h3 className='mb-2 text-sm font-semibold'>一级评论（{post.comments.length}）</h3><div className='space-y-2'>{post.comments.length ? post.comments.map((comment, index) => <div key={comment.platform_comment_id || index} className='rounded-xl border p-4'><div className='flex justify-between text-xs text-muted-foreground'><span>{comment.author || '匿名用户'}</span><span>{formatDate(comment.published_at)}</span></div><p className='mt-2 whitespace-pre-wrap text-sm'>{comment.content || '—'}</p></div>) : <div className='rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground'>没有已保存的一级评论。</div>}</div></div>
  </div>
}

type MediaResolveResponse = { video_urls: string[]; playback_urls: string[]; expires_at: string | null; source: 'live_url' }

function VideoMedia({ runId, post, sentiment }: { runId: string; post: Post; sentiment?: Post['sentiment'] }) {
  const resolvedMedia = useQuery({
    queryKey: ['post-video-media', runId, post.id],
    queryFn: () => api<MediaResolveResponse>(`/runs/${runId}/posts/${post.id}/media/resolve`, { method: 'POST' }),
    retry: false,
    refetchOnWindowFocus: false,
    gcTime: 0,
  })
  const urls = resolvedMedia.data?.playback_urls ?? []
  return <div className='space-y-3 rounded-lg bg-muted/30 p-3 md:col-span-2'>
    <div className='flex flex-wrap items-start justify-between gap-3'>
      <div><div className='text-xs font-medium text-muted-foreground'>视频媒体 · URL 播放</div><p className='mt-1 text-xs leading-5 text-muted-foreground'>打开详情时自动获取最新临时地址；后端不下载、不保存视频文件。</p></div>
      <Button type='button' size='sm' variant='outline' disabled={resolvedMedia.isFetching} onClick={() => void resolvedMedia.refetch()}>{resolvedMedia.isFetching ? <LoaderCircle className='size-4 animate-spin' /> : <RefreshCw className='size-4' />}{resolvedMedia.isFetching ? '正在加载' : resolvedMedia.isError ? '重试加载' : '刷新播放地址'}</Button>
    </div>
    {resolvedMedia.isPending && <div className='flex items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-sm text-muted-foreground'><LoaderCircle className='size-4 animate-spin' />正在获取当前视频地址…</div>}
    {resolvedMedia.isError && <Alert variant='destructive'><CircleAlert className='size-4' /><AlertTitle>视频地址获取失败</AlertTitle><AlertDescription>{errorMessage(resolvedMedia.error)}</AlertDescription></Alert>}
    {!resolvedMedia.isPending && !resolvedMedia.isError && urls.length === 0 && <div className='rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground'>当前帖子没有返回可播放的视频地址。</div>}
    {urls.map((url, index) => { const visual = sentiment?.modalities?.video_visual.items.find((value) => value.input_index === index); const audio = sentiment?.modalities?.video_audio.items.find((value) => value.input_index === index); return <div key={url} className='space-y-2'><div className='text-xs font-medium text-muted-foreground'>视频 {index + 1} · 画面 {visual?.status ?? '未报告'} · 音频 {audio?.status ?? '未报告'}</div><video controls preload='auto' playsInline src={url} className='max-h-96 w-full rounded-lg border'>当前浏览器未能播放该视频。</video>{sentiment?.modalities && <div className='grid gap-3 md:grid-cols-2'><div><div className='mb-1 text-xs text-muted-foreground'>画面依据</div><EvidenceList values={visual?.evidence} /></div><div><div className='mb-1 text-xs text-muted-foreground'>音频依据</div><EvidenceList values={audio?.evidence} /></div></div>}</div> })}
    {resolvedMedia.data?.expires_at && <div className='text-xs text-muted-foreground'>当前播放地址预计有效至：{formatDate(resolvedMedia.data.expires_at)}</div>}
  </div>
}

function ManualSentimentDialog({ open, onOpenChange, runId, post, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; runId: string; post?: Post; onSaved: () => Promise<void> }) {
  const [result, setResult] = useState<SentimentResult>('negative')
  const [primary, setPrimary] = useState('product_complaint')
  const [secondary, setSecondary] = useState<string[]>([])
  const [note, setNote] = useState('')
  const manualActionName = post?.sentiment_result ? '人工修正' : '人工判定'
  useEffect(() => { if (open) { setResult(post?.sentiment_result ?? 'negative'); setPrimary(post?.sentiment?.primary_category ?? 'product_complaint'); setSecondary(post?.sentiment?.secondary_categories ?? []); setNote('') } }, [open, post])
  const save = useMutation({ mutationFn: (action: 'set_result' | 'restore_ai') => api(`/runs/${runId}/posts/${post?.id}/sentiment/manual-revisions`, { method: 'POST', body: JSON.stringify({ action, result: action === 'set_result' ? result : undefined, primary_category: action === 'set_result' && result === 'negative' ? primary : undefined, secondary_categories: action === 'set_result' && result === 'negative' ? secondary : [], note: note.trim() || undefined }) }), onSuccess: async () => { await onSaved(); onOpenChange(false); toast.success('舆情结论已更新') }, onError: (error) => toast.error(`${manualActionName}失败`, { description: errorMessage(error) }) })
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className='sm:max-w-xl'><DialogHeader><DialogTitle>{manualActionName}舆情结论</DialogTitle><DialogDescription>本次操作追加保存历史，人工结论优先于 AI；分析中状态不会开放此入口。</DialogDescription></DialogHeader><div className='space-y-5'><div><Label>结论</Label><Select value={result} onValueChange={(value) => { setResult(value as SentimentResult); if (value !== 'negative') setSecondary([]) }}><SelectTrigger className='mt-2'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='negative'>负面</SelectItem><SelectItem value='non_negative'>非负面</SelectItem><SelectItem value='unrelated'>不相关</SelectItem></SelectContent></Select></div>{result === 'negative' && <><div><Label>主要类型</Label><Select value={primary} onValueChange={(value) => { setPrimary(value); setSecondary((items) => items.filter((item) => item !== value)) }}><SelectTrigger className='mt-2'><SelectValue /></SelectTrigger><SelectContent>{categories.map((value) => <SelectItem key={value} value={value}>{categoryNames[value]}</SelectItem>)}</SelectContent></Select></div><div><Label>次要类型（可多选）</Label><div className='mt-2 grid gap-2 sm:grid-cols-2'>{categories.filter((value) => value !== primary).map((value) => <label key={value} className='flex items-center gap-2 rounded-lg border p-2.5 text-sm'><Checkbox checked={secondary.includes(value)} onCheckedChange={(checked) => setSecondary(checked ? [...secondary, value] : secondary.filter((item) => item !== value))} />{categoryNames[value]}</label>)}</div></div></>}<div><Label htmlFor='sentiment-note'>{manualActionName === '人工修正' ? '修正' : '判定'}备注（选填）</Label><Textarea id='sentiment-note' className='mt-2' value={note} onChange={(event) => setNote(event.target.value)} /></div><div className='flex flex-wrap justify-between gap-2'><Button variant='outline' disabled={!post?.sentiment?.can_restore_ai || save.isPending} onClick={() => save.mutate('restore_ai')}>恢复 AI 结论</Button><Button disabled={save.isPending} onClick={() => save.mutate('set_result')}>{save.isPending ? <LoaderCircle className='size-4 animate-spin' /> : <PencilLine className='size-4' />}保存{manualActionName}</Button></div></div></DialogContent></Dialog>
}

function Meta({ label, value }: { label: string; value?: string }) { return <div><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-1 break-all text-sm'>{value || '—'}</div></div> }

function TaskDialog({ open, onOpenChange, tasks }: { open: boolean; onOpenChange: (open: boolean) => void; tasks: RunTask[] }) {
  const groups = Array.from(tasks.reduce<Map<string, RunTask[]>>((result, task) => {
    const items = result.get(task.platform_code) ?? []
    items.push(task)
    result.set(task.platform_code, items)
    return result
  }, new Map()))
  const targetCount = tasks.reduce((total, task) => total + task.target_count, 0)
  const completedCount = tasks.reduce((total, task) => total + task.completed_count, 0)
  const successfulCount = tasks.filter((task) => ['success', 'completed'].includes(task.status)).length
  const issueCount = tasks.filter((task) => task.failed_count > 0 || task.status === 'failed').length
  const overallProgress = progressValue(completedCount, targetCount)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[86svh] gap-0 overflow-hidden border-border/80 bg-background p-0 shadow-2xl sm:max-w-5xl'>
        <DialogHeader className='relative border-b bg-muted/25 px-5 py-5 pr-14 sm:px-6'>
          <div className='flex items-start gap-3'>
            <div className='flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary shadow-sm'>
              <ListTree className='size-5' />
            </div>
            <div className='min-w-0 space-y-1'>
              <DialogTitle className='text-xl'>来源任务</DialogTitle>
              <DialogDescription>按平台查看每个来源的提取状态与结果进度。</DialogDescription>
            </div>
          </div>

          <div className='mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4'>
            <TaskSummary icon={Layers3} label='任务总数' value={`${tasks.length} 个`} />
            <TaskSummary icon={CircleCheckBig} label='已成功' value={`${successfulCount} 个`} />
            <TaskSummary icon={Gauge} label='结果进度' value={`${completedCount} / ${targetCount}`} />
            <TaskSummary icon={CircleAlert} label='存在异常' value={`${issueCount} 个`} tone={issueCount ? 'danger' : 'normal'} />
          </div>

          <div className='mt-3 flex items-center gap-3'>
            <Progress value={overallProgress} className='h-1.5 flex-1' />
            <span className='w-10 text-right text-xs font-medium tabular-nums text-muted-foreground'>{overallProgress}%</span>
          </div>
        </DialogHeader>

        <ScrollArea className='h-[min(58svh,580px)]'>
          <div className='space-y-4 p-4 sm:p-5'>
            {groups.map(([platformCode, items]) => {
              const platformTarget = items.reduce((total, task) => total + task.target_count, 0)
              const platformCompleted = items.reduce((total, task) => total + task.completed_count, 0)
              const platformProgress = progressValue(platformCompleted, platformTarget)

              return (
                <section key={platformCode} className='overflow-hidden rounded-xl border border-border/70 bg-card shadow-sm'>
                  <div className='flex flex-col gap-3 border-b bg-muted/30 px-4 py-3 sm:flex-row sm:items-center sm:justify-between'>
                    <div className='flex items-center gap-2.5'>
                      <div className='flex size-8 items-center justify-center rounded-lg border bg-background text-muted-foreground'>
                        <Layers3 className='size-4' />
                      </div>
                      <div>
                        <h3 className='text-sm font-semibold'>{platformName(platformCode)}</h3>
                        <p className='text-xs text-muted-foreground'>{items.length} 个来源任务</p>
                      </div>
                    </div>
                    <div className='flex min-w-48 items-center gap-3'>
                      <Progress value={platformProgress} className='h-1.5 flex-1' />
                      <span className='text-xs font-medium tabular-nums text-muted-foreground'>{platformCompleted} / {platformTarget}</span>
                    </div>
                  </div>

                  <div className='divide-y divide-border/60'>
                    {items.map((task) => <TaskRow key={task.id} task={task} />)}
                  </div>
                </section>
              )
            })}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}

function TaskSummary({ icon: Icon, label, value, tone = 'normal' }: { icon: typeof Layers3; label: string; value: string; tone?: 'normal' | 'danger' }) {
  return (
    <div className='rounded-lg border border-border/70 bg-background/85 px-3 py-2.5 shadow-xs'>
      <div className='flex items-center gap-1.5 text-xs text-muted-foreground'><Icon className={cn('size-3.5', tone === 'danger' && 'text-destructive')} />{label}</div>
      <div className={cn('mt-1 text-sm font-semibold tabular-nums', tone === 'danger' && 'text-destructive')}>{value}</div>
    </div>
  )
}

function TaskRow({ task }: { task: RunTask }) {
  const progress = progressValue(task.completed_count, task.target_count)
  const detail = task.error_message || task.stop_reason
  const hasIssue = task.failed_count > 0 || task.status === 'failed'

  return (
    <div className='grid gap-3 px-4 py-3.5 transition-colors hover:bg-muted/20 sm:grid-cols-[minmax(0,1fr)_120px_160px] sm:items-center'>
      <div className='min-w-0'>
        <div className='flex min-w-0 items-center gap-2'>
          <span className='truncate text-sm font-semibold'>{task.source_name || task.circle_name || task.external_id}</span>
          <Badge variant='outline' className='shrink-0 font-normal'>{task.list_order_name || (task.list_order === 'latest_publish' ? '最新发布' : '最新回复')}</Badge>
          {task.circle_url && <a href={task.circle_url} target='_blank' rel='noreferrer' className='shrink-0 text-muted-foreground transition-colors hover:text-primary' aria-label={`打开${task.source_name || task.circle_name || task.external_id}`}><ExternalLink className='size-3.5' /></a>}
        </div>
        <div className={cn('mt-1 flex items-start gap-1.5 text-xs leading-5 text-muted-foreground', hasIssue && 'text-destructive')}>
          {hasIssue ? <CircleAlert className='mt-0.5 size-3.5 shrink-0' /> : <CircleCheckBig className='mt-0.5 size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400' />}
          <span className='line-clamp-2'>{detail || (task.completed_count >= task.target_count ? '已达到配置的有效结果目标。' : '任务正在按配置目标执行。')}</span>
        </div>
      </div>
      <div className='flex items-center sm:justify-center'><StatusBadge value={task.status} label={task.status_name} /></div>
      <div className='space-y-1.5'>
        <div className='flex items-center justify-between text-xs'>
          <span className='text-muted-foreground'>结果进度</span>
          <span className='font-medium tabular-nums'>{task.completed_count} / {task.target_count}</span>
        </div>
        <Progress value={progress} className='h-1.5' />
        {task.failed_count > 0 && <div className='text-right text-[11px] font-medium text-destructive'>{task.failed_count} 项失败</div>}
      </div>
    </div>
  )
}

function progressValue(completed: number, target: number) {
  return target > 0 ? Math.min(100, Math.round((completed / target) * 100)) : 0
}

function isActiveRun(run?: Run) {
  return Boolean(run && ['queued', 'running', 'waiting_for_auth'].includes(run.status))
}

const emptyRunsSearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, listOrder: undefined, from: undefined, to: undefined }
