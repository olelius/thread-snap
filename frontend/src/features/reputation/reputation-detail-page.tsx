import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowUp, Check, CircleAlert, Clipboard, Clock3, Download, EllipsisVertical, FileArchive, FileSpreadsheet, FileText, ImageIcon, Minus, RefreshCw, RotateCcw, ShieldCheck, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { ReputationRoleLabel } from '@/features/reputation/reputation-role-label'
import { api, errorMessage, formatDate } from '@/lib/api'
import type { ReputationMetric, ReputationResult, ReputationRun } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

type SearchState = { view?: 'ranking' | 'evidence' | 'report' }

export function ReputationDetailPage() {
  const { runId } = useParams({ strict: false }) as { runId: string }
  const search = useSearch({ strict: false }) as SearchState
  const view = search.view ?? 'ranking'
  const navigate = useNavigate({ from: '/reputation/runs/$runId' })
  const queryClient = useQueryClient()
  const reduceMotion = useReducedMotion()
  const [evidenceViewer, setEvidenceViewer] = useState<ReputationResult>()
  const query = useQuery({
    queryKey: ['reputation-run', runId],
    queryFn: () => api<ReputationRun>(`/reputation/runs/${runId}`),
    refetchInterval: (value) => value.state.data && (['queued', 'running'].includes(value.state.data.status) || value.state.data.report_status === 'waiting') ? 3_000 : false,
  })
  const retry = useMutation({
    mutationFn: () => api<ReputationRun>(`/reputation/runs/${runId}/retry-failed`, { method: 'POST' }),
    onSuccess: (next) => { queryClient.invalidateQueries({ queryKey: ['reputation-runs'] }); toast.success('失败项补跑已创建', { description: `${next.number} · ${next.planned_count} 项` }); navigate({ to: '/reputation/runs/$runId', params: { runId: next.id }, search: { view: 'ranking' } }) },
    onError: (error) => toast.error('创建补跑失败', { description: errorMessage(error) }),
  })
  const remove = useMutation({
    mutationFn: () => api<{ status: string }>(`/reputation/runs/${runId}`, { method: 'DELETE' }),
    onSuccess: (job) => { queryClient.invalidateQueries({ queryKey: ['reputation-runs'] }); toast.success(job.status === 'success' ? '正式巡检关联链已删除' : '删除作业已提交', { description: `作业状态：${job.status}` }); navigate({ to: '/reputation', search: { tab: 'runs', page: undefined } }) },
    onError: (error) => toast.error('删除失败', { description: errorMessage(error) }),
  })

  if (query.isLoading) return <div className='space-y-4'><Skeleton className='h-20 w-full' /><div className='grid gap-3 md:grid-cols-4'>{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className='h-28 w-full' />)}</div><Skeleton className='h-[420px] w-full' /></div>
  if (query.isError || !query.data) return <Card className='grid h-full place-items-center'><CardContent className='text-center'><CircleAlert className='mx-auto mb-2 size-7 text-destructive' /><div className='font-medium'>巡检详情加载失败</div><div className='mt-1 text-sm text-muted-foreground'>{errorMessage(query.error)}</div><Button className='mt-4' variant='outline' onClick={() => query.refetch()}><RefreshCw className='size-4' />重新加载</Button></CardContent></Card>
  const run = query.data
  const done = run.completed_count + run.failed_count
  const completion = run.planned_count ? Math.round(done / run.planned_count * 100) : 0
  const currentStatus = run.linked_status ?? run.status
  const resolvedCount = run.resolved_count ?? run.completed_count
  const unresolvedCount = run.unresolved_count ?? run.failed_count
  const completeEvidenceCount = run.linked_complete_evidence_count ?? (run.retry_runs?.length ? (run.results ?? []).filter((result) => result.evidence).length : run.complete_evidence_count)

  return <div className='flex h-full min-h-0 flex-col gap-4'>
    <PageHeader
      title={run.number}
      description={`${runDisplayType(run)} · ${run.planned_date} · ${run.platform_codes.length} 个平台 · ${run.planned_count} 款车型`}
      eyebrow={<Button variant='ghost' size='sm' className='-ml-2 mb-1 h-7 text-xs text-muted-foreground' onClick={() => navigate({ to: '/reputation', search: { tab: 'runs', page: undefined } })}><ArrowLeft className='size-3.5' />返回口碑巡检</Button>}
      actions={<><StatusBadge value={currentStatus} label={statusName(currentStatus)} />{currentStatus !== run.status && <Badge variant='outline' title='原批次终态保持不可变'>原批次：{statusName(run.status)}</Badge>}{run.source_type === 'scheduled' && <Badge variant='outline' className='border-cyan-500/25 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300'>正式调度</Badge>}{run.source_type === 'retry' && <Badge variant='outline'>失败项补跑</Badge>}{run.delayed && <Badge variant='outline' title='服务在计划时间之后恢复，并于同一自然日自动补触发。' className='border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300'>同日补触发</Badge>}{run.source_type === 'synthetic' && <Badge variant='outline' className='border-violet-500/25 bg-violet-500/10 text-violet-700 dark:text-violet-300'>合成测试</Badge>}{run.source_type === 'real_acceptance' && <Badge variant='outline' className='border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'>真实验收</Badge>}{run.source_type === 'scheduled' && <DropdownMenu><DropdownMenuTrigger asChild><Button variant='ghost' size='icon' className='size-8' aria-label='更多批次操作'><EllipsisVertical className='size-4' /></Button></DropdownMenuTrigger><DropdownMenuContent align='end'>{run.unresolved_count && ['partial_success', 'failed'].includes(run.status) ? <DropdownMenuItem disabled={retry.isPending} onSelect={() => retry.mutate()}><RotateCcw className='size-4' />补跑 {run.unresolved_count} 个失败项</DropdownMenuItem> : null}{run.unresolved_count && ['partial_success', 'failed'].includes(run.status) ? <DropdownMenuSeparator /> : null}<DropdownMenuItem variant='destructive' disabled={remove.isPending || !['success', 'partial_success', 'failed'].includes(run.status)} onSelect={() => { if (window.confirm('将整体删除该正式批次、全部补跑及交付文件，并保留日期墓碑。确认继续？')) remove.mutate() }}><Trash2 className='size-4' />删除关联链</DropdownMenuItem></DropdownMenuContent></DropdownMenu>}</>}
    />
    <div className='grid shrink-0 gap-3 sm:grid-cols-2 xl:grid-cols-4'>
      <Kpi label='处理完成' value={`${done}/${run.planned_count}`} hint={`${completion}% 已结束`} icon={Check} tone='cyan'><Progress value={completion} className='mt-2 h-1.5' /></Kpi>
      <Kpi label='当前完整结果' value={String(resolvedCount)} hint={unresolvedCount ? `${unresolvedCount} 项需关注` : '全部正常'} icon={ShieldCheck} tone='green' />
      <Kpi label='当前页面证据' value={run.required_evidence_count ? `${completeEvidenceCount}/${run.required_evidence_count}` : '历史未要求'} hint={run.required_evidence_count ? (completeEvidenceCount === run.required_evidence_count ? '所需证据完整' : '仍有证据缺口') : '旧批次沿用创建时证据规则'} icon={ImageIcon} tone='violet' />
      <Kpi label='完成时间' value={formatDate(run.finished_at).slice(11)} hint={formatDate(run.finished_at).slice(0, 10)} icon={RefreshCw} tone='amber' />
    </div>
    <div className='flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
      <Tabs value={view} onValueChange={(value) => navigate({ to: '/reputation/runs/$runId', params: { runId }, search: { view: value as NonNullable<SearchState['view']> }, replace: true })}>
        <TabsList><TabsTrigger value='ranking'>排名数据</TabsTrigger><TabsTrigger value='evidence'>页面证据</TabsTrigger><TabsTrigger value='report'>汇报结果</TabsTrigger></TabsList>
      </Tabs>
      <div className='flex flex-wrap gap-2'>
        <DownloadButton href={run.downloads?.txt} icon={FileText}>TXT</DownloadButton>
        <DownloadButton href={run.downloads?.xlsx} icon={FileSpreadsheet}>XLSX</DownloadButton>
        <DownloadButton href={run.downloads?.evidence_zip} icon={FileArchive}>证据 ZIP</DownloadButton>
      </div>
    </div>
    <motion.div key={view} initial={reduceMotion ? false : { opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: 'easeOut' }} className='min-h-0 flex-1 overflow-hidden'>
      {view === 'ranking' ? <RankingPanel results={run.results ?? []} onViewEvidence={setEvidenceViewer} /> : view === 'evidence' ? <EvidencePanel results={run.results ?? []} onViewEvidence={setEvidenceViewer} /> : <ReportPanel run={run} />}
    </motion.div>
    <ReputationEvidenceDialog result={evidenceViewer} onOpenChange={(open) => !open && setEvidenceViewer(undefined)} />
  </div>
}

function Kpi({ label, value, hint, icon: Icon, tone, children }: { label: string; value: string; hint: string; icon: typeof Check; tone: 'cyan' | 'green' | 'violet' | 'amber'; children?: React.ReactNode }) {
  const colors = { cyan: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-300', green: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300', violet: 'bg-violet-500/10 text-violet-600 dark:text-violet-300', amber: 'bg-amber-500/10 text-amber-600 dark:text-amber-300' }
  return <Card className='border-border/70 bg-card/88 py-4 shadow-sm'><CardContent className='px-4'><div className='flex items-start justify-between'><div><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-1 text-xl font-semibold tabular-nums'>{value}</div></div><div className={cn('grid size-8 place-items-center rounded-lg', colors[tone])}><Icon className='size-4' /></div></div><div className='mt-1 text-[11px] text-muted-foreground'>{hint}</div>{children}</CardContent></Card>
}

function RankingPanel({ results, onViewEvidence }: { results: ReputationResult[]; onViewEvidence: (result: ReputationResult) => void }) {
  const platforms = Array.from(new Map(results.map((result) => [result.platform_code, result.platform_name])).entries())
  const vehicles = Array.from(new Map(results.map((result) => [result.vehicle_id, result])).values())
  const byTarget = new Map(results.map((result) => [`${result.vehicle_id}|${result.platform_code}`, result]))
  return <Card className='flex h-full min-h-0 flex-col overflow-hidden border-border/70 bg-card/90 py-0 shadow-sm'><div className='min-h-0 flex-1 overflow-auto'><Table className='min-w-max'><TableHeader className='[&_th]:bg-card'><TableRow className='bg-card hover:bg-card'><TableHead rowSpan={2} className='reputation-sticky-head sticky top-0 left-0 z-40 w-24 bg-card pl-4'>角色</TableHead><TableHead rowSpan={2} className='reputation-sticky-head sticky top-0 left-24 z-40 min-w-40 bg-card'>车型</TableHead>{platforms.map(([code, name]) => <TableHead key={code} colSpan={6} className='sticky top-0 z-30 border-l bg-card text-center font-semibold'>{name}</TableHead>)}</TableRow><TableRow className='bg-card hover:bg-card'>{platforms.flatMap(([code]) => [<TableHead key={`${code}-score`} className='sticky top-10 z-30 border-l bg-card text-right'>口碑分</TableHead>, <TableHead key={`${code}-rank`} className='sticky top-10 z-30 bg-card text-right'>排名</TableHead>, <TableHead key={`${code}-volume`} className='sticky top-10 z-30 bg-card text-right'>口碑量</TableHead>, <TableHead key={`${code}-reviews`} className='sticky top-10 z-30 bg-card text-right'>评价篇数</TableHead>, <TableHead key={`${code}-negative`} className='sticky top-10 z-30 bg-card text-right'>差评率</TableHead>, <TableHead key={`${code}-state`} className='sticky top-10 z-30 min-w-32 bg-card'>状态/证据</TableHead>])}</TableRow></TableHeader><TableBody>{vehicles.map((vehicle) => <TableRow key={vehicle.vehicle_id} className='group'><TableCell className='sticky left-0 z-20 bg-card pl-4 transition-colors group-hover:bg-muted/50'><ReputationRoleLabel role={vehicle.role} position={vehicle.vehicle_position} /></TableCell><TableCell className='sticky left-24 z-20 bg-card transition-colors group-hover:bg-muted/50'><div className='font-medium'>{vehicle.vehicle_name}</div><div className='mt-1 text-xs text-muted-foreground'>{vehicle.series_name}</div></TableCell>{platforms.flatMap(([code]) => {
    const result = byTarget.get(`${vehicle.vehicle_id}|${code}`)
    if (!result) return [<TableCell key={`${code}-missing`} colSpan={6} className='border-l text-center text-xs text-muted-foreground'>未纳入本批次</TableCell>]
    return [<TableCell key={`${code}-score`} className='border-l text-right'><MetricCell metric={result.metrics.score} /></TableCell>, <TableCell key={`${code}-rank`} className='text-right'><MetricCell metric={result.metrics.rank} inverseLabel /></TableCell>, <TableCell key={`${code}-volume`} className='text-right'><MetricCell metric={result.metrics.volume} /></TableCell>, <TableCell key={`${code}-reviews`} className='text-right'><MetricCell metric={result.metrics.review_article_count ?? historicalMetric()} /></TableCell>, <TableCell key={`${code}-negative`} className='text-right'><MetricCell metric={result.metrics.negative_rate ?? historicalMetric()} /></TableCell>, <TableCell key={`${code}-state`}><div className='flex items-center gap-1'>{result.status === 'success' ? <StatusBadge value='success' label='成功' /> : <StatusBadge value='failed' label='异常' />}{result.evidence ? <Button variant='ghost' size='icon' className='size-8' onClick={() => onViewEvidence(result)} aria-label={`查看${result.platform_name}截图`}><ImageIcon className='size-4' /></Button> : <span className='text-xs text-muted-foreground'>缺图</span>}</div>{result.error_message && <div className='mt-1 max-w-40 text-[11px] text-muted-foreground'>{result.error_message}</div>}</TableCell>]
  })}</TableRow>)}</TableBody></Table></div><div className='shrink-0 border-t bg-card/95 px-4 py-3 text-xs text-muted-foreground'>每款车型一行，每个平台固定五指标与状态/证据六列组；口碑分、口碑量和评价篇数升高为绿色，排名数字和差评率下降为绿色。</div></Card>
}

function historicalMetric(): ReputationMetric {
  return { direction: 'none', tone: 'neutral', comparison_status: 'historical_not_collected' }
}

function MetricCell({ metric, inverseLabel = false }: { metric: ReputationMetric; inverseLabel?: boolean }) {
  const Icon = metric.direction === 'up' ? ArrowUp : metric.direction === 'down' ? ArrowDown : Minus
  const tone = metric.tone === 'positive' ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : metric.tone === 'negative' ? 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300' : 'border-border bg-muted/35 text-foreground'
  if (!metric.raw) return <span className='text-sm text-muted-foreground'>—</span>
  const comparable = metric.comparison_status === 'comparable'
  const changeLabel = metric.direction === 'same' ? (inverseLabel ? '名次持平' : '较前日持平') : inverseLabel ? (metric.tone === 'positive' ? '名次上升' : '名次下降') : (metric.direction === 'up' ? '较前日上升' : '较前日下降')
  const delta = metric.delta == null ? '' : String(metric.delta)
  return <div className={cn('inline-flex min-w-24 flex-col rounded-md border px-2 py-1.5', tone)}><span className='font-semibold tabular-nums'>{metric.raw}</span>{comparable ? <span className='mt-0.5 flex items-center gap-1 text-[11px]'><Icon className='size-3' />{changeLabel}{metric.direction !== 'same' && delta ? ` ${delta.replace(/[+-]/, '')}` : ''}</span> : <span className='mt-0.5 text-[11px] opacity-75'>{stateName(metric.comparison_status)}</span>}</div>
}

function EvidencePanel({ results, onViewEvidence }: { results: ReputationResult[]; onViewEvidence: (result: ReputationResult) => void }) {
  const reduceMotion = useReducedMotion()
  const evidence = results.filter((result) => result.evidence)
  return <div className='h-full overflow-auto pr-1'><div className='grid gap-4 md:grid-cols-2 2xl:grid-cols-3'>{evidence.map((result, index) => <motion.article key={result.id} initial={reduceMotion ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, delay: reduceMotion ? 0 : Math.min(index * 0.025, 0.2) }}><Card className='group overflow-hidden border-border/70 py-0 transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md motion-reduce:transform-none'><button type='button' onClick={() => onViewEvidence(result)} className='relative block w-full cursor-zoom-in overflow-hidden border-b bg-muted/35 text-left' aria-label={`查看 ${result.vehicle_name} 指标区域截图`}><img src={result.evidence!.metric_region_url} alt={`${result.vehicle_name} 指标区域截图`} className='aspect-[4.45/1] w-full object-cover transition-transform duration-300 group-hover:scale-[1.015] motion-reduce:transform-none' /><span className='absolute right-2 bottom-2 rounded-md bg-background/90 px-2 py-1 text-[11px] shadow-sm backdrop-blur'>查看大图 <ImageIcon className='ml-1 inline size-3' /></span></button><CardHeader className='pb-2'><div className='flex items-start justify-between gap-2'><div><CardTitle className='text-base'>{result.vehicle_name}</CardTitle><CardDescription>{result.series_name} · {result.platform_name}</CardDescription></div><Badge variant='outline'>{result.role === 'focus' ? '重点车型' : '竞品'}</Badge></div></CardHeader><CardContent className='pb-4'><div className='grid grid-cols-3 gap-2 text-xs'><EvidenceMetric label='口碑分' value={result.metrics.score.raw} /><EvidenceMetric label='排名' value={result.metrics.rank.raw} /><EvidenceMetric label='口碑量' value={result.metrics.volume.raw} /></div><div className='mt-3 truncate font-mono text-[10px] text-muted-foreground' title={result.evidence!.metric_region_sha256}>SHA-256 · {result.evidence!.metric_region_sha256}</div></CardContent></Card></motion.article>)}</div>{!evidence.length && <Card className='grid h-full min-h-64 place-items-center'><CardContent className='text-center'><ImageIcon className='mx-auto mb-2 size-7 text-muted-foreground/50' /><div className='font-medium'>本批次未保存页面证据</div></CardContent></Card>}</div>
}

function ReputationEvidenceDialog({ result, onOpenChange }: { result?: ReputationResult; onOpenChange: (open: boolean) => void }) {
  const evidence = result?.evidence
  const metrics = result ? [
    { label: '口碑分', value: result.metrics.score.raw },
    { label: '同级排名', value: result.metrics.rank.raw },
    { label: '口碑量', value: result.metrics.volume.raw },
  ] : []

  return <Dialog open={Boolean(evidence)} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton={false} className='max-h-[92svh] w-[96vw] max-w-[1500px] gap-0 overflow-hidden border-border bg-background p-0 text-foreground shadow-[0_32px_90px_rgba(15,23,42,0.28)] sm:max-w-[1500px]'>
      <DialogHeader className='relative overflow-hidden border-b border-border bg-card px-6 py-5 pr-20 text-left'>
        <div className='pointer-events-none absolute -top-20 right-24 size-44 rounded-full bg-primary/8 blur-3xl' />
        <div className='relative flex items-start gap-4'>
          <div className='grid size-11 shrink-0 place-items-center rounded-xl border border-primary/20 bg-primary/10 shadow-sm'>
            <ImageIcon className='size-5 text-primary' />
          </div>
          <div className='min-w-0'>
            <div className='mb-1 flex flex-wrap items-center gap-2 text-[11px] font-medium tracking-[0.14em] text-primary uppercase'>
              <span>页面证据</span><span className='size-1 rounded-full bg-border' /><span>{result?.platform_name}</span>
            </div>
            <DialogTitle className='truncate text-xl leading-tight text-foreground sm:text-2xl'>{result?.vehicle_name} 指标区域截图</DialogTitle>
            <DialogDescription className='mt-1.5 text-sm text-muted-foreground'>{result?.series_name} · 巡检时同一页面上下文保存的原始区域 PNG</DialogDescription>
          </div>
        </div>
        <DialogClose className='absolute top-5 right-5 grid size-9 place-items-center rounded-lg border border-border bg-background/80 text-muted-foreground shadow-sm transition-colors hover:border-primary/30 hover:bg-primary/10 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'>
          <X className='size-4' /><span className='sr-only'>关闭</span>
        </DialogClose>
      </DialogHeader>

      <div className='grid min-h-0 overflow-auto lg:grid-cols-[minmax(0,1fr)_250px] lg:overflow-hidden'>
        <div className='relative grid min-h-64 place-items-center overflow-auto bg-muted/55 p-4 sm:p-6'>
          <div className='pointer-events-none absolute inset-0 text-border opacity-35 [background-image:linear-gradient(currentColor_1px,transparent_1px),linear-gradient(90deg,currentColor_1px,transparent_1px)] [background-size:24px_24px]' />
          {evidence && <img src={evidence.metric_region_url} alt={`${result?.vehicle_name} 指标区域截图大图`} className='relative block h-auto max-h-[calc(92svh-9rem)] w-auto max-w-full rounded-xl border border-card bg-card shadow-[0_18px_50px_rgba(15,23,42,0.2)] ring-1 ring-border/80' />}
        </div>

        <aside className='border-t border-border bg-card p-5 lg:overflow-auto lg:border-t-0 lg:border-l'>
          <div className='flex items-center justify-between gap-3'>
            <div className='text-xs font-medium tracking-wide text-muted-foreground'>证据概览</div>
            <Badge className='border-emerald-500/20 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-300'><ShieldCheck className='size-3' />已留存</Badge>
          </div>
          <div className='mt-4 space-y-2'>
            {metrics.map((metric) => <div key={metric.label} className='flex items-center justify-between rounded-lg border border-border bg-muted/45 px-3 py-2.5'>
              <span className='text-xs text-muted-foreground'>{metric.label}</span><span className='font-semibold tabular-nums text-card-foreground'>{metric.value ?? '—'}</span>
            </div>)}
          </div>
          <div className='mt-5 border-t border-border pt-4'>
            <div className='text-xs font-medium tracking-wide text-muted-foreground'>采集信息</div>
            <dl className='mt-3 space-y-3 text-xs'>
              <div className='flex justify-between gap-3'><dt className='text-muted-foreground/75'>角色</dt><dd className='text-right text-card-foreground'>{result?.role === 'focus' ? '重点车型' : '竞品'}</dd></div>
              <div className='flex justify-between gap-3'><dt className='text-muted-foreground/75'>采集时间</dt><dd className='text-right text-card-foreground'>{result ? formatDate(result.collected_at) : '—'}</dd></div>
              <div className='flex justify-between gap-3'><dt className='text-muted-foreground/75'>文件格式</dt><dd className='text-right text-card-foreground'>PNG · 原始区域</dd></div>
            </dl>
          </div>
          <div className='mt-5 border-t border-border pt-4'>
            <div className='text-xs text-muted-foreground/75'>完整性校验</div>
            <div className='mt-2 break-all rounded-lg border border-border bg-muted/45 p-3 font-mono text-[10px] leading-4 text-muted-foreground' title={evidence?.metric_region_sha256}>SHA-256<br />{evidence?.metric_region_sha256}</div>
          </div>
        </aside>
      </div>
    </DialogContent>
  </Dialog>
}

function EvidenceMetric({ label, value }: { label: string; value?: string }) { return <div className='rounded-md bg-muted/45 p-2'><div className='text-muted-foreground'>{label}</div><div className='mt-0.5 font-semibold tabular-nums'>{value ?? '—'}</div></div> }

function ReportPanel({ run }: { run: ReputationRun }) {
  const report = run.report_text ?? ''
  return <div className='grid h-full min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_300px]'><Card className='flex min-h-0 flex-col overflow-hidden py-0'><div className='flex shrink-0 items-center justify-between border-b bg-muted/25 px-4 py-3'><div><div className='font-medium'>巡检汇报正文</div><div className='text-xs text-muted-foreground'>巡检终态后立即生成，不依赖颜色传达变化</div></div><Button variant='outline' size='sm' disabled={!report} onClick={async () => { await navigator.clipboard.writeText(report); toast.success('巡检汇报正文已复制') }}><Clipboard className='size-4' />复制</Button></div>{report ? <pre className='min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-5 font-sans text-sm leading-7'>{report}</pre> : <CardContent className='grid min-h-64 flex-1 place-items-center text-center'><div><Clock3 className='mx-auto mb-2 size-7 text-muted-foreground/55' /><div className='font-medium'>{run.status === 'running' || run.status === 'queued' ? '巡检执行中' : '汇报生成中'}</div><div className='mt-1 text-sm text-muted-foreground'>{run.status === 'running' || run.status === 'queued' ? '汇报只读取终态冻结结果。' : '巡检已结束，系统正在生成汇报文件。'}</div></div></CardContent>}</Card><div className='space-y-4 overflow-auto'><Card><CardHeader><CardTitle className='flex items-center gap-2 text-base'><FileText className='size-4 text-primary' />交付完整性</CardTitle><CardDescription>同一运行生成三类可追溯文件。</CardDescription></CardHeader><CardContent className='space-y-2 text-sm'><DeliveryRow label='汇报 TXT' done={run.report_status === 'success'} /><DeliveryRow label='彩色 XLSX' done={Boolean(run.downloads?.xlsx)} /><DeliveryRow label='页面证据 ZIP' done={run.complete_evidence_count === run.required_evidence_count} /></CardContent></Card><Card><CardHeader><CardTitle className='text-base'>异常口径</CardTitle></CardHeader><CardContent className='text-sm leading-6 text-muted-foreground'>只有访问、身份、解析或证据生成失败才进入异常；平台未提供的指标保持空白。</CardContent></Card></div></div>
}

function DeliveryRow({ label, done }: { label: string; done: boolean }) { return <div className='flex items-center justify-between rounded-md bg-muted/40 px-3 py-2'><span>{label}</span><span className={cn('flex items-center gap-1 text-xs', done ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-600 dark:text-amber-300')}>{done ? <Check className='size-3.5' /> : <CircleAlert className='size-3.5' />}{done ? '已生成' : '待处理'}</span></div> }

function DownloadButton({ href, icon: Icon, children }: { href?: string; icon: typeof Download; children: React.ReactNode }) {
  if (href) return <Button asChild variant='outline' size='sm'><a href={href}><Icon className='size-4' />{children}</a></Button>
  return <Button variant='outline' size='sm' disabled><Icon className='size-4' />{children}</Button>
}
function runTypeName(value: ReputationRun['run_type']) { return ({ baseline_initialization: '基线初始化', daily: '日常巡检', month_end: '月末巡检' })[value] }
function runDisplayType(run: ReputationRun) { return run.source_type === 'scheduled' ? (run.schedule_type === 'month_end' ? '月末巡检' : '日常巡检') : runTypeName(run.run_type) }
function statusName(value: string) { return ({ success: '成功', partial_success: '部分成功', failed: '失败', running: '运行中', queued: '排队中' } as Record<string, string>)[value] ?? value }
function stateName(value: string) { return ({ no_baseline: '暂无基线', comparable: '可比较', not_comparable: '口径变化', not_available: '页面暂无', unknown: '无法确认', auth_required: '需要认证', historical_not_collected: '历史未采集' } as Record<string, string>)[value] ?? value }
