import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { Activity, Beaker, CalendarClock, ChartNoAxesCombined, CircleAlert, ExternalLink, FileCheck2, Gauge, Images, Loader2, Play, RefreshCw, Rocket, ScanSearch, Settings2, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { api, errorMessage, formatDate, platformName } from '@/lib/api'
import type { PageResult, ReputationCapabilities, ReputationMappingValidation, ReputationRun, ReputationSchedule, ReputationScope } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

type SearchState = { tab?: 'runs' | 'scope' }

export function ReputationPage() {
  const search = useSearch({ strict: false }) as SearchState
  const tab = search.tab ?? 'runs'
  const navigate = useNavigate({ from: '/reputation' })
  const queryClient = useQueryClient()
  const reduceMotion = useReducedMotion()
  const [testOpen, setTestOpen] = useState(false)
  const [scenario, setScenario] = useState('daily_mixed_changes')
  const capabilities = useQuery({
    queryKey: ['reputation-capabilities'],
    queryFn: () => api<ReputationCapabilities>('/reputation/capabilities'),
  })
  const runs = useQuery({
    queryKey: ['reputation-runs'],
    queryFn: () => api<PageResult<ReputationRun>>('/reputation/runs?limit=100'),
    refetchInterval: (query) => query.state.data?.items.some((run) => ['queued', 'running'].includes(run.status) || run.report_status === 'waiting') ? 3_000 : false,
  })
  const schedule = useQuery({
    queryKey: ['reputation-schedule'],
    queryFn: () => api<ReputationSchedule>('/reputation/schedule'),
  })
  const scope = useQuery({
    queryKey: ['reputation-scope'],
    queryFn: () => api<ReputationScope>('/reputation/scope'),
  })
  const createTest = useMutation({
    mutationFn: () => api<ReputationRun>('/reputation/test-runs', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenario }),
    }, 30_000),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['reputation-runs'] })
      setTestOpen(false)
      toast.success('合成巡检已完成', { description: `${run.number} · ${run.planned_count} 项` })
      navigate({ to: '/reputation/runs/$runId', params: { runId: run.id }, search: { view: 'ranking' } })
    },
    onError: (error) => toast.error('测试运行失败', { description: errorMessage(error) }),
  })

  return (
    <div className='flex h-full min-h-0 flex-col gap-4'>
      <PageHeader
        title='口碑巡检'
        description='独立管理垂媒车型口碑分、排名、页面证据与定时汇报，不与帖子提取批次混合。'
        eyebrow={<div className='mb-1 flex items-center gap-2 text-xs font-semibold tracking-[0.18em] text-primary uppercase'><ChartNoAxesCombined className='size-3.5' /> Reputation intelligence</div>}
        actions={<>
          <Button variant='outline' size='sm' onClick={() => { runs.refetch(); scope.refetch(); capabilities.refetch(); schedule.refetch() }}><RefreshCw className={`size-4 ${runs.isFetching ? 'animate-spin' : ''}`} />刷新</Button>
          {capabilities.data?.reputation_synthetic_runs && <Button size='sm' onClick={() => setTestOpen(true)}><Beaker className='size-4' />手动跑测试</Button>}
        </>}
      />

      <div className='flex shrink-0 items-center justify-between gap-3'>
        <Tabs value={tab} onValueChange={(value) => navigate({ to: '/reputation', search: { tab: value as 'runs' | 'scope' }, replace: true })}>
          <TabsList>
            <TabsTrigger value='runs'><Activity />巡检批次</TabsTrigger>
            <TabsTrigger value='scope'><Settings2 />车型与映射</TabsTrigger>
          </TabsList>
        </Tabs>
        <Badge variant='outline' className='hidden gap-1.5 font-normal sm:flex'><Gauge className='size-3.5 text-cyan-500' />当前阶段 · 单平台</Badge>
      </div>

      <motion.div
        key={tab}
        initial={reduceMotion ? false : { opacity: 0, y: 5 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className='min-h-0 flex-1 overflow-hidden'
      >
        {tab === 'runs'
          ? <RunsPanel query={runs} schedule={schedule.data} onOpen={(id) => navigate({ to: '/reputation/runs/$runId', params: { runId: id }, search: { view: 'ranking' } })} />
          : <ScopePanel query={scope} adapterMessage={capabilities.data?.real_adapter_message} />}
      </motion.div>

      <Dialog open={testOpen} onOpenChange={setTestOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className='flex items-center gap-2'><Beaker className='size-5 text-primary' />运行隔离合成测试</DialogTitle>
            <DialogDescription>使用固定版本的虚拟数据生成真实列表、颜色、报告、XLSX 和页面证据；不会访问平台，也不会写入正式提取批次。</DialogDescription>
          </DialogHeader>
          <RadioGroup value={scenario} onValueChange={setScenario} className='gap-2'>
            {capabilities.data?.scenarios.map((item) => (
              <label key={item.id} className='flex cursor-pointer gap-3 rounded-lg border p-3 transition-[border-color,background-color,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/35 hover:bg-primary/[0.025] motion-reduce:transform-none'>
                <RadioGroupItem value={item.id} className='mt-0.5' />
                <span><span className='block text-sm font-medium'>{item.name}</span><span className='mt-0.5 block text-xs leading-5 text-muted-foreground'>{item.description}</span></span>
              </label>
            ))}
          </RadioGroup>
          <DialogFooter>
            <Button variant='outline' onClick={() => setTestOpen(false)}>取消</Button>
            <Button onClick={() => createTest.mutate()} disabled={createTest.isPending}><Play className='size-4' />{createTest.isPending ? '正在生成…' : '运行并查看结果'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function RunsPanel({ query, schedule, onOpen }: { query: ReturnType<typeof useQuery<PageResult<ReputationRun>>>; schedule?: ReputationSchedule; onOpen: (id: string) => void }) {
  if (query.isLoading) return <Card className='h-full py-0'><CardContent className='space-y-3 p-5'>{Array.from({ length: 7 }).map((_, index) => <Skeleton key={index} className='h-12 w-full' />)}</CardContent></Card>
  if (query.isError) return <Failure title='巡检批次加载失败' detail={errorMessage(query.error)} retry={() => query.refetch()} />
  const items = query.data?.items ?? []
  return (
    <Card className='flex h-full min-h-0 flex-col overflow-hidden border-border/70 bg-card/90 py-0 shadow-sm backdrop-blur'>
      <div className='flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-muted/20 px-4 py-3'>
        <div className='flex items-center gap-2 text-sm'><span className='grid size-8 place-items-center rounded-lg bg-primary/10 text-primary'><CalendarClock className='size-4' /></span><span><span className='block font-medium'>每日 {schedule?.inspection_time?.slice(0, 5) ?? '12:00'} 正式巡检</span><span className='block text-xs text-muted-foreground'>{schedule?.timezone ?? 'Asia/Shanghai'} · 巡检完成后立即生成汇报</span></span></div>
        <div className='max-w-xl text-right text-xs text-muted-foreground'>{schedule?.last_event ? `${schedule.last_event.planned_date} · ${schedule.last_event.message}` : '等待首个正式计划事件'}</div>
      </div>
      <div className='min-h-0 flex-1 overflow-auto'>
        <Table className='min-w-[980px]'>
          <TableHeader><TableRow className='bg-muted/35'><TableHead>巡检编号</TableHead><TableHead>类型</TableHead><TableHead>平台与范围</TableHead><TableHead>状态</TableHead><TableHead>处理进度</TableHead><TableHead>证据完整度</TableHead><TableHead>完成时间</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {items.length ? items.map((run) => {
              const done = run.completed_count + run.failed_count
              const percent = run.planned_count ? Math.round(done / run.planned_count * 100) : 0
              return <TableRow key={run.id} className='cursor-pointer transition-colors hover:bg-primary/[0.035]' onClick={() => onOpen(run.id)}>
                <TableCell><div className='font-medium'>{run.number}</div><div className='mt-1 text-xs text-muted-foreground'>{run.planned_date}</div></TableCell>
                <TableCell><Badge variant='secondary'>{runDisplayType(run)}</Badge>{run.run_type === 'baseline_initialization' && run.source_type === 'scheduled' && <div className='mt-1 text-[11px] text-muted-foreground'>基线初始化</div>}{run.source_type === 'scheduled' && <div className='mt-1 text-[11px] text-cyan-700 dark:text-cyan-300'>正式调度{run.delayed ? ' · 同日补触发' : ''}</div>}{run.source_type === 'synthetic' && <div className='mt-1 text-[11px] text-violet-600 dark:text-violet-300'>合成测试</div>}{run.source_type === 'real_acceptance' && <div className='mt-1 text-[11px] text-emerald-600 dark:text-emerald-300'>真实验收</div>}</TableCell>
                <TableCell><div className='text-sm'>{run.platform_codes.map(platformName).join('、')}</div><div className='mt-1 text-xs text-muted-foreground'>{run.planned_count} 款车型</div></TableCell>
                <TableCell><StatusBadge value={run.status} label={statusName(run.status)} />{run.retry_runs?.length ? <div className='mt-1 text-[11px] text-muted-foreground'>关联补跑 {run.retry_runs.length} 次 · {run.resolved_count}/{run.planned_count} 已完整</div> : null}</TableCell>
                <TableCell><div className='w-36 space-y-1.5'><div className='flex justify-between text-xs'><span>{done}/{run.planned_count}</span><span className='text-muted-foreground'>{percent}%</span></div><Progress value={percent} className='h-1.5' />{run.failed_count > 0 && <div className='text-[11px] text-red-600 dark:text-red-300'>{run.failed_count} 项异常</div>}</div></TableCell>
                <TableCell><div className='flex items-center gap-1.5 text-sm'><FileCheck2 className={`size-4 ${run.complete_evidence_count === run.required_evidence_count ? 'text-emerald-500' : 'text-amber-500'}`} />{run.required_evidence_count ? `${run.complete_evidence_count}/${run.required_evidence_count}` : '无需截图'}</div></TableCell>
                <TableCell className='whitespace-nowrap text-sm'>{formatDate(run.finished_at)}</TableCell>
                <TableCell><Button variant='ghost' size='sm' onClick={(event) => { event.stopPropagation(); onOpen(run.id) }}>查看</Button></TableCell>
              </TableRow>
            }) : <TableRow><TableCell colSpan={8} className='h-64 text-center'><ChartNoAxesCombined className='mx-auto mb-3 size-8 text-muted-foreground/45' /><div className='font-medium'>还没有巡检批次</div><div className='mt-1 text-sm text-muted-foreground'>正式运行由定时计划创建；测试环境可用右上角按钮验证完整交付链。</div></TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>
      <div className='shrink-0 border-t bg-card/95 px-4 py-3 text-sm text-muted-foreground'>共 {query.data?.total ?? 0} 个独立巡检批次</div>
    </Card>
  )
}

function ScopePanel({ query, adapterMessage }: { query: ReturnType<typeof useQuery<ReputationScope>>; adapterMessage?: string }) {
  const queryClient = useQueryClient()
  const [mappingOpen, setMappingOpen] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [mappingText, setMappingText] = useState('')
  const [preview, setPreview] = useState<{ valid: boolean; changed_count: number; unchanged_count: number; errors: Array<{ row: string; reason: string }> }>()
  const parseRows = () => mappingText.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    const [vehicle_id, platform_vehicle_id, platform_url, ...display] = line.split('\t')
    return { vehicle_id: vehicle_id?.trim(), platform_vehicle_id: platform_vehicle_id?.trim(), platform_url: platform_url?.trim(), platform_display_name: display.join('\t').trim() }
  })
  const previewMutation = useMutation({
    mutationFn: () => api<typeof preview>('/reputation/scope/mappings/preview', { method: 'POST', body: JSON.stringify({ revision: query.data?.revision, platform_code: 'dongchedi', rows: parseRows() }) }),
    onSuccess: (value) => setPreview(value),
    onError: (error) => toast.error('映射预览失败', { description: errorMessage(error) }),
  })
  const saveMutation = useMutation({
    mutationFn: () => api<ReputationScope>('/reputation/scope/mappings', { method: 'PUT', body: JSON.stringify({ revision: query.data?.revision, platform_code: 'dongchedi', rows: parseRows() }) }),
    onSuccess: (value) => { queryClient.setQueryData(['reputation-scope'], value); setMappingOpen(false); setMappingText(''); setPreview(undefined); toast.success('映射草稿已原子保存', { description: '变化项已恢复为待真实页面验证状态。' }) },
    onError: (error) => toast.error('映射保存失败', { description: errorMessage(error) }),
  })
  const validateMutation = useMutation({
    mutationFn: () => api<ReputationMappingValidation>('/reputation/scope/mapping-validations', {
      method: 'POST',
      body: JSON.stringify({ revision: query.data?.revision }),
    }, 180_000),
    onSuccess: (value) => {
      queryClient.setQueryData(['reputation-scope'], value.scope)
      toast.success('真实页面验证完成', {
        description: `${value.succeeded_count}/${value.requested_count} 项通过，使用并发 ${value.concurrency}`,
      })
    },
    onError: (error) => toast.error('真实页面验证失败', { description: errorMessage(error) }),
  })
  const publishMutation = useMutation({
    mutationFn: () => api<ReputationScope>('/reputation/scope/publish', {
      method: 'POST',
      body: JSON.stringify({ revision: query.data?.revision, initial_review_acknowledged: true }),
    }),
    onSuccess: (value) => {
      queryClient.setQueryData(['reputation-scope'], value)
      setPublishOpen(false)
      toast.success('口碑巡检范围已发布', { description: `当前版本 V${value.published_version?.version}` })
    },
    onError: (error) => toast.error('范围发布失败', { description: errorMessage(error) }),
  })
  if (query.isLoading) return <Card className='h-full py-0'><CardContent className='space-y-3 p-5'><Skeleton className='h-24 w-full' /><Skeleton className='h-72 w-full' /></CardContent></Card>
  if (query.isError) return <Failure title='车型范围加载失败' detail={errorMessage(query.error)} retry={() => query.refetch()} />
  const scope = query.data!
  const verified = scope.vehicles.filter((item) => item.mappings.dongchedi?.validation_status === 'verified').length
  return <div className='h-full space-y-4 overflow-auto pr-1'>
    <div className='grid gap-3 md:grid-cols-3'>
      <SummaryCard icon={ShieldCheck} label='已发布版本' value={scope.published_version ? `V${scope.published_version.version}` : '尚未发布'} hint='发布版本不可变，批次保存触发时快照' />
      <SummaryCard icon={ChartNoAxesCombined} label='车型范围' value={`${scope.vehicles.length}/27`} hint='14 款重点车型 + 13 款竞品' />
      <SummaryCard icon={FileCheck2} label='映射验证' value={`${verified}/${scope.vehicles.length || 27}`} hint='真实页面逐项验证后才开放发布' />
    </div>
    {adapterMessage && <Alert><ShieldCheck /><AlertTitle>真实采集器已接入</AlertTitle><AlertDescription>{adapterMessage}</AlertDescription></Alert>}
    {!scope.initialized ? <Card><CardHeader><CardTitle className='text-base'>车型范围尚未初始化</CardTitle><CardDescription>{scope.message} 初始化属于一次性运维动作，避免浏览器上传真实业务清单。</CardDescription></CardHeader><CardContent className='rounded-lg bg-muted/45 p-4 font-mono text-xs'>threadsnap reputation-init --file &lt;UTF-8-CSV&gt;</CardContent></Card> : <Card className='overflow-hidden py-0'><div className='flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3'><div><div className='text-sm font-medium'>当前范围草稿 · revision {scope.revision}</div><div className='text-xs text-muted-foreground'>验证读取实时页面并只保留口碑指标区域截图；不会创建正式巡检批次。</div></div><div className='flex items-center gap-2'><Button variant='outline' size='sm' onClick={() => setMappingOpen(true)}>批量粘贴映射</Button>{verified === scope.vehicles.length && <Button variant='outline' size='sm' onClick={() => setPublishOpen(true)}><Rocket className='size-4' />{scope.published_version ? '发布新版本' : '发布首个范围'}</Button>}<Button size='sm' disabled={validateMutation.isPending || !scope.vehicles.length} onClick={() => validateMutation.mutate()}>{validateMutation.isPending ? <Loader2 className='size-4 animate-spin' /> : <ScanSearch className='size-4' />}{validateMutation.isPending ? '正在并发验证…' : verified === scope.vehicles.length ? '重新验证全部' : '验证全部真实页面'}</Button></div></div><div className='overflow-auto'><Table className='min-w-[1120px]'><TableHeader><TableRow className='bg-muted/35'><TableHead>角色顺序</TableHead><TableHead>内部车型 ID</TableHead><TableHead>车系</TableHead><TableHead>车型</TableHead><TableHead>平台展示名</TableHead><TableHead className='text-center'>口碑分</TableHead><TableHead className='text-center'>同级排名</TableHead><TableHead className='text-center'>口碑量</TableHead><TableHead>映射状态</TableHead><TableHead>证据</TableHead><TableHead>页面</TableHead></TableRow></TableHeader><TableBody>{scope.vehicles.map((vehicle) => { const mapping = vehicle.mappings.dongchedi; const metrics = mapping?.latest_metrics; return <TableRow key={vehicle.id}><TableCell><Badge variant={vehicle.role === 'focus' ? 'default' : 'secondary'}>{vehicle.role === 'focus' ? '重点' : '竞品'} {vehicle.role_order}</Badge></TableCell><TableCell className='font-mono text-xs text-muted-foreground'>{vehicle.id}</TableCell><TableCell>{vehicle.series_name}</TableCell><TableCell className='font-medium'>{vehicle.vehicle_name}</TableCell><TableCell>{mapping?.actual_name || mapping?.platform_display_name || '—'}</TableCell><TableCell className='text-center font-medium tabular-nums'>{metrics?.score ?? '暂无'}</TableCell><TableCell className='text-center font-medium tabular-nums'>{metrics?.rank ?? '暂无'}</TableCell><TableCell className='text-center font-medium tabular-nums'>{metrics?.volume ?? '暂无'}</TableCell><TableCell><StatusBadge value={mapping?.validation_status ?? 'unknown'} label={mappingStatusName(mapping?.validation_status)} />{mapping?.validation_error && <div className='mt-1 max-w-44 text-[11px] text-destructive'>{mapping.validation_error}</div>}</TableCell><TableCell>{mapping?.validation_attempt_id ? <Button asChild variant='ghost' size='icon'><a href={`/api/v1/reputation/mapping-validations/attempts/${mapping.validation_attempt_id}/metric`} target='_blank' rel='noreferrer' aria-label='查看指标区域截图'><Images className='size-4' /></a></Button> : '—'}</TableCell><TableCell>{mapping?.platform_url ? <Button asChild variant='ghost' size='icon'><a href={mapping.platform_url} target='_blank' rel='noreferrer' aria-label='打开平台页面'><ExternalLink className='size-4' /></a></Button> : '—'}</TableCell></TableRow> })}</TableBody></Table></div></Card>}
    <Dialog open={mappingOpen} onOpenChange={(open) => { setMappingOpen(open); if (!open) setPreview(undefined) }}><DialogContent className='sm:max-w-2xl'><DialogHeader><DialogTitle>批量粘贴懂车帝映射</DialogTitle><DialogDescription>每行四列，以 Tab 分隔：内部车型 ID、平台车型 ID、页面 URL、平台展示名。只提交实际变化项，保存操作全有或全无。</DialogDescription></DialogHeader><Textarea value={mappingText} onChange={(event) => { setMappingText(event.target.value); setPreview(undefined) }} className='min-h-56 font-mono text-xs' placeholder={'dcd-24729\t24729\thttps://www.dongchedi.com/auto/series/score/24729-x-x-x-x-x\t风云A9'} />{preview && <Alert className={preview.valid ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-red-500/25 bg-red-500/5'}><AlertTitle>{preview.valid ? `预览通过：将更新 ${preview.changed_count} 项` : `发现 ${preview.errors.length} 个错误`}</AlertTitle><AlertDescription>{preview.valid ? `${preview.unchanged_count} 项保持不变；保存后变化项进入待验证状态。` : preview.errors.map((item) => `第 ${item.row} 行：${item.reason}`).join('；')}</AlertDescription></Alert>}<DialogFooter><Button variant='outline' onClick={() => setMappingOpen(false)}>取消</Button><Button variant='secondary' disabled={!mappingText.trim() || previewMutation.isPending} onClick={() => previewMutation.mutate()}>预览影响</Button><Button disabled={!preview?.valid || saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? '保存中…' : '确认保存草稿'}</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={publishOpen} onOpenChange={setPublishOpen}><DialogContent className='sm:max-w-xl'><DialogHeader><DialogTitle className='flex items-center gap-2'><Rocket className='size-5 text-primary' />确认发布口碑巡检范围</DialogTitle><DialogDescription>本次发布包含 {scope.vehicles.length} 款车型、{verified} 项已验证懂车帝映射。发布后形成不可变版本，供后续 12:00 正式巡检按计划时点冻结使用。</DialogDescription></DialogHeader><div className='max-h-64 overflow-auto rounded-lg border p-3'><div className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm'>{scope.vehicles.map((vehicle) => <div key={vehicle.id} className='flex items-center justify-between gap-2'><span className='truncate'>{vehicle.vehicle_name}</span><Badge variant={vehicle.role === 'focus' ? 'default' : 'secondary'}>{vehicle.role === 'focus' ? '重点' : '竞品'}</Badge></div>)}</div></div><DialogFooter><Button variant='outline' onClick={() => setPublishOpen(false)}>返回核对</Button><Button disabled={publishMutation.isPending} onClick={() => publishMutation.mutate()}>{publishMutation.isPending ? <Loader2 className='size-4 animate-spin' /> : <Rocket className='size-4' />}确认发布</Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function SummaryCard({ icon: Icon, label, value, hint }: { icon: typeof ShieldCheck; label: string; value: string; hint: string }) {
  return <Card className='border-border/70 bg-card/88 py-4 shadow-sm'><CardContent className='flex items-start gap-3 px-4'><div className='grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary'><Icon className='size-4.5' /></div><div><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-0.5 text-xl font-semibold tabular-nums'>{value}</div><div className='mt-1 text-[11px] text-muted-foreground'>{hint}</div></div></CardContent></Card>
}

function Failure({ title, detail, retry }: { title: string; detail: string; retry: () => void }) {
  return <Card className='grid h-full place-items-center'><CardContent className='text-center'><CircleAlert className='mx-auto mb-2 size-6 text-destructive' /><div className='font-medium'>{title}</div><div className='mt-1 text-sm text-muted-foreground'>{detail}</div><Button className='mt-4' variant='outline' onClick={retry}><RefreshCw className='size-4' />重新加载</Button></CardContent></Card>
}

function runTypeName(value: ReputationRun['run_type']) { return ({ baseline_initialization: '基线初始化', daily: '日常巡检', month_end: '月末巡检' })[value] }
function runDisplayType(run: ReputationRun) { return run.source_type === 'scheduled' ? (run.schedule_type === 'month_end' ? '月末巡检' : '日常巡检') : runTypeName(run.run_type) }
function statusName(value: string) { return ({ success: '成功', partial_success: '部分成功', failed: '失败', running: '运行中', queued: '排队中' } as Record<string, string>)[value] ?? value }
function mappingStatusName(value?: string) { return ({ verified: '已验证', unverified: '待验证', failed: '验证失败' } as Record<string, string>)[value ?? ''] ?? '未知' }
