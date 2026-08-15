import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CircleStop, ChevronLeft, ChevronRight, Copy, Download, ExternalLink, KeyRound, LoaderCircle, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { AuthDialog } from '@/features/auth/auth-dialog'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { api, errorMessage, formatDate, platformName, queryString } from '@/lib/api'
import type { PageResult, Post, PostNavigation, Run, Template } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

type SearchState = { page?: number; pageSize?: 20 | 50 | 100; title?: string; circle?: string; visibility?: 'visible' | 'hidden' | 'unknown'; sort?: 'source' | 'published_at' | 'reply_count' | 'like_count'; direction?: 'asc' | 'desc'; post?: string }
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
  const [manualCopy, setManualCopy] = useState<string>()
  const [postSwitch, setPostSwitch] = useState<PostSwitch>()
  const detailBackgroundScroll = useRef(0)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const debouncedTitle = useDebouncedValue(search.title)
  const debouncedCircle = useDebouncedValue(search.circle)
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api<Run>(`/runs/${runId}`), refetchInterval: 60_000 })
  const postQueryValues = { title: debouncedTitle, circle: debouncedCircle, visibility: search.visibility, sort_by: search.sort, sort_direction: search.direction }
  const posts = useQuery({
    queryKey: ['posts', runId, { page: search.page, pageSize: search.pageSize, ...postQueryValues }],
    queryFn: () => api<PageResult<Post>>(`/runs/${runId}/posts${queryString({ offset: ((search.page ?? 1) - 1) * (search.pageSize ?? 50), limit: search.pageSize, ...postQueryValues })}`),
  })
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates') })
  const detail = useQuery({
    queryKey: ['post', runId, search.post],
    queryFn: () => api<Post>(`/runs/${runId}/posts/${search.post}`),
    enabled: Boolean(search.post),
    placeholderData: keepPreviousData,
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

  function patch(values: Partial<SearchState>, options?: { resetScroll?: boolean }) {
    navigate({
      to: '/runs/$runId',
      params: { runId },
      search: (previous) => ({ ...previous, ...values }),
      replace: true,
      resetScroll: options?.resetScroll,
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
    detailBackgroundScroll.current = window.scrollY
    detailTrigger.current = trigger
    patch({ post: postId }, { resetScroll: false })
  }

  function handleDetailOpenAutoFocus(event: Event) {
    event.preventDefault()
    if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus({ preventScroll: true })
    window.scrollTo(window.scrollX, detailBackgroundScroll.current)
  }

  function handleDetailCloseAutoFocus(event: Event) {
    event.preventDefault()
    detailTrigger.current?.focus({ preventScroll: true })
    window.scrollTo(window.scrollX, detailBackgroundScroll.current)
  }
  function moveToPost(postId: string | undefined, position: number, direction: PostSwitch['direction']) {
    if (!postId || postSwitch) return
    setPostSwitch({ id: postId, direction })
    const page = Math.ceil(position / (search.pageSize ?? 50))
    patch({ post: postId, page }, { resetScroll: false })
  }

  const totalPages = Math.max(1, Math.ceil((posts.data?.total ?? 0) / (search.pageSize ?? 50)))
  const canRetry = run.data?.status === 'failed' || run.data?.status === 'partial_success'
  const canDelete = ['success', 'partial_success', 'failed'].includes(run.data?.status ?? '')
  const inputModeName = run.data?.input_mode === 'url_list' ? 'URL 清单' : '圈子发现'

  return (
    <div className='space-y-6'>
      <Button variant='ghost' className='-ml-2' onClick={() => navigate({ to: '/runs', search: emptyRunsSearch })}><ArrowLeft className='size-4' />返回提取列表</Button>
      <PageHeader title={run.data ? `批次 ${run.data.number}` : '批次链接详情'} description='结果按原始来源位置稳定合并；搜索、筛选、排序和分页均由后端对完整结果集执行。' actions={<><Button variant='outline' onClick={() => { run.refetch(); posts.refetch() }}><RefreshCw className={`size-4 ${run.isFetching || posts.isFetching ? 'animate-spin' : ''}`} />刷新</Button>{run.data?.status === 'waiting_for_auth' && <><Button variant='outline' onClick={() => setAuthOpen(true)}><KeyRound className='size-4' />去认证</Button><AlertDialog><AlertDialogTrigger asChild><Button variant='outline'><CircleStop className='size-4' />结束本次提取</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>结束本次提取？</AlertDialogTitle><AlertDialogDescription>已有结果将保留，批次按实际结果结束并释放平台队列；之后仍可重新提取失败项。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => endAuthWait.mutate()}>确认结束</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></>}{canRetry && <AlertDialog><AlertDialogTrigger asChild><Button variant='outline'>重新提取失败项</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>重新提取失败项？</AlertDialogTitle><AlertDialogDescription>系统会保留原批次快照，只把失败 URL 创建为关联补提批次。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => retry.mutate()}>确认重新提取</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}{canDelete && <AlertDialog><AlertDialogTrigger asChild><Button variant='ghost' className='text-destructive hover:text-destructive'><Trash2 className='size-4' />永久删除</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>永久删除该批次？</AlertDialogTitle><AlertDialogDescription>批次、帖子快照、一级评论和已生成导出记录都会一并删除，此操作不可撤回。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => deleteRun.mutate()}>确认永久删除</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>}</>} />
      {run.isLoading ? <Skeleton className='h-36 rounded-xl' /> : run.data && <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-5'>{[
        ['状态', <StatusBadge key='status' value={run.data.status} label={run.data.status_name} />],
        ['触发方式', `${run.data.trigger_type_name} · ${inputModeName}`],
        ['结果进度', `${run.data.completed_count} / ${run.data.planned_count}`],
        ['失败项', String(run.data.failed_count)],
        ['创建时间', formatDate(run.data.created_at)],
      ].map(([label, value]) => <Card key={String(label)} className='border-border/70 bg-card/88'><CardContent className='p-4'><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-2 text-sm font-semibold'>{value}</div></CardContent></Card>)}</div>}
      {run.data?.waiting_reason && <Alert><KeyRound className='size-4' /><AlertTitle>等待平台认证</AlertTitle><AlertDescription>{run.data.waiting_reason}</AlertDescription></Alert>}
      {run.data?.error_message && <Alert variant='destructive'><AlertTitle>批次错误</AlertTitle><AlertDescription>{run.data.error_message}</AlertDescription></Alert>}
      {run.data?.tasks?.length ? <Card className='border-border/70 bg-card/88'><CardContent className='p-0'><div className='border-b px-5 py-4'><h2 className='font-semibold'>圈子任务</h2><p className='mt-1 text-sm text-muted-foreground'>展示每个平台圈子的独立进度、状态与后端错误。</p></div><div className='overflow-x-auto'><Table className='min-w-[820px]'><TableHeader><TableRow><TableHead>平台</TableHead><TableHead>圈子</TableHead><TableHead>状态</TableHead><TableHead>进度</TableHead><TableHead>错误详情</TableHead></TableRow></TableHeader><TableBody>{run.data.tasks.map((task) => <TableRow key={task.id}><TableCell>{platformName(task.platform_code)}</TableCell><TableCell><div className='font-medium'>{task.circle_name || task.external_id}</div><div className='max-w-72 truncate text-xs text-muted-foreground'>{task.circle_url}</div></TableCell><TableCell><StatusBadge value={task.status} label={task.status_name} /></TableCell><TableCell className='tabular-nums'>{task.completed_count} / {task.target_count}{task.failed_count ? ` · ${task.failed_count} 项失败` : ''}</TableCell><TableCell className='max-w-80 text-sm text-muted-foreground'>{task.error_message || task.stop_reason || '—'}</TableCell></TableRow>)}</TableBody></Table></div></CardContent></Card> : null}
      <Card className='border-border/70 bg-card/88'><CardContent className='grid gap-3 p-4 lg:grid-cols-[1fr_220px_170px_180px_140px_auto]'><Input placeholder='搜索帖子标题' value={search.title ?? ''} onChange={(event) => patch({ title: event.target.value || undefined, page: 1 })} /><Input placeholder='搜索圈子' value={search.circle ?? ''} onChange={(event) => patch({ circle: event.target.value || undefined, page: 1 })} /><Select value={search.visibility ?? 'all'} onValueChange={(value) => patch({ visibility: value === 'all' ? undefined : value as SearchState['visibility'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='all'>全部可见状态</SelectItem><SelectItem value='visible'>可见</SelectItem><SelectItem value='hidden'>不可见</SelectItem><SelectItem value='unknown'>未知</SelectItem></SelectContent></Select><Select value={search.sort} onValueChange={(value) => patch({ sort: value as SearchState['sort'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='source'>来源顺序</SelectItem><SelectItem value='published_at'>发布时间</SelectItem><SelectItem value='reply_count'>评论数</SelectItem><SelectItem value='like_count'>点赞数</SelectItem></SelectContent></Select><Select value={search.direction} onValueChange={(value) => patch({ direction: value as SearchState['direction'], page: 1 })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value='asc'>正序</SelectItem><SelectItem value='desc'>倒序</SelectItem></SelectContent></Select><Button variant='outline' onClick={copyAll}><Copy className='size-4' />复制全部</Button></CardContent></Card>
      <div className='overflow-hidden rounded-xl border border-border/70 bg-card/90'><div className='overflow-x-auto'><Table className='min-w-[1050px]'><TableHeader><TableRow className='bg-muted/35'><TableHead>标题</TableHead><TableHead>圈子</TableHead><TableHead>作者</TableHead><TableHead>发布时间</TableHead><TableHead>可见状态</TableHead><TableHead className='text-right'>评论数</TableHead><TableHead className='text-right'>点赞数</TableHead><TableHead className='text-right'>操作</TableHead></TableRow></TableHeader><TableBody>{posts.isLoading ? Array.from({ length: 6 }).map((_, index) => <TableRow key={index}>{Array.from({ length: 8 }).map((__, cell) => <TableCell key={cell}><Skeleton className='h-6 w-full' /></TableCell>)}</TableRow>) : posts.data?.items.length ? posts.data.items.map((post) => <TableRow key={post.id}><TableCell className='max-w-80'><a href={post.url} target='_blank' rel='noreferrer' className='flex items-center gap-1.5 truncate font-medium hover:text-primary hover:underline'>{post.title || '无标题'}<ExternalLink className='size-3 shrink-0' /></a></TableCell><TableCell>{post.circle_name || '—'}</TableCell><TableCell>{post.author || '—'}</TableCell><TableCell className='whitespace-nowrap'>{formatDate(post.published_at)}</TableCell><TableCell><StatusBadge value={post.visibility} label={{ visible: '可见', hidden: '不可见', unknown: '未知' }[post.visibility]} /></TableCell><TableCell className='text-right tabular-nums'>{post.reply_count ?? '—'}</TableCell><TableCell className='text-right tabular-nums'>{post.like_count ?? '—'}</TableCell><TableCell><div className='flex justify-end gap-1'><Button variant='ghost' size='sm' onClick={(event) => openPost(post.id, event.currentTarget)}>查看</Button><Button variant='ghost' size='icon' onClick={() => copyText(post.url)} aria-label='复制帖子链接'><Copy className='size-4' /></Button></div></TableCell></TableRow>) : <TableRow><TableCell colSpan={8} className='h-52 text-center text-muted-foreground'>当前筛选条件下没有帖子结果。</TableCell></TableRow>}</TableBody></Table></div><div className='flex flex-col gap-3 border-t p-4 sm:flex-row sm:items-center sm:justify-between'><div className='text-sm text-muted-foreground'>共 {posts.data?.total ?? 0} 条，第 {search.page} / {totalPages} 页</div><div className='flex gap-2'><Select value={String(search.pageSize)} onValueChange={(value) => patch({ pageSize: Number(value) as 20 | 50 | 100, page: 1 })}><SelectTrigger className='w-28'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='20'>每页 20</SelectItem><SelectItem value='50'>每页 50</SelectItem><SelectItem value='100'>每页 100</SelectItem></SelectContent></Select><Button variant='outline' size='icon' disabled={(search.page ?? 1) <= 1} onClick={() => patch({ page: (search.page ?? 1) - 1 })}><ChevronLeft className='size-4' /></Button><Button variant='outline' size='icon' disabled={(search.page ?? 1) >= totalPages} onClick={() => patch({ page: (search.page ?? 1) + 1 })}><ChevronRight className='size-4' /></Button></div></div></div>
      <div className='flex justify-end'><Select onValueChange={(value) => exportRun.mutate(value)} disabled={!templates.data?.length || exportRun.isPending}><SelectTrigger className='w-56'><Download className='size-4' /><SelectValue placeholder={templates.data?.length ? '导出 Excel' : '暂无导出模板'} /></SelectTrigger><SelectContent>{templates.data?.map((item) => item.versions[0] && <SelectItem key={item.versions[0].version_id} value={item.versions[0].version_id}>{item.name}</SelectItem>)}</SelectContent></Select></div>
      <Sheet open={Boolean(search.post)} onOpenChange={(open) => { if (!open) { setPostSwitch(undefined); patch({ post: undefined }, { resetScroll: false }) } }}>
        <SheetContent className='w-full overflow-y-auto p-0 sm:max-w-[58vw]' onOpenAutoFocus={handleDetailOpenAutoFocus} onCloseAutoFocus={handleDetailCloseAutoFocus}>
          <SheetHeader className='sticky top-0 z-10 border-b bg-background/90 p-6 backdrop-blur'>
            <div className='flex items-start justify-between gap-4 pr-8'>
              <div>
                <SheetTitle>{detail.data?.title || '帖子快照详情'}</SheetTitle>
                <SheetDescription className='mt-1'>数据库快照，不会在打开时重新访问平台。{navigation.data && ` 当前为筛选结果第 ${navigation.data.position} / ${navigation.data.total} 条。`}</SheetDescription>
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
          {detail.isLoading ? <div className='space-y-4 p-6'><Skeleton className='h-10 w-2/3' /><Skeleton className='h-72 w-full' /></div> : detail.data && <div className='space-y-6 p-6'><div className='grid gap-3 rounded-xl border bg-muted/20 p-4 sm:grid-cols-2'><Meta label='圈子' value={detail.data.circle_name} /><Meta label='作者' value={detail.data.author} /><Meta label='发布时间' value={formatDate(detail.data.published_at)} /><Meta label='平台帖子 ID' value={detail.data.platform_post_id} /></div><div><h3 className='mb-2 text-sm font-semibold'>正文快照</h3><div className='whitespace-pre-wrap rounded-xl border bg-background p-4 text-sm leading-7'>{detail.data.content || '正文为空'}</div></div><div><h3 className='mb-2 text-sm font-semibold'>一级评论（{detail.data.comments.length}）</h3><div className='space-y-2'>{detail.data.comments.length ? detail.data.comments.map((comment, index) => <div key={comment.platform_comment_id || index} className='rounded-xl border p-4'><div className='flex justify-between text-xs text-muted-foreground'><span>{comment.author || '匿名用户'}</span><span>{formatDate(comment.published_at)}</span></div><p className='mt-2 whitespace-pre-wrap text-sm'>{comment.content || '—'}</p></div>) : <div className='rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground'>没有已保存的一级评论。</div>}</div></div></div>}
        </SheetContent>
      </Sheet>
      <Dialog open={manualCopy !== undefined} onOpenChange={(open) => !open && setManualCopy(undefined)}><DialogContent><DialogHeader><DialogTitle>手动复制</DialogTitle><DialogDescription>当前浏览器上下文未开放剪贴板写入，文本已全选。</DialogDescription></DialogHeader><Textarea readOnly rows={12} value={manualCopy ?? ''} onFocus={(event) => event.currentTarget.select()} autoFocus /></DialogContent></Dialog>
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} runId={runId} />
    </div>
  )
}

function Meta({ label, value }: { label: string; value?: string }) { return <div><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-1 break-all text-sm'>{value || '—'}</div></div> }

const emptyRunsSearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, from: undefined, to: undefined }
