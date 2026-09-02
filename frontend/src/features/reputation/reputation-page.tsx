import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { Activity, Beaker, CalendarClock, CarFront, ChartNoAxesCombined, ChevronLeft, ChevronRight, CircleAlert, ExternalLink, FileCheck2, Gauge, Images, Loader2, Pencil, Play, Plus, RefreshCw, Rocket, RotateCcw, ScanSearch, Settings2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { ReputationRoleLabel } from '@/features/reputation/reputation-role-label'
import { api, errorMessage, formatDate, platformName } from '@/lib/api'
import type { PageResult, ReputationCapabilities, ReputationMappingValidation, ReputationRun, ReputationSchedule, ReputationScope, ReputationScopeVehicle } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

type SearchState = { tab?: 'runs' | 'scope'; page?: number }

const REPUTATION_RUNS_PAGE_SIZE = 20

export function ReputationPage() {
  const search = useSearch({ strict: false }) as SearchState
  const tab = search.tab ?? 'runs'
  const runsPage = search.page ?? 1
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
    queryKey: ['reputation-runs', runsPage],
    queryFn: () => api<PageResult<ReputationRun>>(`/reputation/runs?offset=${(runsPage - 1) * REPUTATION_RUNS_PAGE_SIZE}&limit=${REPUTATION_RUNS_PAGE_SIZE}`),
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
  const runsTotalPages = Math.max(1, Math.ceil((runs.data?.total ?? 0) / REPUTATION_RUNS_PAGE_SIZE))
  useEffect(() => {
    if (runs.data && runsPage > runsTotalPages) {
      navigate({ to: '/reputation', search: { tab: 'runs', page: runsTotalPages }, replace: true, resetScroll: false })
    }
  }, [navigate, runs.data, runsPage, runsTotalPages])

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
        <Tabs value={tab} onValueChange={(value) => navigate({ to: '/reputation', search: { tab: value as 'runs' | 'scope', page: undefined }, replace: true })}>
          <TabsList>
            <TabsTrigger value='runs'><Activity />巡检批次</TabsTrigger>
            <TabsTrigger value='scope'><Settings2 />车型与映射</TabsTrigger>
          </TabsList>
        </Tabs>
        <Badge variant='outline' className='hidden gap-1.5 font-normal sm:flex'><Gauge className='size-3.5 text-cyan-500' />三平台统一巡检</Badge>
      </div>

      <motion.div
        key={tab}
        initial={reduceMotion ? false : { opacity: 0, y: 5 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className='min-h-0 flex-1 overflow-hidden'
      >
        {tab === 'runs'
          ? <RunsPanel query={runs} schedule={schedule.data} page={runsPage} totalPages={runsTotalPages} onPageChange={(page) => navigate({ to: '/reputation', search: { tab: 'runs', page }, replace: true, resetScroll: false })} onOpen={(id) => navigate({ to: '/reputation/runs/$runId', params: { runId: id }, search: { view: 'ranking' } })} />
          : <ScopePanel query={scope} platforms={capabilities.data?.reputation_platforms} adapterStatus={capabilities.data?.real_adapter_status} adapterMessage={capabilities.data?.real_adapter_message} />}
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

function RunsPanel({ query, schedule, page, totalPages, onPageChange, onOpen }: { query: ReturnType<typeof useQuery<PageResult<ReputationRun>>>; schedule?: ReputationSchedule; page: number; totalPages: number; onPageChange: (page: number) => void; onOpen: (id: string) => void }) {
  if (query.isLoading) return <Card className='h-full py-0'><CardContent className='space-y-3 p-5'>{Array.from({ length: 7 }).map((_, index) => <Skeleton key={index} className='h-12 w-full' />)}</CardContent></Card>
  if (query.isError) return <Failure title='巡检批次加载失败' detail={errorMessage(query.error)} retry={() => query.refetch()} />
  const items = query.data?.items ?? []
  return (
    <div className='flex h-full min-h-0 flex-col gap-3'>
      <Card className='shrink-0 border-border/70 bg-card/90 py-0 shadow-sm backdrop-blur'>
      <div className='flex flex-wrap items-center justify-between gap-3 px-4 py-3'>
        <div className='flex items-center gap-2 text-sm'><span className='grid size-8 place-items-center rounded-lg bg-primary/10 text-primary'><CalendarClock className='size-4' /></span><span><span className='block font-medium'>每日 {schedule?.inspection_time?.slice(0, 5) ?? '10:00'} 正式巡检</span><span className='block text-xs text-muted-foreground'>{schedule?.timezone ?? 'Asia/Shanghai'} · 巡检完成后立即生成汇报</span></span></div>
        <div className='max-w-xl text-right text-xs text-muted-foreground'>{schedule?.last_event ? `${schedule.last_event.planned_date} · ${schedule.last_event.message}` : '等待首个正式计划事件'}</div>
      </div>
      </Card>
      <Card className='flex min-h-0 flex-1 flex-col overflow-hidden border-border/70 bg-card/90 py-0 shadow-sm backdrop-blur'>
      <div className='min-h-0 flex-1 overflow-auto'>
        <Table className='min-w-[980px]'>
          <TableHeader><TableRow className='bg-muted/35'><TableHead className='pl-4'>巡检编号</TableHead><TableHead>类型</TableHead><TableHead>平台与范围</TableHead><TableHead>状态</TableHead><TableHead>处理进度</TableHead><TableHead>证据完整度</TableHead><TableHead>完成时间</TableHead><TableHead className='pr-4 text-right'>操作</TableHead></TableRow></TableHeader>
          <TableBody>
            {items.length ? items.map((run) => {
              const done = run.completed_count + run.failed_count
              const percent = run.planned_count ? Math.round(done / run.planned_count * 100) : 0
              const currentStatus = run.linked_status ?? run.status
              const completeEvidenceCount = run.linked_complete_evidence_count ?? run.complete_evidence_count
              const currentUnresolvedCount = run.unresolved_count ?? run.failed_count
              return <TableRow key={run.id} tabIndex={0} className='cursor-pointer transition-colors hover:bg-primary/[0.035] focus-visible:bg-primary/[0.06] focus-visible:outline-none' onClick={() => onOpen(run.id)} onKeyDown={(event) => { if (event.key === 'Enter') onOpen(run.id) }}>
                <TableCell className='pl-4'><div className='font-medium'>{run.number}</div><div className='mt-1 text-xs text-muted-foreground'>{run.planned_date}</div></TableCell>
                <TableCell><Badge variant='secondary'>{runDisplayType(run)}</Badge>{run.run_type === 'baseline_initialization' && run.source_type === 'scheduled' && <div className='mt-1 text-[11px] text-muted-foreground'>基线初始化</div>}{run.source_type === 'scheduled' && <div className='mt-1 text-[11px] text-cyan-700 dark:text-cyan-300'>正式调度{run.delayed ? ' · 同日补触发' : ''}</div>}{run.source_type === 'synthetic' && <div className='mt-1 text-[11px] text-violet-600 dark:text-violet-300'>合成测试</div>}{run.source_type === 'real_acceptance' && <div className='mt-1 text-[11px] text-emerald-600 dark:text-emerald-300'>真实验收</div>}</TableCell>
                <TableCell><div className='text-sm'>{run.platform_codes.map(platformName).join('、')}</div><div className='mt-1 text-xs text-muted-foreground'>{run.planned_count} 款车型</div></TableCell>
                <TableCell><StatusBadge value={currentStatus} label={statusName(currentStatus)} />{currentStatus !== run.status && <div className='mt-1 text-[11px] text-muted-foreground'>原批次{statusName(run.status)}</div>}{run.retry_runs?.length ? <div className='mt-1 text-[11px] text-muted-foreground'>关联补跑 {run.retry_runs.length} 次 · {run.resolved_count}/{run.planned_count} 已完整</div> : null}</TableCell>
                <TableCell><div className='w-36 space-y-1.5'><div className='flex justify-between text-xs'><span>{done}/{run.planned_count}</span><span className='text-muted-foreground'>{percent}%</span></div><Progress value={percent} className='h-1.5' />{currentUnresolvedCount > 0 && <div className='text-[11px] text-red-600 dark:text-red-300'>{currentUnresolvedCount} 项异常</div>}</div></TableCell>
                <TableCell><div className='flex items-center gap-1.5 text-sm'><FileCheck2 className={`size-4 ${completeEvidenceCount === run.required_evidence_count ? 'text-emerald-500' : 'text-amber-500'}`} />{run.required_evidence_count ? `${completeEvidenceCount}/${run.required_evidence_count}` : '历史未要求'}</div></TableCell>
                <TableCell className='whitespace-nowrap text-sm'>{formatDate(run.finished_at)}</TableCell>
                <TableCell className='pr-4 text-right'><Button variant='ghost' size='sm' onClick={(event) => { event.stopPropagation(); onOpen(run.id) }}>查看</Button></TableCell>
              </TableRow>
            }) : <TableRow><TableCell colSpan={8} className='h-64 text-center'><ChartNoAxesCombined className='mx-auto mb-3 size-8 text-muted-foreground/45' /><div className='font-medium'>还没有巡检批次</div><div className='mt-1 text-sm text-muted-foreground'>正式运行由定时计划创建；测试环境可用右上角按钮验证完整交付链。</div></TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>
      {totalPages > 1 && <div className='flex shrink-0 items-center justify-end gap-2 border-t bg-card/95 px-4 py-3'><span className='mr-1 text-sm text-muted-foreground'>第 {page} / {totalPages} 页</span><Button variant='outline' size='icon' disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label='上一页'><ChevronLeft className='size-4' /></Button><Button variant='outline' size='icon' disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label='下一页'><ChevronRight className='size-4' /></Button></div>}
      </Card>
    </div>
  )
}

type VehicleForm = {
  series_name: string
  vehicle_name: string
  project_group: string
  role: 'focus' | 'competitor'
  platform_vehicle_id: string
  platform_url: string
  platform_display_name: string
}

const emptyVehicleForm: VehicleForm = {
  series_name: '',
  vehicle_name: '',
  project_group: '',
  role: 'focus',
  platform_vehicle_id: '',
  platform_url: '',
  platform_display_name: '',
}

function vehicleFormFrom(vehicle: ReputationScopeVehicle, platformCode: string): VehicleForm {
  const mapping = vehicle.mappings[platformCode]
  return {
    series_name: vehicle.series_name,
    vehicle_name: vehicle.vehicle_name,
    project_group: vehicle.project_group,
    role: vehicle.role,
    platform_vehicle_id: mapping?.platform_vehicle_id ?? '',
    platform_url: mapping?.platform_url ?? '',
    platform_display_name: mapping?.platform_display_name ?? '',
  }
}

type PublishPreview = {
  can_publish: boolean
  has_changes: boolean
  verified_mapping_count: number
  expected_mapping_count: number
  added_count: number
  disabled_count: number
  role_changed_count: number
  mapping_changed_count: number
  identity_changed_count: number
  warning?: string
}

function ScopePanel({ query, platforms, adapterStatus, adapterMessage }: { query: ReturnType<typeof useQuery<ReputationScope>>; platforms?: ReputationCapabilities['reputation_platforms']; adapterStatus?: ReputationCapabilities['real_adapter_status']; adapterMessage?: string }) {
  const queryClient = useQueryClient()
  const [mappingOpen, setMappingOpen] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [vehicleDialogOpen, setVehicleDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ReputationScopeVehicle>()
  const [removeTarget, setRemoveTarget] = useState<ReputationScopeVehicle>()
  const [vehicleForm, setVehicleForm] = useState<VehicleForm>(emptyVehicleForm)
  const [mappingText, setMappingText] = useState('')
  const [platformCode, setPlatformCode] = useState('dongchedi')
  const platformOptions = platforms?.length ? platforms : [{ code: 'dongchedi', display_name: '懂车帝', adapter_version: '', validation_contract_version: '' }]
  const selectedPlatformName = platformOptions.find((item) => item.code === platformCode)?.display_name ?? platformName(platformCode)
  const [preview, setPreview] = useState<{ valid: boolean; changed_count: number; unchanged_count: number; errors: Array<{ row: string; reason: string }> }>()
  const publishPreviewQuery = useQuery({
    queryKey: ['reputation-scope-publish-preview', query.data?.revision],
    queryFn: () => api<PublishPreview>('/reputation/scope/publish-preview'),
    enabled: Boolean(query.data?.initialized),
  })
  const refreshScopeState = (value: ReputationScope) => {
    queryClient.setQueryData(['reputation-scope'], value)
    queryClient.invalidateQueries({ queryKey: ['reputation-scope-publish-preview'] })
  }
  const parseRows = () => mappingText.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    const [vehicle_id, platform_vehicle_id, platform_url, ...display] = line.split('\t')
    return { vehicle_id: vehicle_id?.trim(), platform_vehicle_id: platform_vehicle_id?.trim(), platform_url: platform_url?.trim(), platform_display_name: display.join('\t').trim() }
  })
  const previewMutation = useMutation({
    mutationFn: () => api<typeof preview>('/reputation/scope/mappings/preview', { method: 'POST', body: JSON.stringify({ revision: query.data?.revision, platform_code: platformCode, rows: parseRows() }) }),
    onSuccess: (value) => setPreview(value),
    onError: (error) => toast.error('映射预览失败', { description: errorMessage(error) }),
  })
  const saveMutation = useMutation({
    mutationFn: () => api<ReputationScope>('/reputation/scope/mappings', { method: 'PUT', body: JSON.stringify({ revision: query.data?.revision, platform_code: platformCode, rows: parseRows() }) }),
    onSuccess: (value) => { refreshScopeState(value); setMappingOpen(false); setMappingText(''); setPreview(undefined); toast.success('映射草稿已原子保存', { description: '变化项已恢复为待真实页面验证状态。' }) },
    onError: (error) => toast.error('映射保存失败', { description: errorMessage(error) }),
  })
  const saveVehicleMutation = useMutation({
    mutationFn: () => api<ReputationScope>(editTarget ? `/reputation/scope/vehicles/${encodeURIComponent(editTarget.id)}` : '/reputation/scope/vehicles', {
      method: editTarget ? 'PATCH' : 'POST',
      body: JSON.stringify({ revision: query.data?.revision, platform_code: platformCode, ...vehicleForm }),
    }),
    onSuccess: (value) => {
      const editing = Boolean(editTarget)
      refreshScopeState(value)
      setVehicleDialogOpen(false)
      setEditTarget(undefined)
      setVehicleForm(emptyVehicleForm)
      toast.success(editing ? '车型信息已保存' : '车型已加入当前范围草稿', {
        description: editing
          ? value.last_vehicle_mapping_changed ? '平台映射已变化，该车型需要重新验证后再发布。' : '修改已进入范围草稿，发布后影响后续巡检。'
          : '新映射需通过真实页面验证后才能发布。',
      })
    },
    onError: (error) => toast.error(editTarget ? '修改车型失败' : '新增车型失败', { description: errorMessage(error) }),
  })
  const removeMutation = useMutation({
    mutationFn: (vehicle: ReputationScopeVehicle) => api<ReputationScope>(`/reputation/scope/vehicles/${encodeURIComponent(vehicle.id)}?revision=${query.data?.revision}`, { method: 'DELETE' }),
    onSuccess: (value) => {
      refreshScopeState(value)
      setRemoveTarget(undefined)
      toast.success(value.last_vehicle_action === 'disabled' ? '车型已停用' : '车型已删除', {
        description: value.last_vehicle_action === 'disabled' ? '历史版本与既有批次保持不变，后续范围不再包含该车型。' : '该车型尚未进入版本或批次，草稿身份已永久删除。',
      })
    },
    onError: (error) => toast.error('车型移除失败', { description: errorMessage(error) }),
  })
  const restoreMutation = useMutation({
    mutationFn: (vehicle: ReputationScopeVehicle) => api<ReputationScope>(`/reputation/scope/vehicles/${encodeURIComponent(vehicle.id)}/restore`, { method: 'POST', body: JSON.stringify({ revision: query.data?.revision }) }),
    onSuccess: (value) => { refreshScopeState(value); toast.success('车型已恢复', { description: '已重新加入后续发布范围。' }) },
    onError: (error) => toast.error('恢复车型失败', { description: errorMessage(error) }),
  })
  const validateMutation = useMutation({
    mutationFn: () => api<ReputationMappingValidation>('/reputation/scope/mapping-validations', {
      method: 'POST',
      body: JSON.stringify({ revision: query.data?.revision, platform_code: platformCode }),
    }, 180_000),
    onSuccess: (value) => {
      refreshScopeState(value.scope)
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
      refreshScopeState(value)
      setPublishOpen(false)
      toast.success('口碑巡检范围已发布', { description: '后续计划触发将使用本次冻结范围。' })
    },
    onError: (error) => toast.error('范围发布失败', { description: errorMessage(error) }),
  })
  const openVehicleDialog = (vehicle?: ReputationScopeVehicle) => {
    setEditTarget(vehicle)
    setVehicleForm(vehicle ? vehicleFormFrom(vehicle, platformCode) : emptyVehicleForm)
    setVehicleDialogOpen(true)
  }
  if (query.isLoading) return <Card className='h-full py-0'><CardContent className='space-y-3 p-5'><Skeleton className='h-16 w-full' /><Skeleton className='h-72 w-full' /></CardContent></Card>
  if (query.isError) return <Failure title='车型范围加载失败' detail={errorMessage(query.error)} retry={() => query.refetch()} />
  const scope = query.data!
  const activeVehicles = scope.vehicles.filter((item) => item.enabled)
  const displayVehicles = [...scope.vehicles].sort((left, right) => Number(right.enabled) - Number(left.enabled))
  const verified = activeVehicles.filter((item) => item.mappings[platformCode]?.validation_status === 'verified').length
  const pendingValidation = activeVehicles.length - verified
  const canCreate = Object.entries(vehicleForm).every(([key, value]) => key === 'role' || value.trim())
  const vehicleFormChanged = !editTarget || JSON.stringify(vehicleForm) !== JSON.stringify(vehicleFormFrom(editTarget, platformCode))
  const canSaveVehicle = canCreate && vehicleFormChanged
  const publishPreview = publishPreviewQuery.data
  const publishDisabled = !publishPreview?.can_publish

  return <div className='flex h-full min-h-0 flex-col gap-3'>
    {adapterStatus === 'not_configured' && adapterMessage && <Alert variant='destructive' className='shrink-0'><CircleAlert /><AlertTitle>真实采集器尚未就绪</AlertTitle><AlertDescription>{adapterMessage}</AlertDescription></Alert>}
    {!scope.initialized ? <Card><CardHeader><CardTitle className='text-base'>车型范围尚未初始化</CardTitle><CardDescription>{scope.message} 初始化属于一次性运维动作，避免浏览器上传真实业务清单。</CardDescription></CardHeader><CardContent className='rounded-lg bg-muted/45 p-4 font-mono text-xs'>threadsnap reputation-init --file &lt;UTF-8-CSV&gt;</CardContent></Card> : <div className='flex min-h-0 flex-1 flex-col gap-3'>
      <Card className='shrink-0 border-border/70 bg-card/90 py-0 shadow-sm'>
      <div className='flex flex-wrap items-center justify-between gap-3 px-4 py-3'>
        <div className='flex min-w-0 items-center gap-3'>
          <span className='grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary'><CarFront className='size-4.5' /></span>
          <div className='min-w-0'>
            <div className='flex flex-wrap items-center gap-2'><span className='font-semibold'>车型与映射</span><Badge variant='secondary'>{activeVehicles.length} 款启用</Badge>{scope.vehicles.length > activeVehicles.length && <Badge variant='outline'>{scope.vehicles.length - activeVehicles.length} 款停用</Badge>}</div>
            <div className='mt-0.5 text-xs text-muted-foreground'>维护后续巡检范围；新增或停用后统一验证并发布，历史批次保持不变。</div>
          </div>
        </div>
        <div className='flex flex-wrap items-center justify-end gap-2'>
          <Select value={platformCode} onValueChange={(value) => { setPlatformCode(value); setPreview(undefined); setMappingText('') }}><SelectTrigger className='w-36'><SelectValue /></SelectTrigger><SelectContent>{platformOptions.map((item) => <SelectItem key={item.code} value={item.code}>{item.display_name}</SelectItem>)}</SelectContent></Select>
          <Button variant='outline' size='sm' disabled={validateMutation.isPending || !activeVehicles.length} onClick={() => validateMutation.mutate()}>{validateMutation.isPending ? <Loader2 className='size-4 animate-spin' /> : <ScanSearch className='size-4' />}{validateMutation.isPending ? '正在验证…' : pendingValidation ? `验证待验证（${pendingValidation}）` : '重新验证全部'}</Button>
          <Button variant='outline' size='sm' onClick={() => openVehicleDialog()}><Plus className='size-4' />新增车型</Button>
          <Button variant='outline' size='sm' onClick={() => setMappingOpen(true)}>批量粘贴映射</Button>
          <Button size='sm' disabled={publishDisabled} title={publishPreview?.warning} onClick={() => setPublishOpen(true)}><Rocket className='size-4' />发布变更</Button>
        </div>
      </div>
      </Card>
      <Card className='flex min-h-0 flex-1 flex-col overflow-hidden border-border/70 bg-card/90 py-0 shadow-sm'>
      <div className='min-h-0 flex-1 overflow-auto'>
        <Table className='min-w-[1520px]'>
          <TableHeader className='sticky top-0 z-10 bg-card shadow-[0_1px_0_hsl(var(--border))]'><TableRow className='bg-muted/35 hover:bg-muted/35'><TableHead className='w-24 pl-4'>角色顺序</TableHead><TableHead>内部车型 ID</TableHead><TableHead>车系</TableHead><TableHead>车型</TableHead><TableHead className='min-w-36'>项目组归属</TableHead><TableHead>{selectedPlatformName}展示名</TableHead><TableHead className='text-right'>口碑分</TableHead><TableHead className='text-right'>同级排名</TableHead><TableHead className='text-right'>口碑量</TableHead><TableHead className='text-right'>评价篇数</TableHead><TableHead className='text-right'>差评率</TableHead><TableHead>状态</TableHead><TableHead className='text-center'>证据</TableHead><TableHead className='text-center'>页面</TableHead><TableHead className='pr-4 text-right'>操作</TableHead></TableRow></TableHeader>
          <TableBody>{displayVehicles.map((vehicle) => {
            const mapping = vehicle.mappings[platformCode]
            const metrics = mapping?.latest_metrics
            return <TableRow key={vehicle.id} className={vehicle.enabled ? undefined : 'bg-muted/20 text-muted-foreground'}><TableCell className='w-24 pl-4'><ReputationRoleLabel role={vehicle.role} position={vehicle.role_order} /></TableCell><TableCell className='font-mono text-xs text-muted-foreground'>{vehicle.id}</TableCell><TableCell>{vehicle.series_name}</TableCell><TableCell className='font-medium'>{vehicle.vehicle_name}</TableCell><TableCell>{vehicle.project_group}</TableCell><TableCell>{mapping?.actual_name || mapping?.platform_display_name || '—'}</TableCell><TableCell className='text-right font-medium tabular-nums'>{metrics?.score ?? '暂无'}</TableCell><TableCell className='text-right font-medium tabular-nums'>{metrics?.rank ?? '暂无'}</TableCell><TableCell className='text-right font-medium tabular-nums'>{metrics?.volume ?? '暂无'}</TableCell><TableCell className='text-right font-medium tabular-nums'>{metrics?.review_article_count ?? '暂无'}</TableCell><TableCell className='text-right font-medium tabular-nums'>{metrics?.negative_rate ?? '暂无'}</TableCell><TableCell>{vehicle.enabled ? <StatusBadge value={mapping?.validation_status ?? 'unknown'} label={mappingStatusName(mapping?.validation_status)} /> : <Badge variant='outline'>已停用</Badge>}{vehicle.enabled && mapping?.validation_error && <div className='mt-1 max-w-44 text-[11px] text-destructive'>{mapping.validation_error}</div>}</TableCell><TableCell className='text-center'>{mapping?.validation_attempt_id ? <Button asChild variant='ghost' size='icon'><a href={`/api/v1/reputation/mapping-validations/attempts/${mapping.validation_attempt_id}/metric`} target='_blank' rel='noreferrer' aria-label='查看指标区域截图'><Images className='size-4' /></a></Button> : '—'}</TableCell><TableCell className='text-center'>{mapping?.platform_url ? <Button asChild variant='ghost' size='icon'><a href={mapping.platform_url} target='_blank' rel='noreferrer' aria-label='打开平台页面'><ExternalLink className='size-4' /></a></Button> : '—'}</TableCell><TableCell className='pr-4 text-right'><ScopeVehicleAction vehicle={vehicle} editPending={saveVehicleMutation.isPending} restorePending={restoreMutation.isPending} onEdit={() => openVehicleDialog(vehicle)} onRemove={() => setRemoveTarget(vehicle)} onRestore={() => restoreMutation.mutate(vehicle)} /></TableCell></TableRow>
          })}</TableBody>
        </Table>
      </div>
      </Card>
    </div>}

    <Dialog open={vehicleDialogOpen} onOpenChange={(open) => { setVehicleDialogOpen(open); if (!open) { setEditTarget(undefined); setVehicleForm(emptyVehicleForm) } }}><DialogContent className='sm:max-w-2xl'><DialogHeader><DialogTitle className='flex items-center gap-2'>{editTarget ? <Pencil className='size-5 text-primary' /> : <Plus className='size-5 text-primary' />}{editTarget ? '修改车型' : '新增车型'}</DialogTitle><DialogDescription>{editTarget ? `修改 ${editTarget.vehicle_name} 的当前范围草稿和${selectedPlatformName}映射；映射字段变化后需要重新验证，发布后影响后续巡检。` : `新增后先进入当前草稿并分配不可复用的内部车型 ID；完成${selectedPlatformName}真实页面验证并发布后，后续巡检才会包含该车型。`}</DialogDescription></DialogHeader><div className='grid gap-4 py-1 sm:grid-cols-2'><div className='space-y-2'><Label htmlFor='series-name'>车系</Label><Input id='series-name' value={vehicleForm.series_name} onChange={(event) => setVehicleForm((value) => ({ ...value, series_name: event.target.value }))} placeholder='例如：风云系' /></div><div className='space-y-2'><Label htmlFor='vehicle-name'>车型</Label><Input id='vehicle-name' value={vehicleForm.vehicle_name} onChange={(event) => setVehicleForm((value) => ({ ...value, vehicle_name: event.target.value }))} placeholder='例如：风云A9' /></div><div className='space-y-2'><Label htmlFor='project-group'>项目组归属</Label><Input id='project-group' maxLength={80} value={vehicleForm.project_group} onChange={(event) => setVehicleForm((value) => ({ ...value, project_group: event.target.value }))} placeholder='例如：奇瑞项目组' /></div><div className='space-y-2'><Label>角色</Label><Select value={vehicleForm.role} onValueChange={(role: 'focus' | 'competitor') => setVehicleForm((value) => ({ ...value, role }))}><SelectTrigger className='w-full'><SelectValue /></SelectTrigger><SelectContent><SelectItem value='focus'>重点车型</SelectItem><SelectItem value='competitor'>竞品车型</SelectItem></SelectContent></Select></div><div className='space-y-2'><Label htmlFor='platform-id'>平台车型 ID</Label><Input id='platform-id' value={vehicleForm.platform_vehicle_id} onChange={(event) => setVehicleForm((value) => ({ ...value, platform_vehicle_id: event.target.value }))} placeholder='平台页面中的车型 ID' /></div><div className='space-y-2'><Label htmlFor='platform-name'>平台展示名</Label><Input id='platform-name' value={vehicleForm.platform_display_name} onChange={(event) => setVehicleForm((value) => ({ ...value, platform_display_name: event.target.value }))} placeholder='页面实际展示的车型名称' /></div><div className='space-y-2 sm:col-span-2'><Label htmlFor='platform-url'>车型口碑页 URL</Label><Input id='platform-url' value={vehicleForm.platform_url} onChange={(event) => setVehicleForm((value) => ({ ...value, platform_url: event.target.value }))} placeholder={`${selectedPlatformName}车型口碑页 URL`} /></div></div><DialogFooter><Button variant='outline' onClick={() => { setVehicleDialogOpen(false); setEditTarget(undefined); setVehicleForm(emptyVehicleForm) }}>取消</Button><Button disabled={!canSaveVehicle || saveVehicleMutation.isPending} onClick={() => saveVehicleMutation.mutate()}>{saveVehicleMutation.isPending ? <Loader2 className='size-4 animate-spin' /> : editTarget ? <Pencil className='size-4' /> : <Plus className='size-4' />}{saveVehicleMutation.isPending ? '正在保存…' : editTarget ? '保存修改' : '确认新增'}</Button></DialogFooter></DialogContent></Dialog>

    <AlertDialog open={Boolean(removeTarget)} onOpenChange={(open) => { if (!open) setRemoveTarget(undefined) }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{removeTarget?.removal_mode === 'disable' ? '停用该车型？' : '永久删除该车型？'}</AlertDialogTitle><AlertDialogDescription>{removeTarget?.removal_mode === 'disable' ? `${removeTarget.vehicle_name} 已被历史版本或批次引用，因此会保留身份和历史数据，只从后续发布范围中停用。` : `${removeTarget?.vehicle_name ?? ''} 尚未进入任何版本或批次，确认后会从当前草稿中永久删除。`}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction className='bg-destructive text-destructive-foreground hover:bg-destructive/90' disabled={removeMutation.isPending} onClick={() => removeTarget && removeMutation.mutate(removeTarget)}>{removeMutation.isPending ? '处理中…' : removeTarget?.removal_mode === 'disable' ? '确认停用' : '确认删除'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>

    <Dialog open={mappingOpen} onOpenChange={(open) => { setMappingOpen(open); if (!open) setPreview(undefined) }}><DialogContent className='sm:max-w-2xl'><DialogHeader><DialogTitle>批量粘贴{selectedPlatformName}映射</DialogTitle><DialogDescription>每行四列，以 Tab 分隔：内部车型 ID、平台车型 ID、页面 URL、平台展示名。只提交实际变化项，保存操作全有或全无。</DialogDescription></DialogHeader><Textarea value={mappingText} onChange={(event) => { setMappingText(event.target.value); setPreview(undefined) }} className='min-h-56 font-mono text-xs' placeholder={'rep-…\t平台车型ID\t车型口碑页URL\t平台展示名'} />{preview && <Alert className={preview.valid ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-red-500/25 bg-red-500/5'}><AlertTitle>{preview.valid ? `预览通过：将更新 ${preview.changed_count} 项` : `发现 ${preview.errors.length} 个错误`}</AlertTitle><AlertDescription>{preview.valid ? `${preview.unchanged_count} 项保持不变；保存后变化项进入待验证状态。` : preview.errors.map((item) => `第 ${item.row} 行：${item.reason}`).join('；')}</AlertDescription></Alert>}<DialogFooter><Button variant='outline' onClick={() => setMappingOpen(false)}>取消</Button><Button variant='secondary' disabled={!mappingText.trim() || previewMutation.isPending} onClick={() => previewMutation.mutate()}>预览影响</Button><Button disabled={!preview?.valid || saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? '保存中…' : '确认保存草稿'}</Button></DialogFooter></DialogContent></Dialog>

    <Dialog open={publishOpen} onOpenChange={setPublishOpen}><DialogContent className='sm:max-w-2xl'><DialogHeader><DialogTitle className='flex items-center gap-2'><Rocket className='size-5 text-primary' />确认发布范围变更</DialogTitle><DialogDescription>本次将冻结 {activeVehicles.length} 款启用车型和 {publishPreview?.verified_mapping_count ?? verified} / {publishPreview?.expected_mapping_count ?? activeVehicles.length} 项已验证映射；后续计划使用新范围，既有批次保持不变。</DialogDescription></DialogHeader><div className='grid grid-cols-2 gap-3 rounded-lg border bg-muted/20 p-3 text-sm sm:grid-cols-4'><div><div className='text-xs text-muted-foreground'>新增</div><div className='mt-1 font-semibold'>{publishPreview?.added_count ?? 0}</div></div><div><div className='text-xs text-muted-foreground'>停用</div><div className='mt-1 font-semibold'>{publishPreview?.disabled_count ?? 0}</div></div><div><div className='text-xs text-muted-foreground'>角色/顺序</div><div className='mt-1 font-semibold'>{publishPreview?.role_changed_count ?? 0}</div></div><div><div className='text-xs text-muted-foreground'>名称/映射</div><div className='mt-1 font-semibold'>{(publishPreview?.mapping_changed_count ?? 0) + (publishPreview?.identity_changed_count ?? 0)}</div></div></div><div className='max-h-56 overflow-auto rounded-lg border p-3'><div className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm'>{activeVehicles.map((vehicle) => <div key={vehicle.id} className='flex items-center justify-between gap-2'><span className='truncate'>{vehicle.vehicle_name}</span><Badge variant='outline' className='max-w-36 truncate font-normal'>{vehicle.project_group}</Badge></div>)}</div></div><DialogFooter><Button variant='outline' onClick={() => setPublishOpen(false)}>返回核对</Button><Button disabled={publishMutation.isPending} onClick={() => publishMutation.mutate()}>{publishMutation.isPending ? <Loader2 className='size-4 animate-spin' /> : <Rocket className='size-4' />}确认发布</Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function ScopeVehicleAction({ vehicle, editPending, restorePending, onEdit, onRemove, onRestore }: { vehicle: ReputationScopeVehicle; editPending: boolean; restorePending: boolean; onEdit: () => void; onRemove: () => void; onRestore: () => void }) {
  const label = vehicle.enabled
    ? vehicle.removal_mode === 'disable' ? '停用并保留历史' : '永久删除未发布车型'
    : '恢复车型'
  return <div className='inline-flex items-center justify-end gap-1'><Button variant='ghost' size='sm' className='h-8 px-2 text-muted-foreground hover:text-foreground' aria-label={`修改车型 ${vehicle.vehicle_name}`} disabled={editPending} onClick={onEdit}><Pencil className='size-3.5' />修改</Button><Tooltip><TooltipTrigger asChild>{vehicle.enabled ? <Button variant='ghost' size='icon' className='size-8 text-muted-foreground hover:text-destructive' aria-label={`${vehicle.removal_mode === 'disable' ? '停用' : '删除'}车型 ${vehicle.vehicle_name}`} onClick={onRemove}><Trash2 className='size-4' /></Button> : <Button variant='ghost' size='icon' className='size-8' aria-label={`恢复车型 ${vehicle.vehicle_name}`} disabled={restorePending} onClick={onRestore}><RotateCcw className='size-4' /></Button>}</TooltipTrigger><TooltipContent side='left'>{label}</TooltipContent></Tooltip></div>
}

function Failure({ title, detail, retry }: { title: string; detail: string; retry: () => void }) {
  return <Card className='grid h-full place-items-center'><CardContent className='text-center'><CircleAlert className='mx-auto mb-2 size-6 text-destructive' /><div className='font-medium'>{title}</div><div className='mt-1 text-sm text-muted-foreground'>{detail}</div><Button className='mt-4' variant='outline' onClick={retry}><RefreshCw className='size-4' />重新加载</Button></CardContent></Card>
}

function runTypeName(value: ReputationRun['run_type']) { return ({ baseline_initialization: '基线初始化', daily: '日常巡检', month_end: '月末巡检' })[value] }
function runDisplayType(run: ReputationRun) { return run.source_type === 'scheduled' ? (run.schedule_type === 'month_end' ? '月末巡检' : '日常巡检') : runTypeName(run.run_type) }
function statusName(value: string) { return ({ success: '成功', partial_success: '部分成功', failed: '失败', running: '运行中', queued: '排队中' } as Record<string, string>)[value] ?? value }
function mappingStatusName(value?: string) { return ({ verified: '已验证', unverified: '待验证', failed: '验证失败' } as Record<string, string>)[value ?? ''] ?? '未知' }
