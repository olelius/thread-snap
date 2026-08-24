import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, CircleAlert, Clipboard, Download, FileArchive, FileSpreadsheet, FileText, ImageIcon, Minus, RefreshCw, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { api, errorMessage, formatDate } from '@/lib/api'
import type { ReputationMetric, ReputationResult, ReputationRun } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
  const reduceMotion = useReducedMotion()
  const query = useQuery({
    queryKey: ['reputation-run', runId],
    queryFn: () => api<ReputationRun>(`/reputation/runs/${runId}`),
  })

  if (query.isLoading) return <div className='space-y-4'><Skeleton className='h-20 w-full' /><div className='grid gap-3 md:grid-cols-4'>{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className='h-28 w-full' />)}</div><Skeleton className='h-[420px] w-full' /></div>
  if (query.isError || !query.data) return <Card className='grid h-full place-items-center'><CardContent className='text-center'><CircleAlert className='mx-auto mb-2 size-7 text-destructive' /><div className='font-medium'>巡检详情加载失败</div><div className='mt-1 text-sm text-muted-foreground'>{errorMessage(query.error)}</div><Button className='mt-4' variant='outline' onClick={() => query.refetch()}><RefreshCw className='size-4' />重新加载</Button></CardContent></Card>
  const run = query.data
  const done = run.completed_count + run.failed_count
  const completion = run.planned_count ? Math.round(done / run.planned_count * 100) : 0

  return <div className='flex h-full min-h-0 flex-col gap-4'>
    <PageHeader
      title={run.number}
      description={`${runTypeName(run.run_type)} · ${run.planned_date} · ${run.platform_codes.length} 个平台 · ${run.planned_count} 款车型`}
      eyebrow={<Button variant='ghost' size='sm' className='-ml-2 mb-1 h-7 text-xs text-muted-foreground' onClick={() => navigate({ to: '/reputation', search: { tab: 'runs' } })}><ArrowLeft className='size-3.5' />返回口碑巡检</Button>}
      actions={<><StatusBadge value={run.status} label={statusName(run.status)} />{run.source_type === 'synthetic' && <Badge variant='outline' className='border-violet-500/25 bg-violet-500/10 text-violet-700 dark:text-violet-300'>合成测试</Badge>}{run.source_type === 'real_acceptance' && <Badge variant='outline' className='border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'>真实验收</Badge>}</>}
    />
    <div className='grid shrink-0 gap-3 sm:grid-cols-2 xl:grid-cols-4'>
      <Kpi label='处理完成' value={`${done}/${run.planned_count}`} hint={`${completion}% 已结束`} icon={Check} tone='cyan'><Progress value={completion} className='mt-2 h-1.5' /></Kpi>
      <Kpi label='成功结果' value={String(run.completed_count)} hint={run.failed_count ? `${run.failed_count} 项需关注` : '全部成功'} icon={ShieldCheck} tone='green' />
      <Kpi label='页面证据' value={`${run.complete_evidence_count}/${run.required_evidence_count}`} hint={run.complete_evidence_count === run.required_evidence_count ? '所需证据完整' : '仍有证据缺口'} icon={ImageIcon} tone='violet' />
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
      {view === 'ranking' ? <RankingPanel results={run.results ?? []} /> : view === 'evidence' ? <EvidencePanel results={run.results ?? []} /> : <ReportPanel run={run} />}
    </motion.div>
  </div>
}

function Kpi({ label, value, hint, icon: Icon, tone, children }: { label: string; value: string; hint: string; icon: typeof Check; tone: 'cyan' | 'green' | 'violet' | 'amber'; children?: React.ReactNode }) {
  const colors = { cyan: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-300', green: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300', violet: 'bg-violet-500/10 text-violet-600 dark:text-violet-300', amber: 'bg-amber-500/10 text-amber-600 dark:text-amber-300' }
  return <Card className='border-border/70 bg-card/88 py-4 shadow-sm'><CardContent className='px-4'><div className='flex items-start justify-between'><div><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-1 text-xl font-semibold tabular-nums'>{value}</div></div><div className={cn('grid size-8 place-items-center rounded-lg', colors[tone])}><Icon className='size-4' /></div></div><div className='mt-1 text-[11px] text-muted-foreground'>{hint}</div>{children}</CardContent></Card>
}

function RankingPanel({ results }: { results: ReputationResult[] }) {
  return <Card className='flex h-full min-h-0 flex-col overflow-hidden border-border/70 bg-card/90 py-0 shadow-sm'><div className='min-h-0 flex-1 overflow-auto'><Table className='min-w-[1080px]'><TableHeader><TableRow className='bg-muted/40'><TableHead className='sticky left-0 z-20 w-24 bg-card'>角色</TableHead><TableHead className='sticky left-24 z-20 min-w-40 bg-card'>车型</TableHead><TableHead>平台</TableHead><TableHead>口碑分</TableHead><TableHead>排名</TableHead><TableHead>口碑量</TableHead><TableHead>状态</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>{results.map((result) => <TableRow key={result.id} className='hover:bg-primary/[0.025]'><TableCell className='sticky left-0 z-10 bg-card'><Badge variant={result.role === 'focus' ? 'default' : 'secondary'}>{result.role === 'focus' ? '重点' : '竞品'} {result.vehicle_position}</Badge></TableCell><TableCell className='sticky left-24 z-10 bg-card'><div className='font-medium'>{result.vehicle_name}</div><div className='mt-1 text-xs text-muted-foreground'>{result.series_name}</div></TableCell><TableCell>{result.platform_name}</TableCell><TableCell><MetricCell metric={result.metrics.score} /></TableCell><TableCell><MetricCell metric={result.metrics.rank} inverseLabel /></TableCell><TableCell><MetricCell metric={result.metrics.volume} /></TableCell><TableCell>{result.status === 'success' ? <StatusBadge value='success' label='成功' /> : <div><StatusBadge value='failed' label='异常' /><div className='mt-1 max-w-52 text-[11px] text-muted-foreground'>{result.error_message}</div></div>}</TableCell><TableCell>{result.evidence ? <Button asChild variant='ghost' size='sm'><a href={result.evidence.metric_region_url} target='_blank' rel='noreferrer'><ImageIcon className='size-4' />查看截图</a></Button> : <span className='text-xs text-muted-foreground'>{result.evidence_required ? '缺失' : '无需截图'}</span>}</TableCell></TableRow>)}</TableBody></Table></div><div className='shrink-0 border-t bg-card/95 px-4 py-3 text-xs text-muted-foreground'>颜色表达业务方向：口碑分/口碑量升高为绿色；排名数字变小代表名次上升，同样为绿色。颜色始终配合箭头和文字。</div></Card>
}

function MetricCell({ metric, inverseLabel = false }: { metric: ReputationMetric; inverseLabel?: boolean }) {
  const Icon = metric.direction === 'up' ? ArrowUp : metric.direction === 'down' ? ArrowDown : Minus
  const tone = metric.tone === 'positive' ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : metric.tone === 'negative' ? 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300' : 'border-border bg-muted/35 text-foreground'
  if (!metric.raw) return <div><span className='text-sm text-muted-foreground'>—</span><div className='mt-1 text-[11px] text-muted-foreground'>{stateName(metric.comparison_status)}</div></div>
  return <div className={cn('inline-flex min-w-24 flex-col rounded-md border px-2 py-1.5', tone)}><span className='font-semibold tabular-nums'>{metric.raw}</span>{metric.delta ? <span className='mt-0.5 flex items-center gap-1 text-[11px]'><Icon className='size-3' />{inverseLabel ? (metric.tone === 'positive' ? '名次上升' : '名次下降') : (metric.direction === 'up' ? '较前日上升' : '较前日下降')} {metric.delta.replace(/[+-]/, '')}</span> : <span className='mt-0.5 text-[11px] opacity-75'>{stateName(metric.comparison_status)}</span>}</div>
}

function EvidencePanel({ results }: { results: ReputationResult[] }) {
  const reduceMotion = useReducedMotion()
  const evidence = results.filter((result) => result.evidence)
  return <div className='h-full overflow-auto pr-1'><div className='grid gap-4 md:grid-cols-2 2xl:grid-cols-3'>{evidence.map((result, index) => <motion.article key={result.id} initial={reduceMotion ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, delay: reduceMotion ? 0 : Math.min(index * 0.025, 0.2) }}><Card className='group overflow-hidden border-border/70 py-0 transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md motion-reduce:transform-none'><a href={result.evidence!.metric_region_url} target='_blank' rel='noreferrer' className='relative block overflow-hidden border-b bg-muted/35'><img src={result.evidence!.metric_region_url} alt={`${result.vehicle_name} 指标区域截图`} className='aspect-[4.45/1] w-full object-cover transition-transform duration-300 group-hover:scale-[1.015] motion-reduce:transform-none' /><span className='absolute right-2 bottom-2 rounded-md bg-background/90 px-2 py-1 text-[11px] shadow-sm backdrop-blur'>打开截图 <ArrowRight className='ml-1 inline size-3' /></span></a><CardHeader className='pb-2'><div className='flex items-start justify-between gap-2'><div><CardTitle className='text-base'>{result.vehicle_name}</CardTitle><CardDescription>{result.series_name} · {result.platform_name}</CardDescription></div><Badge variant='outline'>{result.role === 'focus' ? '重点车型' : '竞品'}</Badge></div></CardHeader><CardContent className='pb-4'><div className='grid grid-cols-3 gap-2 text-xs'><EvidenceMetric label='口碑分' value={result.metrics.score.raw} /><EvidenceMetric label='排名' value={result.metrics.rank.raw} /><EvidenceMetric label='口碑量' value={result.metrics.volume.raw} /></div><div className='mt-3 truncate font-mono text-[10px] text-muted-foreground' title={result.evidence!.metric_region_sha256}>SHA-256 · {result.evidence!.metric_region_sha256}</div></CardContent></Card></motion.article>)}</div>{!evidence.length && <Card className='grid h-full min-h-64 place-items-center'><CardContent className='text-center'><ImageIcon className='mx-auto mb-2 size-7 text-muted-foreground/50' /><div className='font-medium'>本批次没有页面证据</div></CardContent></Card>}</div>
}

function EvidenceMetric({ label, value }: { label: string; value?: string }) { return <div className='rounded-md bg-muted/45 p-2'><div className='text-muted-foreground'>{label}</div><div className='mt-0.5 font-semibold tabular-nums'>{value ?? '—'}</div></div> }

function ReportPanel({ run }: { run: ReputationRun }) {
  const report = run.report_text ?? ''
  return <div className='grid h-full min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_300px]'><Card className='flex min-h-0 flex-col overflow-hidden py-0'><div className='flex shrink-0 items-center justify-between border-b bg-muted/25 px-4 py-3'><div><div className='font-medium'>定时汇报正文</div><div className='text-xs text-muted-foreground'>纯文本输出，不依赖颜色传达变化</div></div><Button variant='outline' size='sm' onClick={async () => { await navigator.clipboard.writeText(report); toast.success('汇报正文已复制') }}><Clipboard className='size-4' />复制</Button></div><pre className='min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-5 font-sans text-sm leading-7'>{report}</pre></Card><div className='space-y-4 overflow-auto'><Card><CardHeader><CardTitle className='flex items-center gap-2 text-base'><FileText className='size-4 text-primary' />交付完整性</CardTitle><CardDescription>同一运行生成三类可追溯文件。</CardDescription></CardHeader><CardContent className='space-y-2 text-sm'><DeliveryRow label='汇报 TXT' done={run.report_status === 'success'} /><DeliveryRow label='彩色 XLSX' done={Boolean(run.downloads?.xlsx)} /><DeliveryRow label='页面证据 ZIP' done={run.complete_evidence_count === run.required_evidence_count} /></CardContent></Card><Card><CardHeader><CardTitle className='text-base'>异常口径</CardTitle></CardHeader><CardContent className='text-sm leading-6 text-muted-foreground'>页面缺失、需认证和无法可靠解析会进入“异常与缺失”，不会用空值伪装成无变化。</CardContent></Card></div></div>
}

function DeliveryRow({ label, done }: { label: string; done: boolean }) { return <div className='flex items-center justify-between rounded-md bg-muted/40 px-3 py-2'><span>{label}</span><span className={cn('flex items-center gap-1 text-xs', done ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-600 dark:text-amber-300')}>{done ? <Check className='size-3.5' /> : <CircleAlert className='size-3.5' />}{done ? '已生成' : '待处理'}</span></div> }

function DownloadButton({ href, icon: Icon, children }: { href?: string; icon: typeof Download; children: React.ReactNode }) { return <Button asChild={Boolean(href)} variant='outline' size='sm' disabled={!href}>{href ? <a href={href}><Icon className='size-4' />{children}</a> : <span><Icon className='size-4' />{children}</span>}</Button> }
function runTypeName(value: ReputationRun['run_type']) { return ({ baseline_initialization: '基线初始化', daily: '日常巡检', month_end: '月末巡检' })[value] }
function statusName(value: string) { return ({ success: '成功', partial_success: '部分成功', failed: '失败', running: '运行中', queued: '排队中' } as Record<string, string>)[value] ?? value }
function stateName(value: string) { return ({ no_baseline: '暂无基线', comparable: '可比较', not_available: '页面暂无', unknown: '无法确认', auth_required: '需要认证' } as Record<string, string>)[value] ?? value }
