import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { ChevronLeft, ChevronRight, CircleAlert, FilterX, KeyRound, RefreshCw } from 'lucide-react'
import { AuthDialog } from '@/features/auth/auth-dialog'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { NewExtractionSheet } from './new-extraction-sheet'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { api, errorMessage, formatDate, platformName, queryString, shanghaiDayBoundary } from '@/lib/api'
import type { PageResult, Run } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type SearchState = {
  page?: number
  pageSize?: 20 | 50 | 100
  number?: string
  status?: 'queued' | 'running' | 'waiting_for_auth' | 'success' | 'partial_success' | 'failed'
  trigger?: 'manual' | 'scheduled'
  listOrder?: 'latest_reply' | 'latest_publish'
  from?: string
  to?: string
}

const column = createColumnHelper<Run>()

type RunListKind = 'extraction' | 'recurring'

export function RunsPage() {
  return <RunListPage kind='extraction' />
}

export function RecurringRunsPage() {
  return <RunListPage kind='recurring' />
}

function RunListPage({ kind }: { kind: RunListKind }) {
  const recurring = kind === 'recurring'
  const listPath = recurring ? '/recurring-runs' as const : '/runs' as const
  const detailPath = recurring ? '/recurring-runs/$runId' as const : '/runs/$runId' as const
  const rawSearch = useSearch({ strict: false }) as SearchState
  const navigate = useNavigate()
  const search = { ...rawSearch, page: rawSearch.page ?? 1, pageSize: rawSearch.pageSize ?? 50 }
  const [authRun, setAuthRun] = useState<Run>()
  const [highlightedRunId, setHighlightedRunId] = useState<string>()
  const debouncedNumber = useDebouncedValue(search.number)
  useEffect(() => {
    let timer: number | undefined
    const highlight = (event: Event) => {
      setHighlightedRunId((event as CustomEvent<string>).detail)
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setHighlightedRunId(undefined), 2600)
    }
    window.addEventListener('threadsnap:new-run', highlight)
    return () => { window.removeEventListener('threadsnap:new-run', highlight); window.clearTimeout(timer) }
  }, [])
  const offset = ((search.page ?? 1) - 1) * (search.pageSize ?? 50)
  const query = useQuery({
    queryKey: ['runs', kind, { ...search, number: debouncedNumber }],
    queryFn: () => api<PageResult<Run>>(`/runs${queryString({
      offset,
      limit: search.pageSize,
      number: debouncedNumber,
      status: search.status,
      trigger_types: recurring ? ['recurring'] : search.trigger ? [search.trigger] : ['manual', 'scheduled'],
      list_order: search.listOrder,
      created_from: search.from ? shanghaiDayBoundary(search.from) : undefined,
      created_to: search.to ? shanghaiDayBoundary(search.to, true) : undefined,
    })}`, undefined, 20_000),
    refetchInterval: (current) => current.state.data?.items.some(isActiveRun) ? 3_000 : 60_000,
  })

  function patch(values: Partial<SearchState>) {
    const next = { ...rawSearch, ...values }
    navigate({
      to: listPath,
      search: {
        page: next.page,
        pageSize: next.pageSize,
        number: next.number,
        status: next.status,
        trigger: next.trigger,
        listOrder: next.listOrder,
        from: next.from,
        to: next.to,
      },
      replace: true,
      resetScroll: false,
    })
  }

  const columns = useMemo(() => [
    column.display({ id: 'index', header: () => <span className='block text-center'>序号</span>, cell: ({ row }) => <span className='block text-center tabular-nums text-muted-foreground'>{offset + row.index + 1}</span> }),
    column.accessor('number', { header: '批次编号', cell: (info) => <div><div className='font-medium'>{info.getValue()}</div><div className='mt-1 text-xs text-muted-foreground'>{info.row.original.trigger_type_name}</div></div> }),
    column.display({ id: 'scope', header: '提取范围', cell: ({ row }) => <div className='max-w-64'><div className='truncate text-sm'>{row.original.source_names?.join('、') || row.original.circle_names?.join('、') || `${row.original.circle_count} 个任务`}</div><div className='mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground'><span>{row.original.platform_codes?.map(platformName).join('、') || `${row.original.platform_count} 个平台`}</span>{row.original.list_order_names?.map((name) => <Badge key={name} variant='outline' className='h-5 px-1.5 text-[11px] font-normal'>{name}</Badge>)}</div></div> }),
    column.accessor('status', { header: '状态', cell: ({ row }) => <StatusBadge value={row.original.status} label={row.original.status_name} /> }),
    column.display({ id: 'progress', header: '进度', cell: ({ row }) => { const run = row.original; const percent = run.planned_count ? Math.min(100, Math.round(((run.completed_count + run.failed_count) / run.planned_count) * 100)) : 0; const screenshot = run.screenshot_summary; const reachedTarget = run.status === 'success' && run.completed_count >= run.planned_count; return <div className='w-40 space-y-1.5'><div className='flex justify-between text-xs'><span>{run.completed_count} / {run.planned_count}</span><span className='text-muted-foreground'>{percent}%</span></div><Progress value={percent} className='h-1.5' />{run.failed_count > 0 && !reachedTarget && <div className='text-[11px] text-red-600 dark:text-red-300'>{run.failed_count} 项失败</div>}{screenshot && screenshot.status !== 'not_applicable' && <div className='text-[11px] text-muted-foreground'>截图：{runScreenshotStatusNames[screenshot.status] ?? screenshot.status}{screenshot.group_count > 0 ? ` ${screenshot.ready_count}/${screenshot.group_count}` : ''}</div>}</div> } }),
    column.display({ id: 'time', header: '时间', cell: ({ row }) => <div className='whitespace-nowrap text-sm'><div>{formatDate(row.original.created_at)}</div><div className='mt-1 text-xs text-muted-foreground'>{row.original.finished_at ? `完成 ${formatDate(row.original.finished_at)}` : row.original.queue_position ? `队列第 ${row.original.queue_position} 位` : '进行中'}</div></div> }),
    column.display({ id: 'action', header: () => <span className='sr-only'>操作</span>, cell: ({ row }) => <div className='flex justify-end gap-1'>{row.original.status === 'waiting_for_auth' && <Button variant='outline' size='sm' onClick={(event) => { event.stopPropagation(); setAuthRun(row.original) }}><KeyRound className='size-4' />处理会话</Button>}<Button variant='ghost' size='sm' onClick={(event) => { event.stopPropagation(); navigate({ to: detailPath, params: { runId: row.original.id }, search: emptyDetailSearch }) }}>查看</Button></div> }),
  ], [detailPath, navigate, offset])
  const table = useReactTable({ data: query.data?.items ?? [], columns, getCoreRowModel: getCoreRowModel() })
  const totalPages = Math.max(1, Math.ceil((query.data?.total ?? 0) / (search.pageSize ?? 50)))

  return (
    <div className='flex h-full min-h-0 flex-col gap-4'>
      <div className='shrink-0 space-y-4'>
        <PageHeader title={recurring ? '循环计划列表' : '提取列表'} description={recurring ? '只查看循环计划触发的独立批次，页面能力与定时批次保持一致。' : '查看手动与定时提取批次，状态变化由 SSE 通知并回查权威接口。'} actions={recurring ? undefined : <NewExtractionSheet />} />
        <Card className='border-border/70 bg-card/88 py-0 shadow-sm backdrop-blur'>
          <CardContent className={`grid gap-3 p-3 md:grid-cols-2 ${recurring ? 'xl:grid-cols-3 2xl:grid-cols-[minmax(220px,1fr)_160px_160px_150px_150px_auto]' : 'xl:grid-cols-4 2xl:grid-cols-[minmax(220px,1fr)_160px_160px_160px_150px_150px_auto]'}`}>
            <Input value={search.number ?? ''} onChange={(event) => patch({ number: event.target.value || undefined, page: 1 })} placeholder='搜索批次编号' aria-label='搜索批次编号' />
            <Select value={search.status ?? 'all'} onValueChange={(value) => patch({ status: value === 'all' ? undefined : value as SearchState['status'], page: 1 })}><SelectTrigger><SelectValue placeholder='全部状态' /></SelectTrigger><SelectContent><SelectItem value='all'>全部状态</SelectItem><SelectItem value='queued'>排队中</SelectItem><SelectItem value='running'>提取中</SelectItem><SelectItem value='waiting_for_auth'>等待平台会话</SelectItem><SelectItem value='success'>成功</SelectItem><SelectItem value='partial_success'>部分成功</SelectItem><SelectItem value='failed'>失败</SelectItem></SelectContent></Select>
            {!recurring && <Select value={search.trigger ?? 'all'} onValueChange={(value) => patch({ trigger: value === 'all' ? undefined : value as SearchState['trigger'], page: 1 })}><SelectTrigger><SelectValue placeholder='全部触发方式' /></SelectTrigger><SelectContent><SelectItem value='all'>全部触发方式</SelectItem><SelectItem value='manual'>手动触发</SelectItem><SelectItem value='scheduled'>定时提取</SelectItem></SelectContent></Select>}
            <Select value={search.listOrder ?? 'all'} onValueChange={(value) => patch({ listOrder: value === 'all' ? undefined : value as SearchState['listOrder'], page: 1 })}><SelectTrigger><SelectValue placeholder='全部列表类型' /></SelectTrigger><SelectContent><SelectItem value='all'>全部列表类型</SelectItem><SelectItem value='latest_reply'>最新回复</SelectItem><SelectItem value='latest_publish'>最新发布</SelectItem></SelectContent></Select>
            <Input type='date' value={search.from ?? ''} onChange={(event) => patch({ from: event.target.value || undefined, page: 1 })} aria-label='开始日期' />
            <Input type='date' value={search.to ?? ''} onChange={(event) => patch({ to: event.target.value || undefined, page: 1 })} aria-label='结束日期' />
            <div className='flex gap-1'><Button variant='outline' size='icon' onClick={() => query.refetch()} aria-label='刷新列表'><RefreshCw className={`size-4 ${query.isFetching ? 'animate-spin' : ''}`} /></Button><Button variant='ghost' size='icon' onClick={() => navigate({ to: listPath, search: emptyRunsSearch, replace: true, resetScroll: false })} aria-label='重置筛选'><FilterX className='size-4' /></Button></div>
          </CardContent>
        </Card>
      </div>
      <div className='flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border/70 bg-card/90 shadow-sm backdrop-blur'>
        <div className='min-h-0 flex-1 overflow-auto' data-list-viewport='runs'>
          <Table className='min-w-[1050px]'>
            <TableHeader>{table.getHeaderGroups().map((group) => <TableRow key={group.id} className='bg-muted/35'>{group.headers.map((header) => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
            <TableBody>
              {query.isLoading ? Array.from({ length: 6 }).map((_, index) => <TableRow key={index}>{columns.map((_, cell) => <TableCell key={cell}><Skeleton className='h-7 w-full' /></TableCell>)}</TableRow>) : query.isError ? <TableRow><TableCell colSpan={columns.length} className='h-56 text-center'><CircleAlert className='mx-auto mb-2 size-5 text-destructive' /><div className='text-sm font-medium'>{recurring ? '循环计划列表加载失败' : '提取列表加载失败'}</div><div className='mt-1 text-xs text-muted-foreground'>{errorMessage(query.error)}</div><Button className='mt-3' variant='outline' size='sm' onClick={() => query.refetch()}><RefreshCw className='size-4' />重新加载</Button></TableCell></TableRow> : table.getRowModel().rows.length ? table.getRowModel().rows.map((row) => <TableRow key={row.id} tabIndex={0} className={`cursor-pointer transition-colors hover:bg-primary/[0.035] focus-visible:bg-primary/[0.06] focus-visible:outline-none ${row.original.id === highlightedRunId ? 'run-row-highlight' : ''}`} onClick={() => navigate({ to: detailPath, params: { runId: row.original.id }, search: emptyDetailSearch })} onKeyDown={(event) => { if (event.key === 'Enter') navigate({ to: detailPath, params: { runId: row.original.id }, search: emptyDetailSearch }) }}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>) : <TableRow><TableCell colSpan={columns.length} className='h-56 text-center'><div className='text-sm font-medium'>{recurring ? '还没有循环计划批次' : '没有匹配的提取批次'}</div><div className='mt-1 text-xs text-muted-foreground'>{recurring ? '循环计划触发后，批次会显示在这里。' : '调整筛选条件或创建新的提取任务。'}</div></TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
        <div className='flex shrink-0 flex-col gap-3 border-t bg-card/95 p-4 sm:flex-row sm:items-center sm:justify-between' data-list-footer='runs'>
          <div className='text-sm text-muted-foreground'>{query.isLoading ? '正在加载批次…' : query.isError ? '批次加载失败' : `共 ${query.data?.total ?? 0} 个批次，第 ${search.page} / ${totalPages} 页`}</div>
          <div className='flex items-center gap-2'><Select value={String(search.pageSize)} onValueChange={(value) => patch({ pageSize: Number(value) as 20 | 50 | 100, page: 1 })}><SelectTrigger className='w-28'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='20'>每页 20</SelectItem><SelectItem value='50'>每页 50</SelectItem><SelectItem value='100'>每页 100</SelectItem></SelectContent></Select><Button variant='outline' size='icon' disabled={(search.page ?? 1) <= 1} onClick={() => patch({ page: (search.page ?? 1) - 1 })} aria-label='上一页'><ChevronLeft className='size-4' /></Button><Button variant='outline' size='icon' disabled={(search.page ?? 1) >= totalPages} onClick={() => patch({ page: (search.page ?? 1) + 1 })} aria-label='下一页'><ChevronRight className='size-4' /></Button></div>
        </div>
      </div>
      <AuthDialog open={Boolean(authRun)} onOpenChange={(open) => !open && setAuthRun(undefined)} platformCode={authRun?.waiting_platform_codes?.[0] ?? authRun?.platform_codes?.[0]} runId={authRun?.id} freshOnOpen />
    </div>
  )
}

const emptyRunsSearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, listOrder: undefined, from: undefined, to: undefined }
const emptyDetailSearch = { view: undefined, page: undefined, pageSize: undefined, title: undefined, sources: undefined, visibility: undefined, sentiment: undefined, analysisStatus: undefined, sort: undefined, direction: undefined, post: undefined }

const runScreenshotStatusNames: Record<string, string> = { evidence_pending: '待采集', evidence_running: '采集中', waiting_for_sentiment: '待判定', rendering: '生成中', ready: '已就绪', empty: '空成果', failed: '失败', not_collected: '历史未采集' }

function isActiveRun(run: Run) {
  return ['queued', 'running', 'waiting_for_auth'].includes(run.status)
}
