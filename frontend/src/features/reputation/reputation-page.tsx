import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { Activity, Beaker, ChartNoAxesCombined, CircleAlert, ExternalLink, FileCheck2, Gauge, Play, RefreshCw, Settings2, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { api, errorMessage, formatDate, platformName } from '@/lib/api'
import type { PageResult, ReputationCapabilities, ReputationRun, ReputationScope } from '@/lib/types'
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
          <Button variant='outline' size='sm' onClick={() => { runs.refetch(); scope.refetch(); capabilities.refetch() }}><RefreshCw className={`size-4 ${runs.isFetching ? 'animate-spin' : ''}`} />刷新</Button>
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
          ? <RunsPanel query={runs} onOpen={(id) => navigate({ to: '/reputation/runs/$runId', params: { runId: id }, search: { view: 'ranking' } })} />
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

function RunsPanel({ query, onOpen }: { query: ReturnType<typeof useQuery<PageResult<ReputationRun>>>; onOpen: (id: string) => void }) {
  if (query.isLoading) return <Card className='h-full py-0'><CardContent className='space-y-3 p-5'>{Array.from({ length: 7 }).map((_, index) => <Skeleton key={index} className='h-12 w-full' />)}</CardContent></Card>
  if (query.isError) return <Failure title='巡检批次加载失败' detail={errorMessage(query.error)} retry={() => query.refetch()} />
  const items = query.data?.items ?? []
  return (
    <Card className='flex h-full min-h-0 flex-col overflow-hidden border-border/70 bg-card/90 py-0 shadow-sm backdrop-blur'>
      <div className='min-h-0 flex-1 overflow-auto'>
        <Table className='min-w-[980px]'>
          <TableHeader><TableRow className='bg-muted/35'><TableHead>巡检编号</TableHead><TableHead>类型</TableHead><TableHead>平台与范围</TableHead><TableHead>状态</TableHead><TableHead>处理进度</TableHead><TableHead>证据完整度</TableHead><TableHead>完成时间</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {items.length ? items.map((run) => {
              const done = run.completed_count + run.failed_count
              const percent = run.planned_count ? Math.round(done / run.planned_count * 100) : 0
              return <TableRow key={run.id} className='cursor-pointer transition-colors hover:bg-primary/[0.035]' onClick={() => onOpen(run.id)}>
                <TableCell><div className='font-medium'>{run.number}</div><div className='mt-1 text-xs text-muted-foreground'>{run.planned_date}</div></TableCell>
                <TableCell><Badge variant='secondary'>{runTypeName(run.run_type)}</Badge>{run.source_type === 'synthetic' && <div className='mt-1 text-[11px] text-violet-600 dark:text-violet-300'>合成测试</div>}</TableCell>
                <TableCell><div className='text-sm'>{run.platform_codes.map(platformName).join('、')}</div><div className='mt-1 text-xs text-muted-foreground'>{run.planned_count} 款车型</div></TableCell>
                <TableCell><StatusBadge value={run.status} label={statusName(run.status)} /></TableCell>
                <TableCell><div className='w-36 space-y-1.5'><div className='flex justify-between text-xs'><span>{done}/{run.planned_count}</span><span className='text-muted-foreground'>{percent}%</span></div><Progress value={percent} className='h-1.5' />{run.failed_count > 0 && <div className='text-[11px] text-red-600 dark:text-red-300'>{run.failed_count} 项异常</div>}</div></TableCell>
                <TableCell><div className='flex items-center gap-1.5 text-sm'><FileCheck2 className={`size-4 ${run.complete_evidence_count === run.required_evidence_count ? 'text-emerald-500' : 'text-amber-500'}`} />{run.complete_evidence_count}/{run.required_evidence_count}</div></TableCell>
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
    {adapterMessage && <Alert><CircleAlert /><AlertTitle>真实采集器待页面合同</AlertTitle><AlertDescription>{adapterMessage} 当前先交付可验证的领域、配置和合成测试闭环。</AlertDescription></Alert>}
    {!scope.initialized ? <Card><CardHeader><CardTitle className='text-base'>车型范围尚未初始化</CardTitle><CardDescription>{scope.message} 初始化属于一次性运维动作，避免浏览器上传真实业务清单。</CardDescription></CardHeader><CardContent className='rounded-lg bg-muted/45 p-4 font-mono text-xs'>threadsnap reputation-init --file &lt;UTF-8-CSV&gt;</CardContent></Card> : <Card className='overflow-hidden py-0'><div className='flex items-center justify-between border-b px-4 py-3'><div><div className='text-sm font-medium'>当前范围草稿 · revision {scope.revision}</div><div className='text-xs text-muted-foreground'>保存映射不会自动发布，也不会修改历史巡检。</div></div><Button variant='outline' size='sm' onClick={() => setMappingOpen(true)}>批量粘贴映射</Button></div><div className='overflow-auto'><Table className='min-w-[860px]'><TableHeader><TableRow className='bg-muted/35'><TableHead>角色顺序</TableHead><TableHead>内部车型 ID</TableHead><TableHead>车系</TableHead><TableHead>车型</TableHead><TableHead>平台展示名</TableHead><TableHead>映射状态</TableHead><TableHead>页面</TableHead></TableRow></TableHeader><TableBody>{scope.vehicles.map((vehicle) => { const mapping = vehicle.mappings.dongchedi; return <TableRow key={vehicle.id}><TableCell><Badge variant={vehicle.role === 'focus' ? 'default' : 'secondary'}>{vehicle.role === 'focus' ? '重点' : '竞品'} {vehicle.role_order}</Badge></TableCell><TableCell className='font-mono text-xs text-muted-foreground'>{vehicle.id}</TableCell><TableCell>{vehicle.series_name}</TableCell><TableCell className='font-medium'>{vehicle.vehicle_name}</TableCell><TableCell>{mapping?.platform_display_name || '—'}</TableCell><TableCell><StatusBadge value={mapping?.validation_status ?? 'unknown'} label={mappingStatusName(mapping?.validation_status)} /></TableCell><TableCell>{mapping?.platform_url ? <Button asChild variant='ghost' size='icon'><a href={mapping.platform_url} target='_blank' rel='noreferrer' aria-label='打开平台页面'><ExternalLink className='size-4' /></a></Button> : '—'}</TableCell></TableRow> })}</TableBody></Table></div></Card>}
    <Dialog open={mappingOpen} onOpenChange={(open) => { setMappingOpen(open); if (!open) setPreview(undefined) }}><DialogContent className='sm:max-w-2xl'><DialogHeader><DialogTitle>批量粘贴懂车帝映射</DialogTitle><DialogDescription>每行四列，以 Tab 分隔：内部车型 ID、平台车型 ID、页面 URL、平台展示名。只提交实际变化项，保存操作全有或全无。</DialogDescription></DialogHeader><Textarea value={mappingText} onChange={(event) => { setMappingText(event.target.value); setPreview(undefined) }} className='min-h-56 font-mono text-xs' placeholder={'vehicle-01\tplatform-1001\thttps://example.test/vehicle/1001\t页面车型名'} />{preview && <Alert className={preview.valid ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-red-500/25 bg-red-500/5'}><AlertTitle>{preview.valid ? `预览通过：将更新 ${preview.changed_count} 项` : `发现 ${preview.errors.length} 个错误`}</AlertTitle><AlertDescription>{preview.valid ? `${preview.unchanged_count} 项保持不变；保存后变化项进入待验证状态。` : preview.errors.map((item) => `第 ${item.row} 行：${item.reason}`).join('；')}</AlertDescription></Alert>}<DialogFooter><Button variant='outline' onClick={() => setMappingOpen(false)}>取消</Button><Button variant='secondary' disabled={!mappingText.trim() || previewMutation.isPending} onClick={() => previewMutation.mutate()}>预览影响</Button><Button disabled={!preview?.valid || saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? '保存中…' : '确认保存草稿'}</Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function SummaryCard({ icon: Icon, label, value, hint }: { icon: typeof ShieldCheck; label: string; value: string; hint: string }) {
  return <Card className='border-border/70 bg-card/88 py-4 shadow-sm'><CardContent className='flex items-start gap-3 px-4'><div className='grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary'><Icon className='size-4.5' /></div><div><div className='text-xs text-muted-foreground'>{label}</div><div className='mt-0.5 text-xl font-semibold tabular-nums'>{value}</div><div className='mt-1 text-[11px] text-muted-foreground'>{hint}</div></div></CardContent></Card>
}

function Failure({ title, detail, retry }: { title: string; detail: string; retry: () => void }) {
  return <Card className='grid h-full place-items-center'><CardContent className='text-center'><CircleAlert className='mx-auto mb-2 size-6 text-destructive' /><div className='font-medium'>{title}</div><div className='mt-1 text-sm text-muted-foreground'>{detail}</div><Button className='mt-4' variant='outline' onClick={retry}><RefreshCw className='size-4' />重新加载</Button></CardContent></Card>
}

function runTypeName(value: ReputationRun['run_type']) { return ({ baseline_initialization: '基线初始化', daily: '日常巡检', month_end: '月末巡检' })[value] }
function statusName(value: string) { return ({ success: '成功', partial_success: '部分成功', failed: '失败', running: '运行中', queued: '排队中' } as Record<string, string>)[value] ?? value }
function mappingStatusName(value?: string) { return ({ verified: '已验证', unverified: '待验证', failed: '验证失败' } as Record<string, string>)[value ?? ''] ?? '未知' }
