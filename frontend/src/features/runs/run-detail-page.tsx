import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ArrowLeft, BrainCircuit, Check, CircleAlert, CircleCheckBig, CircleStop, ChevronLeft, ChevronRight, ChevronsUpDown, Copy, Download, ExternalLink, Eye, Gauge, Images, KeyRound, Layers3, Link2, ListTree, LoaderCircle, PencilLine, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { AuthDialog } from '@/features/auth/auth-dialog'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { api, errorMessage, formatDate, platformName, queryString } from '@/lib/api'
import type { AnalysisStatus, PageResult, Post, PostNavigation, Run, RunSourceOption, RunTask, ScreenshotGroup, SentimentResult, Template } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

type SearchState = { view?: 'links' | 'screenshots'; page?: number; pageSize?: 20 | 50 | 100; title?: string; sources?: string; visibility?: 'visible' | 'hidden' | 'unknown'; sentiment?: SentimentResult; analysisStatus?: AnalysisStatus; sort?: 'source' | 'published_at' | 'reply_count' | 'like_count'; direction?: 'asc' | 'desc'; post?: string }
type PostSwitch = { id: string; direction: 'previous' | 'next' }
type RunDetailKind = 'extraction' | 'recurring'

export function RunDetailPage() {
  return <RunDetail kind='extraction' />
}

export function RecurringRunDetailPage() {
  return <RunDetail kind='recurring' />
}

function RunDetail({ kind }: { kind: RunDetailKind }) {
  const recurring = kind === 'recurring'
  const listPath = recurring ? '/recurring-runs' as const : '/runs' as const
  const detailPath = recurring ? '/recurring-runs/$runId' as const : '/runs/$runId' as const
  const { runId } = useParams({ strict: false }) as { runId: string }
  const rawSearch = useSearch({ strict: false }) as SearchState
  const navigate = useNavigate()
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
  const selectedSourceKeys = (search.sources ?? '').split(',').filter(Boolean)
  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api<Run>(`/runs/${runId}`, undefined, 20_000),
    refetchInterval: (current) => isActiveRun(current.state.data) ? 3_000 : 60_000,
  })
  const postQueryValues = { title: debouncedTitle, source_key: selectedSourceKeys, visibility: search.visibility, sentiment_result: search.sentiment, analysis_status: search.analysisStatus, sort_by: search.sort, sort_direction: search.direction }
  const posts = useQuery({
    queryKey: ['posts', runId, run.data?.summary_version ?? 0, { page: search.page, pageSize: search.pageSize, ...postQueryValues }],
    queryFn: () => api<PageResult<Post>>(`/runs/${runId}/posts${queryString({ offset: ((search.page ?? 1) - 1) * (search.pageSize ?? 50), limit: search.pageSize, ...postQueryValues })}`, undefined, 20_000),
    placeholderData: keepPreviousData,
    refetchInterval: (current) => isActiveRun(run.data) || current.state.data?.items.some((post) => ['analysis_queued', 'analysis_running'].includes(post.analysis_status ?? '')) ? 3_000 : false,
  })
  const screenshots = useQuery({
    queryKey: ['run-screenshots', runId, run.data?.summary_version ?? 0],
    queryFn: () => api<{ items: ScreenshotGroup[] }>(`/runs/${runId}/screenshots`, undefined, 20_000),
    enabled: search.view === 'screenshots',
    refetchInterval: (current) => current.state.data?.items.some((item) => ['evidence_pending', 'evidence_running', 'waiting_for_sentiment', 'rendering'].includes(item.status)) ? 3_000 : false,
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
    const next = { ...rawSearch, ...values }
    navigate({
      to: detailPath,
      params: { runId },
      search: {
        view: next.view,
        page: next.page,
        pageSize: next.pageSize,
        title: next.title,
        sources: next.sources,
        visibility: next.visibility,
        sentiment: next.sentiment,
        analysisStatus: next.analysisStatus,
        sort: next.sort,
        direction: next.direction,
        post: next.post,
      },
      replace: true,
      resetScroll: options?.resetScroll ?? false,
    })
  }

  const retry = useMutation({ mutationFn: () => api<Run>(`/runs/${runId}/retry`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }), onSuccess: async (value) => { await client.invalidateQueries({ queryKey: ['runs'] }); toast.success('失败项已重新提交', { description: `新批次 ${value.number}` }) }, onError: (error) => toast.error('重新提取失败', { description: errorMessage(error) }) })
  const exportRun = useMutation({ mutationFn: (templateVersionId: string) => api<{ id: string }>(`/runs/${runId}/exports`, { method: 'POST', body: JSON.stringify({ template_version_id: templateVersionId }) }), onSuccess: (value) => { window.open(`/api/v1/exports/${value.id}/download`, '_blank', 'noopener'); toast.success('Excel 导出已生成') }, onError: (error) => toast.error('导出失败', { description: errorMessage(error) }) })
  const endAuthWait = useMutation({ mutationFn: () => api<Run>(`/runs/${runId}/end-auth-wait`, { method: 'POST' }), onSuccess: async (value) => { client.setQueryData(['run', runId], value); await client.invalidateQueries({ queryKey: ['runs'] }); toast.success('本次提取已结束') }, onError: (error) => toast.error('结束提取失败', { description: errorMessage(error) }) })
  const deleteRun = useMutation({ mutationFn: () => api<{ message: string }>(`/runs/${runId}`, { method: 'DELETE' }), onSuccess: async () => { client.removeQueries({ queryKey: ['run', runId] }); await client.invalidateQueries({ queryKey: ['runs'] }); toast.success('批次及关联快照已永久删除'); navigate({ to: listPath, search: emptyRunsSearch }) }, onError: (error) => toast.error('删除批次失败', { description: errorMessage(error) }) })

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
          eyebrow={<Button variant='ghost' size='sm' className='-ml-2 h-7 px-2 text-xs' onClick={() => navigate({ to: listPath, search: emptyRunsSearch })}><ArrowLeft className='size-3.5' />返回{recurring ? '循环计划列表' : '提取列表'}</Button>}
          title={run.data ? `批次 ${run.data.number}` : '批次链接详情'}
          description='结果按原始来源位置稳定合并；搜索、筛选、排序和分页均由后端对完整结果集执行。'
          actions={<>
            <Button variant='outline' size='sm' onClick={() => { run.refetch(); posts.refetch() }}><RefreshCw className={`size-4 ${run.isFetching || posts.isFetching ? 'animate-spin' : ''}`} />刷新</Button>
            {run.data?.tasks?.length ? <Button variant='outline' size='sm' onClick={() => setTasksOpen(true)}><ListTree className='size-4' />来源任务 <span className='text-xs text-muted-foreground'>{run.data.tasks.length}</span></Button> : null}
            {run.data?.status === 'waiting_for_auth' && <><Button variant='outline' size='sm' onClick={() => setAuthOpen(true)}><KeyRound className='size-4' />处理会话</Button><AlertDialog><AlertDialogTrigger asChild><Button variant='outline' size='sm'><CircleStop className='size-4' />结束本次提取</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>结束本次提取？</AlertDialogTitle><AlertDialogDescription>已有结果将保留，批次按实际结果结束并释放平台队列；之后仍可重新提取失败项。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => endAuthWait.mutate()}>确认结束</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></>}
            {canRetry && <AlertDialog><AlertDialogTrigger asChild><Button variant='outline' size='sm'>重新提取失败项</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>重新提取失败项？</AlertDialogTitle><AlertDialogDescription>系统会保留原批次快照，只把失败 URL 创建为关联补提批次。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => retry.mutate()}>确认重新提取</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}
            {canDelete && <AlertDialog><AlertDialogTrigger asChild><Button variant='ghost' size='sm' className='text-destructive hover:text-destructive'><Trash2 className='size-4' />永久删除</Button></AlertDialogTrigger><AlertDialogContent aria-busy={deleteRun.isPending} onEscapeKeyDown={(event) => { if (deleteRun.isPending) event.preventDefault() }}><AlertDialogHeader><AlertDialogTitle>{deleteRun.isPending ? '正在永久删除批次…' : '永久删除该批次？'}</AlertDialogTitle><AlertDialogDescription>{deleteRun.isPending ? `正在清理批次数据和关联文件；若其他批次仍在共用截图成果，系统还会重新生成当前成果。完成后将自动返回${recurring ? '循环计划列表' : '提取列表'}。` : '批次、帖子快照、一级评论、页面证据和已生成导出记录都会一并删除；关联截图成果将按剩余贡献重新生成。此操作不可撤回。'}</AlertDialogDescription></AlertDialogHeader>{deleteRun.isPending && <div role='status' aria-live='polite' className='flex items-center gap-3 rounded-lg border border-border/70 bg-muted/35 p-3 text-sm text-muted-foreground'><LoaderCircle className='size-4 shrink-0 animate-spin motion-reduce:animate-none' /><span>正在执行删除与关联内容整理，请勿关闭页面…</span></div>}<AlertDialogFooter><AlertDialogCancel disabled={deleteRun.isPending}>取消</AlertDialogCancel><AlertDialogAction disabled={deleteRun.isPending} aria-busy={deleteRun.isPending} onClick={(event) => { event.preventDefault(); if (!deleteRun.isPending) deleteRun.mutate() }}>{deleteRun.isPending ? <><LoaderCircle className='size-4 animate-spin motion-reduce:animate-none' />正在永久删除</> : '确认永久删除'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}
          </>}
        />
      {run.isLoading ? <Skeleton className='h-20 rounded-xl' /> : run.data && <div className='grid gap-2 sm:grid-cols-2 xl:grid-cols-5'>{[
        ['状态', <StatusBadge key='status' value={run.data.status} label={run.data.status_name} />],
        ['触发方式', `${run.data.trigger_type_name} · ${inputModeName}`],
        ['结果进度', `${run.data.completed_count} / ${run.data.planned_count}`],
        [run.data.status === 'success' && run.data.completed_count >= run.data.planned_count ? '跳过异常候选' : '失败项', String(run.data.failed_count)],
        ['创建时间', formatDate(run.data.created_at)],
      ].map(([label, value]) => <Card key={String(label)} className='border-border/70 bg-card/88 py-0'><CardContent className='p-3'><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-1 text-sm font-semibold'>{value}</div></CardContent></Card>)}</div>}
      {run.data?.waiting_reason && <Alert><KeyRound className='size-4' /><AlertTitle>等待平台会话</AlertTitle><AlertDescription>{run.data.waiting_reason}</AlertDescription></Alert>}
      {run.data?.error_message && <Alert variant='destructive'><AlertTitle>批次错误</AlertTitle><AlertDescription>{run.data.error_message}</AlertDescription></Alert>}
        <div className='flex w-fit rounded-lg border bg-muted/25 p-1' role='tablist' aria-label='批次结果视图'><Button role='tab' aria-selected={search.view !== 'screenshots'} variant={search.view !== 'screenshots' ? 'secondary' : 'ghost'} size='sm' onClick={() => patch({ view: 'links' })}><Link2 className='size-4' />链接结果</Button><Button role='tab' aria-selected={search.view === 'screenshots'} variant={search.view === 'screenshots' ? 'secondary' : 'ghost'} size='sm' onClick={() => patch({ view: 'screenshots' })}><Images className='size-4' />页面截图</Button></div>
        {search.view !== 'screenshots' && <Card className='border-border/70 bg-card/88 py-0'><CardContent className='grid gap-2 p-3 [&>[data-slot=select-trigger]]:w-full [&>[data-slot=select-trigger]]:min-w-0 [&>[data-slot=select-trigger]]:gap-1 [&>[data-slot=select-trigger]]:px-2 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-[minmax(180px,1fr)_190px_125px_130px_130px_100px_88px_auto] [@media(min-width:2000px)]:grid-cols-[minmax(180px,360px)_210px_125px_130px_130px_100px_88px_minmax(0,1fr)_auto]'><Input placeholder='搜索帖子标题' aria-label='搜索帖子标题' value={search.title ?? ''} onChange={(event) => patch({ title: event.target.value || undefined, page: 1 })} /><SourceMultiSelect options={posts.data?.source_options ?? []} values={selectedSourceKeys} onChange={(values) => patch({ sources: values.length ? values.join(',') : undefined, page: 1 })} /><Select value={search.visibility ?? 'all'} onValueChange={(value) => patch({ visibility: value === 'all' ? undefined : value as SearchState['visibility'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部可见状态</SelectItem><SelectItem value='visible'>可见</SelectItem><SelectItem value='hidden'>不可见</SelectItem><SelectItem value='unknown'>未知</SelectItem></SelectContent></Select><Select value={search.sentiment ?? 'all'} onValueChange={(value) => patch({ sentiment: value === 'all' ? undefined : value as SentimentResult, page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部舆情结果</SelectItem><SelectItem value='negative'>负面</SelectItem><SelectItem value='non_negative'>非负面</SelectItem><SelectItem value='unrelated'>不相关</SelectItem></SelectContent></Select><Select value={search.analysisStatus ?? 'all'} onValueChange={(value) => patch({ analysisStatus: value === 'all' ? undefined : value as AnalysisStatus, page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部分析状态</SelectItem>{Object.entries(analysisStatusNames).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select><Select value={search.sort} onValueChange={(value) => patch({ sort: value as SearchState['sort'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='source'>来源顺序</SelectItem><SelectItem value='published_at'>发布时间</SelectItem><SelectItem value='reply_count'>评论数</SelectItem><SelectItem value='like_count'>点赞数</SelectItem></SelectContent></Select><Select value={search.direction} onValueChange={(value) => patch({ direction: value as SearchState['direction'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='asc'>正序</SelectItem><SelectItem value='desc'>倒序</SelectItem></SelectContent></Select><div className='flex min-w-0 items-center justify-end gap-2 [@media(min-width:2000px)]:col-start-9'><Button className='shrink-0' variant='outline' onClick={copyAll}><Copy className='size-4' />复制全部</Button><Select onValueChange={(value) => exportRun.mutate(value)} disabled={!templates.data?.length || exportRun.isPending}><SelectTrigger className='w-36'><Download className='size-4' /><SelectValue placeholder={templates.data?.length ? '导出 Excel' : '暂无模板'} /></SelectTrigger><SelectContent>{templates.data?.map((item) => item.versions[0] && <SelectItem key={item.versions[0].version_id} value={item.versions[0].version_id}>{item.name}</SelectItem>)}</SelectContent></Select></div></CardContent></Card>}
      </div>
      <div className='min-h-[360px] flex-1 xl:min-h-0'>
        {search.view === 'screenshots' ? <ScreenshotPanel groups={screenshots.data?.items} loading={screenshots.isLoading} error={screenshots.error} onRetry={() => screenshots.refetch()} /> :
        <div className='flex h-[min(65svh,640px)] min-h-[360px] flex-col overflow-hidden rounded-xl border border-border/70 bg-card/90 xl:h-full xl:min-h-0'>
        <div className='min-h-0 flex-1 overflow-auto' data-list-viewport='run-posts'>
          <Table className='min-w-[1050px]'>
            <TableHeader><TableRow className='bg-muted/35'><TableHead className='w-16 text-center'>序号</TableHead><TableHead>标题</TableHead><TableHead>来源</TableHead><TableHead>作者</TableHead><TableHead>发布时间</TableHead><TableHead>可见状态</TableHead><TableHead>舆情结果</TableHead><TableHead className='text-right'>评论数</TableHead><TableHead className='text-right'>点赞数</TableHead><TableHead className='text-right'>操作</TableHead></TableRow></TableHeader>
            <TableBody>
              {posts.isLoading ? Array.from({ length: 6 }).map((_, index) => <TableRow key={index}>{Array.from({ length: 10 }).map((__, cell) => <TableCell key={cell}><Skeleton className='h-6 w-full' /></TableCell>)}</TableRow>) : posts.isError ? <TableRow><TableCell colSpan={10} className='h-56 text-center'><CircleAlert className='mx-auto mb-2 size-5 text-destructive' /><div className='text-sm font-medium'>帖子列表加载失败</div><div className='mt-1 text-xs text-muted-foreground'>{errorMessage(posts.error)}</div><Button className='mt-3' variant='outline' size='sm' onClick={() => posts.refetch()}><RefreshCw className='size-4' />重新加载</Button></TableCell></TableRow> : posts.data?.items.length ? posts.data.items.map((post, index) => {
                const isCurrentPost = post.id === search.post
                const isLastViewedPost = !search.post && post.id === lastViewedPostId
                const isHighlightedPost = isCurrentPost || isLastViewedPost
                const forumIdentity = postForumIdentity(post)
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
                  </TableCell><TableCell><div className='flex min-w-0 items-center gap-1.5'><span className='truncate'>{post.source_name || post.circle_name || '—'}</span>{post.list_order_name && <Badge variant='outline' className='h-5 shrink-0 px-1.5 text-[11px] font-normal'>{post.list_order_name}</Badge>}{forumIdentity.crossForum && <Badge variant='secondary' className='h-5 shrink-0 px-1.5 text-[11px] font-normal'>跨论坛</Badge>}</div></TableCell><TableCell>{post.author || '—'}</TableCell><TableCell className='whitespace-nowrap'>{formatDate(post.published_at)}</TableCell><TableCell><StatusBadge value={post.visibility} label={{ visible: '可见', hidden: '不可见', unknown: '未知' }[post.visibility]} /></TableCell><TableCell><SentimentCell post={post} /></TableCell><TableCell className='text-right tabular-nums'>{post.reply_count ?? '—'}</TableCell><TableCell className='text-right tabular-nums'>{post.like_count ?? '—'}</TableCell><TableCell><div className='flex justify-end gap-1'><Button variant='ghost' size='sm' data-post-detail-trigger='true' onClick={(event) => openPost(post.id, event.currentTarget)}>查看</Button><Button variant='ghost' size='icon' onClick={() => copyText(post.url)} aria-label='复制帖子链接'><Copy className='size-4' /></Button></div></TableCell>
                </TableRow>
              }) : <TableRow><TableCell colSpan={10} className='h-52 text-center text-muted-foreground'>当前筛选条件下没有帖子结果。</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
        <div className='flex shrink-0 flex-col gap-3 border-t bg-card/95 p-4 sm:flex-row sm:items-center sm:justify-between' data-list-footer='run-posts'><div className='text-sm text-muted-foreground'>{posts.isLoading ? '正在加载帖子…' : posts.isError ? '帖子加载失败' : `共 ${posts.data?.total ?? 0} 条，第 ${search.page} / ${totalPages} 页`}</div><div className='flex gap-2'><Select value={String(search.pageSize)} onValueChange={(value) => patch({ pageSize: Number(value) as 20 | 50 | 100, page: 1 })}><SelectTrigger className='w-28'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='20'>每页 20</SelectItem><SelectItem value='50'>每页 50</SelectItem><SelectItem value='100'>每页 100</SelectItem></SelectContent></Select><Button variant='outline' size='icon' disabled={(search.page ?? 1) <= 1} onClick={() => patch({ page: (search.page ?? 1) - 1 })}><ChevronLeft className='size-4' /></Button><Button variant='outline' size='icon' disabled={(search.page ?? 1) >= totalPages} onClick={() => patch({ page: (search.page ?? 1) + 1 })}><ChevronRight className='size-4' /></Button></div></div>
      </div>}
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
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} platformCode={run.data?.waiting_platform_codes?.[0] ?? run.data?.platform_codes?.[0]} runId={runId} freshOnOpen />
    </div>
  )
}

function screenshotArtifactSummary(group: ScreenshotGroup) {
  const items = group.artifact?.items ?? []
  const runCount = new Set(items.map((item) => item.run_number)).size
  const captured = items.map((item) => item.captured_at).filter(Boolean).sort()
  const first = captured[0]
  const last = captured[captured.length - 1]
  const range = first ? first === last ? formatDate(first) : `${formatDate(first)} 至 ${formatDate(last)}` : '—'
  return `当前版本 v${group.current_version}，共 ${group.item_count} 条、负面 ${group.negative_count} 条；贡献批次 ${runCount} 个，捕获时间 ${range}。`
}

function SourceMultiSelect({ options, values, onChange }: { options: RunSourceOption[]; values: string[]; onChange: (values: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const selected = options.filter((option) => values.includes(option.key))
  const label = values.length === 0 ? '全部来源' : selected.length === 1 && values.length === 1 ? `${selected[0].source_name} · ${selected[0].list_order_name}` : `已选 ${values.length} 个来源`
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild><Button type='button' variant='outline' role='combobox' aria-expanded={open} aria-label={`筛选来源，当前${label}`} className='w-full min-w-0 justify-between px-2 font-normal'><span className='truncate'>{label}</span><ChevronsUpDown className='size-4 shrink-0 text-muted-foreground' /></Button></PopoverTrigger>
    <PopoverContent align='start' className='w-[var(--radix-popover-trigger-width)] min-w-80 p-0'>
      <Command><CommandInput placeholder='搜索来源名称或圈子' /><CommandList><CommandEmpty>当前批次没有匹配来源。</CommandEmpty><CommandGroup>{options.map((option) => { const checked = values.includes(option.key); return <CommandItem key={option.key} value={`${option.source_name} ${option.circle_name} ${option.external_id} ${option.list_order_name}`} onSelect={() => onChange(checked ? values.filter((key) => key !== option.key) : [...values, option.key])}><Check className={cn('size-4', checked ? 'opacity-100' : 'opacity-0')} /><div className='min-w-0 flex-1'><div className='truncate text-sm font-medium'>{option.source_name}</div><div className='mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground'><span className='truncate'>{option.circle_name}</span><Badge variant='outline' className='h-5 shrink-0 px-1.5 text-[11px] font-normal'>{option.list_order_name}</Badge></div></div></CommandItem> })}</CommandGroup></CommandList>{values.length > 0 && <div className='border-t p-1.5'><Button type='button' variant='ghost' size='sm' className='w-full' onClick={() => onChange([])}>清除选择</Button></div>}</Command>
    </PopoverContent>
  </Popover>
}

function ScreenshotPanel({ groups, loading, error, onRetry }: { groups?: ScreenshotGroup[]; loading: boolean; error: unknown; onRetry: () => void }) {
  const [viewer, setViewer] = useState<{ group: ScreenshotGroup; mode: 'artifact' | 'evidence'; evidenceIndex: number }>()
  if (loading) return <div className='grid gap-3 md:grid-cols-2'>{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className='h-48 rounded-xl' />)}</div>
  if (error) return <div className='flex h-full min-h-[360px] flex-col items-center justify-center rounded-xl border border-border/70 bg-card/90 text-center'><CircleAlert className='mb-2 size-6 text-destructive' /><div className='font-medium'>页面截图加载失败</div><div className='mt-1 text-sm text-muted-foreground'>{errorMessage(error)}</div><Button className='mt-4' variant='outline' onClick={onRetry}><RefreshCw className='size-4' />重新加载</Button></div>
  return <div className='h-full min-h-[360px] overflow-auto rounded-xl border border-border/70 bg-card/90 p-4' aria-live='polite'>
    <div className='mb-4'><h2 className='font-semibold'>圈子页面截图</h2><p className='mt-1 text-sm text-muted-foreground'>每个实际圈子来源独立保留原始全页证据；最终成果汇总当前有效条目，并一次性框出全部负面卡片。</p></div>
    {!groups?.length ? <div className='rounded-xl border border-dashed p-12 text-center text-sm text-muted-foreground'>当前批次没有圈子来源截图。</div> : <div className='grid gap-3 xl:grid-cols-2'>{groups.map((group, index) => {
      const status = screenshotStatus[group.status]
      return <Card key={group.id ?? `${group.external_id}-${group.list_order}-${index}`} className='border-border/70 py-0'><CardContent className='space-y-4 p-4'>
        <div className='flex items-start justify-between gap-3'><div className='min-w-0'><div className='flex flex-wrap items-center gap-2'><h3 className='truncate font-semibold'>{group.circle_name || group.external_id}</h3><Badge variant='outline'>{group.list_order === 'latest_reply' ? '最新回复' : '最新发布'}</Badge></div><div className='mt-1 text-xs text-muted-foreground'>圈子 ID {group.external_id} · 原始证据 {group.evidence.length} 页 · 成果 v{group.current_version}</div></div><StatusBadge value={status.value} label={status.label} /></div>
        <div className='grid grid-cols-3 gap-2 rounded-lg bg-muted/30 p-3 text-center'><div><div className='text-lg font-semibold tabular-nums'>{group.item_count}</div><div className='text-xs text-muted-foreground'>有效条目</div></div><div><div className='text-lg font-semibold tabular-nums text-destructive'>{group.negative_count}</div><div className='text-xs text-muted-foreground'>负面条目</div></div><div><div className='text-lg font-semibold tabular-nums'>{group.artifact?.tiles.length ?? 0}</div><div className='text-xs text-muted-foreground'>成果分片</div></div></div>
        {group.error_message && <Alert variant='destructive'><CircleAlert className='size-4' /><AlertDescription>{group.error_message}</AlertDescription></Alert>}
        <div className='flex flex-wrap gap-2'><Button size='sm' disabled={!group.artifact} onClick={() => setViewer({ group, mode: 'artifact', evidenceIndex: 0 })}><Eye className='size-4' />查看负面成果</Button><Button size='sm' variant='outline' disabled={!group.evidence.length} onClick={() => setViewer({ group, mode: 'evidence', evidenceIndex: 0 })}><Images className='size-4' />查看原始全页</Button>{group.artifact && <Button size='sm' variant='outline' asChild><a href={group.artifact.download_url}><Download className='size-4' />打包下载</a></Button>}</div>
      </CardContent></Card>
    })}</div>}
    <Dialog open={Boolean(viewer)} onOpenChange={(open) => !open && setViewer(undefined)}><DialogContent className='h-[92svh] max-w-[96vw] gap-0 overflow-hidden p-0 sm:max-w-[96vw]'><DialogHeader className='border-b px-5 py-4 pr-14'><DialogTitle>{viewer?.group.circle_name || viewer?.group.external_id} · {viewer?.mode === 'artifact' ? '负面框选成果' : '原始全页证据'}</DialogTitle><DialogDescription>{viewer?.mode === 'artifact' ? screenshotArtifactSummary(viewer.group) : '原始证据保持采集时页面像素，不叠加判定标记。'}</DialogDescription><div className='flex flex-wrap gap-2 pt-2'><Button size='sm' variant={viewer?.mode === 'artifact' ? 'secondary' : 'outline'} disabled={!viewer?.group.artifact} onClick={() => viewer && setViewer({ ...viewer, mode: 'artifact' })}>负面成果</Button><Button size='sm' variant={viewer?.mode === 'evidence' ? 'secondary' : 'outline'} disabled={!viewer?.group.evidence.length} onClick={() => viewer && setViewer({ ...viewer, mode: 'evidence' })}>原始全页</Button>{viewer?.mode === 'evidence' && viewer.group.evidence.length > 1 && <Select value={String(viewer.evidenceIndex)} onValueChange={(value) => setViewer({ ...viewer, evidenceIndex: Number(value) })}><SelectTrigger className='w-32'><SelectValue /></SelectTrigger><SelectContent>{viewer.group.evidence.map((item, evidenceIndex) => <SelectItem key={item.id} value={String(evidenceIndex)}>第 {item.page_number} 页</SelectItem>)}</SelectContent></Select>}</div></DialogHeader><ScrollArea className='min-h-0 flex-1 bg-muted/35'><div className='mx-auto max-w-[1440px] space-y-3 p-4'>{viewer?.mode === 'artifact' ? viewer.group.artifact?.tiles.map((tile) => <img key={tile.index} src={tile.image_url} loading='lazy' className='h-auto w-full border bg-white shadow-sm' alt={`负面框选成果第 ${tile.index + 1} 片`} />) : viewer && <img src={viewer.group.evidence[viewer.evidenceIndex]?.image_url} className='h-auto w-full border bg-white shadow-sm' alt={`原始全页证据第 ${viewer.group.evidence[viewer.evidenceIndex]?.page_number} 页`} />}</div></ScrollArea></DialogContent></Dialog>
  </div>
}

const screenshotStatus: Record<ScreenshotGroup['status'], { value: string; label: string }> = {
  evidence_pending: { value: 'queued', label: '等待页面证据' },
  evidence_running: { value: 'running', label: '页面证据采集中' },
  waiting_for_sentiment: { value: 'queued', label: '等待舆情结论' },
  rendering: { value: 'running', label: '成果生成中' },
  ready: { value: 'success', label: '成果就绪' },
  empty: { value: 'success', label: '空页面成果' },
  failed: { value: 'failed', label: '生成失败' },
  not_collected: { value: 'unknown', label: '历史批次未采集' },
  not_applicable: { value: 'unknown', label: 'URL 清单不适用' },
}

const analysisStatusNames: Record<AnalysisStatus, string> = {
  analysis_queued: '等待分析', analysis_running: '分析中', analysis_completed: '分析成功', analysis_partial: '分析不完整', analysis_failed: '分析失败', analysis_paused: '分析暂停', analysis_disabled: '分析禁用',
}
const sentimentNames: Record<SentimentResult, string> = { negative: '负面', non_negative: '非负面', unrelated: '不相关' }
const sentimentSourceNames = { ai: 'AI', manual: '人工', inherited_manual: '继承人工' }
const categoryNames: Record<string, string> = { product_complaint: '产品客诉', product_criticism: '产品吐槽', service_complaint: '服务投诉', brand_criticism: '品牌吐槽', competitor_attack: '竞品攻击', other: '其他' }
const sentimentModelNames: Record<string, string> = {
  'qwen3.5-omni-plus-2026-03-15': '千问 Omni Plus（云端多模态）',
  'deepseek-v4-flash': 'DeepSeek V4 Flash（云端文字）',
  'paddlenlp-local-text-nano-v1': 'PaddleNLP 本地轻量文字分析（Nano）',
}
const modalityStatusNames: Record<string, string> = {
  absent: '无输入', processed: '已分析', speech: '有语音', silent: '静音', no_speech: '无语音',
  inaccessible: '不可访问', unrecognizable: '无法识别', unprocessed: '未处理', not_requested: '未参与分析',
}
const categories = Object.keys(categoryNames)

function modalityStatusName(status?: string, fallback?: string) {
  const value = status ?? fallback
  return value ? (modalityStatusNames[value] ?? value) : '未报告'
}

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
  const forumIdentity = postForumIdentity(post)
  return <div className='space-y-6 p-6'>
    <div className='grid gap-3 rounded-xl border bg-muted/20 p-4 sm:grid-cols-2'><Meta label='发现来源' value={[post.source_name || post.circle_name, post.list_order_name].filter(Boolean).join(' · ')} />{forumIdentity.crossForum && <Meta label='原始归属' value={`跨论坛聚合 · 论坛 ID ${forumIdentity.canonicalBbsId ?? '未知'}`} />}<Meta label='作者' value={post.author} /><Meta label='发布时间' value={formatDate(post.published_at)} /><Meta label='平台帖子 ID' value={post.platform_post_id} /></div>
    <section className='space-y-3 rounded-xl border p-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'><div><div className='flex items-center gap-2'><BrainCircuit className='size-4 text-primary' /><h3 className='text-sm font-semibold'>舆情反馈</h3></div><div className='mt-2 flex flex-wrap gap-1.5'>{post.sentiment_result ? <><StatusBadge value={post.sentiment_result === 'negative' ? 'failed' : post.sentiment_result === 'non_negative' ? 'success' : 'unknown'} label={sentimentNames[post.sentiment_result]} />{post.sentiment_source && <Badge variant='outline'>{sentimentSourceNames[post.sentiment_source]}</Badge>}</> : post.analysis_status ? <StatusBadge value={post.analysis_status === 'analysis_failed' ? 'failed' : post.analysis_status === 'analysis_running' ? 'running' : 'unknown'} label={analysisStatusNames[post.analysis_status]} /> : <Badge variant='outline'>未建立分析任务</Badge>}</div></div>{sentiment?.can_manual_correct && <Button variant='outline' size='sm' onClick={onCorrect}><PencilLine className='size-4' />{manualActionName}</Button>}</div>
      {sentiment?.summary && <div><div className='mb-1 text-xs font-medium text-muted-foreground'>中文总结</div><div className='whitespace-pre-wrap text-sm leading-7'>{sentiment.summary}</div></div>}
      {sentiment?.matched_subjects.length ? <div className='flex flex-wrap gap-1.5'>{sentiment.matched_subjects.map((item) => <Badge key={item} variant='secondary'>{item}</Badge>)}</div> : null}
      {sentiment?.primary_category && <div className='text-sm'>主要类型：<Badge variant='outline'>{categoryNames[sentiment.primary_category] ?? sentiment.primary_category}</Badge>{sentiment.secondary_categories.length ? <span className='ml-2 text-muted-foreground'>次要类型：{sentiment.secondary_categories.map((item) => categoryNames[item] ?? item).join('、')}</span> : null}</div>}
      {sentiment?.modalities && <div className='grid gap-3 md:grid-cols-2'><div className='rounded-lg bg-muted/30 p-3'><div className='mb-2 text-xs font-medium text-muted-foreground'>文字依据 · {modalityStatusName(sentiment.modalities.text.status)}</div><EvidenceList values={sentiment.modalities.text.evidence} /></div>{post.image_urls.map((url, index) => { const item = sentiment.modalities?.image.items.find((value) => value.input_index === index); const skipped = sentiment.modalities?.image.status === 'not_requested'; return <div key={url} className='space-y-2 rounded-lg bg-muted/30 p-3'><div className='text-xs font-medium text-muted-foreground'>图片 {index + 1} · {modalityStatusName(item?.status, sentiment.modalities?.image.status)}</div><img src={url} loading='lazy' referrerPolicy='no-referrer' className='max-h-72 w-full rounded-lg border object-contain' alt={`帖子图片 ${index + 1}`} />{!skipped && <EvidenceList values={item?.evidence} />}</div> })}{post.video_urls.length > 0 && <VideoMedia key={post.id} runId={runId} post={post} sentiment={sentiment} />}</div>}
      {(post.image_urls.length > 0 || post.video_urls.length > 0) && !sentiment?.modalities && <div className='grid gap-3 md:grid-cols-2'>{post.image_urls.map((url, index) => <img key={url} src={url} loading='lazy' referrerPolicy='no-referrer' className='max-h-72 w-full rounded-lg border object-contain' alt={`帖子图片 ${index + 1}`} />)}{post.video_urls.length > 0 && <VideoMedia key={post.id} runId={runId} post={post} sentiment={sentiment} />}</div>}
      {sentiment?.error_message && <Alert variant='destructive'><AlertTitle>{analysisStatusNames[sentiment.analysis_status ?? 'analysis_failed']}</AlertTitle><AlertDescription>{sentiment.error_message}</AlertDescription></Alert>}
      {sentiment?.model_code && <div className='text-xs text-muted-foreground'>模型：{sentimentModelNames[sentiment.model_code] ?? sentiment.model_code}{sentiment.updated_at ? ` · 更新时间：${formatDate(sentiment.updated_at)}` : ''}{sentiment.duration_ms !== undefined ? ` · ${sentiment.duration_ms} ms` : ''}</div>}
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
    {urls.map((url, index) => { const visual = sentiment?.modalities?.video_visual.items.find((value) => value.input_index === index); const audio = sentiment?.modalities?.video_audio.items.find((value) => value.input_index === index); const skipped = sentiment?.modalities?.video_visual.status === 'not_requested' && sentiment?.modalities?.video_audio.status === 'not_requested'; return <div key={url} className='space-y-2'><div className='text-xs font-medium text-muted-foreground'>视频 {index + 1} · 画面 {modalityStatusName(visual?.status, sentiment?.modalities?.video_visual.status)} · 音频 {modalityStatusName(audio?.status, sentiment?.modalities?.video_audio.status)}</div><video controls preload='auto' playsInline src={url} className='max-h-96 w-full rounded-lg border'>当前浏览器未能播放该视频。</video>{sentiment?.modalities && !skipped && <div className='grid gap-3 md:grid-cols-2'><div><div className='mb-1 text-xs text-muted-foreground'>画面依据</div><EvidenceList values={visual?.evidence} /></div><div><div className='mb-1 text-xs text-muted-foreground'>音频依据</div><EvidenceList values={audio?.evidence} /></div></div>}</div> })}
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

function postForumIdentity(post: Post) {
  const raw = post.raw_status
  const canonicalBbsId = raw?.bbs_id
  return {
    crossForum: raw?.cross_forum_aggregate === true,
    canonicalBbsId: typeof canonicalBbsId === 'string' || typeof canonicalBbsId === 'number' ? String(canonicalBbsId) : undefined,
  }
}

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
  const failuresRecovered = task.status === 'success' && task.completed_count >= task.target_count
  const hasIssue = task.status === 'failed' || (task.failed_count > 0 && !failuresRecovered)

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
        {task.failed_count > 0 && <div className={cn('text-right text-[11px] font-medium', failuresRecovered ? 'text-muted-foreground' : 'text-destructive')}>{failuresRecovered ? `跳过 ${task.failed_count} 个异常候选` : `${task.failed_count} 项失败`}</div>}
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
