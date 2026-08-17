import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { ChevronLeft, ChevronRight, FilterX, KeyRound, RefreshCw } from 'lucide-react'
import { AuthDialog } from '@/features/auth/auth-dialog'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { NewExtractionSheet } from './new-extraction-sheet'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { api, formatDate, platformName, queryString, shanghaiDayBoundary } from '@/lib/api'
import type { PageResult, Run } from '@/lib/types'
import { Button } from '@/components/ui/button'
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
  from?: string
  to?: string
}

const column = createColumnHelper<Run>()

export function RunsPage() {
  const rawSearch = useSearch({ strict: false }) as SearchState
  const navigate = useNavigate({ from: '/runs' })
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
    queryKey: ['runs', { ...search, number: debouncedNumber }],
    queryFn: () => api<PageResult<Run>>(`/runs${queryString({
      offset,
      limit: search.pageSize,
      number: debouncedNumber,
      status: search.status,
      trigger_type: search.trigger,
      created_from: search.from ? shanghaiDayBoundary(search.from) : undefined,
      created_to: search.to ? shanghaiDayBoundary(search.to, true) : undefined,
    })}`),
    refetchInterval: 60_000,
  })

  function patch(values: Partial<SearchState>) {
    navigate({
      to: '/runs',
      search: (previous) => ({ ...previous, ...values }),
      replace: true,
      resetScroll: false,
    })
  }

  const columns = useMemo(() => [
    column.accessor('number', { header: '批次编号', cell: (info) => <div><div className='font-medium'>{info.getValue()}</div><div className='mt-1 text-xs text-muted-foreground'>{info.row.original.trigger_type_name}</div></div> }),
    column.display({ id: 'scope', header: '提取范围', cell: ({ row }) => <div className='max-w-64'><div className='truncate text-sm'>{row.original.circle_names?.join('、') || `${row.original.circle_count} 个任务`}</div><div className='mt-1 text-xs text-muted-foreground'>{row.original.platform_codes?.map(platformName).join('、') || `${row.original.platform_count} 个平台`}</div></div> }),
    column.accessor('status', { header: '状态', cell: ({ row }) => <StatusBadge value={row.original.status} label={row.original.status_name} /> }),
    column.display({ id: 'progress', header: '进度', cell: ({ row }) => { const run = row.original; const percent = run.planned_count ? Math.min(100, Math.round(((run.completed_count + run.failed_count) / run.planned_count) * 100)) : 0; return <div className='w-40 space-y-1.5'><div className='flex justify-between text-xs'><span>{run.completed_count} / {run.planned_count}</span><span className='text-muted-foreground'>{percent}%</span></div><Progress value={percent} className='h-1.5' />{run.failed_count > 0 && <div className='text-[11px] text-red-600 dark:text-red-300'>{run.failed_count} 项失败</div>}</div> } }),
    column.display({ id: 'time', header: '时间', cell: ({ row }) => <div className='whitespace-nowrap text-sm'><div>{formatDate(row.original.created_at)}</div><div className='mt-1 text-xs text-muted-foreground'>{row.original.finished_at ? `完成 ${formatDate(row.original.finished_at)}` : row.original.queue_position ? `队列第 ${row.original.queue_position} 位` : '进行中'}</div></div> }),
    column.display({ id: 'action', header: () => <span className='sr-only'>操作</span>, cell: ({ row }) => <div className='flex justify-end gap-1'>{row.original.status === 'waiting_for_auth' && <Button variant='outline' size='sm' onClick={(event) => { event.stopPropagation(); setAuthRun(row.original) }}><KeyRound className='size-4' />去认证</Button>}<Button variant='ghost' size='sm' onClick={(event) => { event.stopPropagation(); navigate({ to: '/runs/$runId', params: { runId: row.original.id }, search: emptyDetailSearch }) }}>查看</Button></div> }),
  ], [navigate])
  const table = useReactTable({ data: query.data?.items ?? [], columns, getCoreRowModel: getCoreRowModel() })
  const totalPages = Math.max(1, Math.ceil((query.data?.total ?? 0) / (search.pageSize ?? 50)))

  return (
    <div className='flex h-full min-h-0 flex-col gap-6'>
      <div className='shrink-0 space-y-6'>
        <PageHeader title='提取列表' description='查看手动与定时提取批次，状态变化由 SSE 通知并回查权威接口。' actions={<NewExtractionSheet />} />
        <Card className='border-border/70 bg-card/88 shadow-sm backdrop-blur'>
          <CardContent className='grid gap-3 p-4 lg:grid-cols-[minmax(220px,1fr)_180px_160px_150px_150px_auto]'>
            <Input value={search.number ?? ''} onChange={(event) => patch({ number: event.target.value || undefined, page: 1 })} placeholder='搜索批次编号' aria-label='搜索批次编号' />
            <Select value={search.status ?? 'all'} onValueChange={(value) => patch({ status: value === 'all' ? undefined : value as SearchState['status'], page: 1 })}><SelectTrigger><SelectValue placeholder='全部状态' /></SelectTrigger><SelectContent><SelectItem value='all'>全部状态</SelectItem><SelectItem value='queued'>排队中</SelectItem><SelectItem value='running'>提取中</SelectItem><SelectItem value='waiting_for_auth'>等待平台认证</SelectItem><SelectItem value='success'>成功</SelectItem><SelectItem value='partial_success'>部分成功</SelectItem><SelectItem value='failed'>失败</SelectItem></SelectContent></Select>
            <Select value={search.trigger ?? 'all'} onValueChange={(value) => patch({ trigger: value === 'all' ? undefined : value as SearchState['trigger'], page: 1 })}><SelectTrigger><SelectValue placeholder='全部触发方式' /></SelectTrigger><SelectContent><SelectItem value='all'>全部触发方式</SelectItem><SelectItem value='manual'>手动触发</SelectItem><SelectItem value='scheduled'>定时提取</SelectItem></SelectContent></Select>
            <Input type='date' value={search.from ?? ''} onChange={(event) => patch({ from: event.target.value || undefined, page: 1 })} aria-label='开始日期' />
            <Input type='date' value={search.to ?? ''} onChange={(event) => patch({ to: event.target.value || undefined, page: 1 })} aria-label='结束日期' />
            <div className='flex gap-1'><Button variant='outline' size='icon' onClick={() => query.refetch()} aria-label='刷新列表'><RefreshCw className={`size-4 ${query.isFetching ? 'animate-spin' : ''}`} /></Button><Button variant='ghost' size='icon' onClick={() => navigate({ to: '/runs', search: emptyRunsSearch, replace: true, resetScroll: false })} aria-label='重置筛选'><FilterX className='size-4' /></Button></div>
          </CardContent>
        </Card>
      </div>
      <div className='min-h-0 flex-1 overflow-y-auto rounded-xl border border-border/70 bg-card/90 shadow-sm backdrop-blur'>
        <div className='overflow-x-auto'>
          <Table className='min-w-[1050px]'>
            <TableHeader>{table.getHeaderGroups().map((group) => <TableRow key={group.id} className='bg-muted/35'>{group.headers.map((header) => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
            <TableBody>
              {query.isLoading ? Array.from({ length: 6 }).map((_, index) => <TableRow key={index}>{columns.map((_, cell) => <TableCell key={cell}><Skeleton className='h-7 w-full' /></TableCell>)}</TableRow>) : table.getRowModel().rows.length ? table.getRowModel().rows.map((row) => <TableRow key={row.id} tabIndex={0} className={`cursor-pointer transition-colors hover:bg-primary/[0.035] focus-visible:bg-primary/[0.06] focus-visible:outline-none ${row.original.id === highlightedRunId ? 'run-row-highlight' : ''}`} onClick={() => navigate({ to: '/runs/$runId', params: { runId: row.original.id }, search: emptyDetailSearch })} onKeyDown={(event) => { if (event.key === 'Enter') navigate({ to: '/runs/$runId', params: { runId: row.original.id }, search: emptyDetailSearch }) }}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>) : <TableRow><TableCell colSpan={columns.length} className='h-56 text-center'><div className='text-sm font-medium'>没有匹配的提取批次</div><div className='mt-1 text-xs text-muted-foreground'>调整筛选条件或创建新的提取任务。</div></TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
        <div className='flex flex-col gap-3 border-t p-4 sm:flex-row sm:items-center sm:justify-between'>
          <div className='text-sm text-muted-foreground'>共 {query.data?.total ?? 0} 个批次，第 {search.page} / {totalPages} 页</div>
          <div className='flex items-center gap-2'><Select value={String(search.pageSize)} onValueChange={(value) => patch({ pageSize: Number(value) as 20 | 50 | 100, page: 1 })}><SelectTrigger className='w-28'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='20'>每页 20</SelectItem><SelectItem value='50'>每页 50</SelectItem><SelectItem value='100'>每页 100</SelectItem></SelectContent></Select><Button variant='outline' size='icon' disabled={(search.page ?? 1) <= 1} onClick={() => patch({ page: (search.page ?? 1) - 1 })} aria-label='上一页'><ChevronLeft className='size-4' /></Button><Button variant='outline' size='icon' disabled={(search.page ?? 1) >= totalPages} onClick={() => patch({ page: (search.page ?? 1) + 1 })} aria-label='下一页'><ChevronRight className='size-4' /></Button></div>
        </div>
      </div>
      <AuthDialog open={Boolean(authRun)} onOpenChange={(open) => !open && setAuthRun(undefined)} runId={authRun?.id} />
    </div>
  )
}

const emptyRunsSearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, from: undefined, to: undefined }
const emptyDetailSearch = { page: undefined, pageSize: undefined, title: undefined, circle: undefined, visibility: undefined, sort: undefined, direction: undefined, post: undefined }
