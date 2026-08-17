import { useEffect, useState, type ReactNode } from 'react'
import { useBlocker, useNavigate, useSearch } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore, CalendarClock, CarFront, Check, ChevronDown, ChevronsUpDown, CirclePlus, Copy, KeyRound, Loader2, Plus, RefreshCw, Save, Settings2, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { AuthDialog } from '@/features/auth/auth-dialog'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { ApiError, api, errorMessage, formatDate, queryString } from '@/lib/api'
import type { Circle, ExtractionPlan, Platform, SessionStatus, Template, Vehicle } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

const tabValues = ['plan', 'platforms', 'circles', 'history', 'templates'] as const
type Tab = typeof tabValues[number]
const weekdays = ['一', '二', '三', '四', '五', '六', '日']

type CircleBatchResult = { items: Circle[]; saved_count: number; deleted_count: number }
type ValidationJob = { id: string; circle_id: string; status: string; error_message?: string }
type ValidationBatchResult = { jobs: ValidationJob[]; queued_count: number; reused_count: number; total_count: number }

const validationSettled = (job: ValidationJob) => ['success', 'failed', 'waiting_for_auth'].includes(job.status)

function ConfigSectionToolbar({ icon, title, summary, description, children }: { icon: ReactNode; title: string; summary: string; description: string; children: ReactNode }) {
  return <div className='sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-card/95 px-4 py-2.5 shadow-sm backdrop-blur-xl'>
    <div className='flex min-w-0 items-center gap-3'>
      <div className='grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/15'>{icon}</div>
      <div className='min-w-0'>
        <div className='flex flex-wrap items-center gap-2'><h2 className='text-base font-semibold'>{title}</h2><Badge variant='secondary' className='font-normal'>{summary}</Badge></div>
        <p className='mt-0.5 text-xs text-muted-foreground'>{description}</p>
      </div>
    </div>
    <div className='flex flex-wrap gap-2'>{children}</div>
  </div>
}

function editablePlanSignature(plan?: ExtractionPlan) {
  if (!plan) return ''
  return JSON.stringify({
    rules: plan.rules.map(({ id, name, platform_quantities, circle_ids }) => ({ id, name, platform_quantities, circle_ids: [...circle_ids].sort() })),
    nodes: plan.nodes.map(({ id, weekdays: days, time, enabled, rule_id }) => ({ id, weekdays: [...days].sort(), time, enabled, rule_id })),
  })
}

function editableRuleSignature(rule?: ExtractionPlan['rules'][number]) {
  if (!rule) return ''
  return JSON.stringify({ name: rule.name, platform_quantities: rule.platform_quantities, circle_ids: [...rule.circle_ids].sort() })
}

function editableNodeSignature(node?: ExtractionPlan['nodes'][number]) {
  if (!node) return ''
  return JSON.stringify({ weekdays: [...node.weekdays].sort(), time: node.time, enabled: node.enabled, rule_id: node.rule_id })
}

function RuleCombobox({ rules, value, disabled, onChange }: { rules: ExtractionPlan['rules']; value: string; disabled?: boolean; onChange: (ruleId: string) => void }) {
  const [open, setOpen] = useState(false)
  const selected = rules.find((rule) => rule.id === value)
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild><Button type='button' variant='outline' role='combobox' aria-expanded={open} disabled={disabled} className='w-full justify-between font-normal'><span className='truncate'>{selected?.name ?? '选择规则'}</span><ChevronsUpDown className='size-4 shrink-0 text-muted-foreground' /></Button></PopoverTrigger>
    <PopoverContent align='start' className='w-[var(--radix-popover-trigger-width)] p-0'>
      <Command><CommandInput placeholder='搜索规则名称或 ID' /><CommandList><CommandEmpty>没有匹配的规则。</CommandEmpty><CommandGroup>{rules.map((rule) => <CommandItem key={rule.id} value={`${rule.name} ${rule.id}`} onSelect={() => { onChange(rule.id); setOpen(false) }}><Check className={cn('size-4', value === rule.id ? 'opacity-100' : 'opacity-0')} /><div className='min-w-0 flex-1'><div className='truncate'>{rule.name}</div><div className='text-xs text-muted-foreground'>版本 {rule.version} · {rule.circle_ids.length} 个圈子</div></div></CommandItem>)}</CommandGroup></CommandList></Command>
    </PopoverContent>
  </Popover>
}

function vehicleRows(vehicles: Vehicle[]) {
  return vehicles.flatMap((vehicle) => vehicle.circles.map((circle) => ({ ...circle, vehicle_id: vehicle.id, vehicle_name: vehicle.name })))
}

function rowsAsVehicles(rows: Circle[]) {
  const vehicles = new Map<string, Vehicle>()
  rows.forEach((circle) => {
    if (!circle.vehicle_id) return
    const vehicle = vehicles.get(circle.vehicle_id) ?? { id: circle.vehicle_id, name: circle.vehicle_name ?? '未分组', circles: [] }
    vehicle.circles.push(circle)
    vehicles.set(circle.vehicle_id, vehicle)
  })
  return [...vehicles.values()]
}

export function ConfigPage() {
  const raw = useSearch({ strict: false }) as { tab?: Tab }
  const navigate = useNavigate({ from: '/config' })
  const [planDirty, setPlanDirty] = useState(false)
  const [platformDirty, setPlatformDirty] = useState(false)
  const [circleDirty, setCircleDirty] = useState(false)
  const dirty = planDirty || platformDirty || circleDirty
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => dirty && current.pathname !== next.pathname,
    enableBeforeUnload: dirty,
    disabled: !dirty,
    withResolver: true,
  })
  const tab = tabValues.includes(raw.tab as Tab) ? raw.tab as Tab : 'plan'
  return (
    <div className='flex h-full min-h-0 flex-col'>
      <div className='shrink-0 space-y-4'>
        <PageHeader title='配置管理' description='每项配置只在唯一归属页面编辑；跨页区域只展示摘要和跳转入口。' />
        {dirty && <Alert className='border-amber-500/30 bg-amber-500/5'><Save className='size-4' /><AlertTitle>存在尚未保存的修改</AlertTitle><AlertDescription>切换标签会保留暂存内容；离开或刷新页面前会提示。保存按钮只提交当前标签。</AlertDescription></Alert>}
      </div>
      <Tabs className='mt-4 flex min-h-0 flex-1 flex-col' value={tab} onValueChange={(value) => navigate({ to: '/config', search: { tab: value as Tab }, replace: true, resetScroll: false })}>
        <div className='shrink-0 overflow-x-auto'><TabsList className='h-10 min-w-max bg-muted/65 p-1'><TabsTrigger value='plan'>提取计划</TabsTrigger><TabsTrigger value='platforms'>平台配置</TabsTrigger><TabsTrigger value='circles'>车型与圈子</TabsTrigger><TabsTrigger value='history'>手动圈子历史</TabsTrigger><TabsTrigger value='templates'>导出模板</TabsTrigger></TabsList></div>
        <TabsContent forceMount value='plan' className='mt-3 min-h-0 flex-1 overflow-y-auto pr-1 data-[state=inactive]:hidden'><PlanPanel onDirtyChange={setPlanDirty} /></TabsContent>
        <TabsContent forceMount value='platforms' className='mt-3 min-h-0 flex-1 overflow-y-auto pr-1 data-[state=inactive]:hidden'><PlatformPanel onDirtyChange={setPlatformDirty} /></TabsContent>
        <TabsContent forceMount value='circles' className='mt-3 min-h-0 flex-1 overflow-y-auto pr-1 data-[state=inactive]:hidden'><CirclePanel onDirtyChange={setCircleDirty} /></TabsContent>
        <TabsContent forceMount value='history' className='mt-3 min-h-0 flex-1 overflow-y-auto pr-1 data-[state=inactive]:hidden'><HistoryPanel /></TabsContent>
        <TabsContent forceMount value='templates' className='mt-3 min-h-0 flex-1 overflow-y-auto pr-1 data-[state=inactive]:hidden'><TemplatePanel /></TabsContent>
      </Tabs>
      <AlertDialog open={blocker.status === 'blocked'}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>放弃尚未保存的修改？</AlertDialogTitle>
            <AlertDialogDescription>离开配置管理后，所有标签中尚未保存的内容都会被放弃。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.status === 'blocked' && blocker.reset()}>留在当前页面</AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.status === 'blocked' && blocker.proceed()}>放弃并离开</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function PlanPanel({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['extraction-plan'], queryFn: () => api<ExtractionPlan>('/extraction-plan') })
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api<Platform[]>('/platforms') })
  const vehicles = useQuery({ queryKey: ['vehicles'], queryFn: () => api<Vehicle[]>('/vehicles') })
  const [draft, setDraft] = useState<ExtractionPlan>()
  const [dirty, setDirty] = useState(false)
  const [selectedRuleId, setSelectedRuleId] = useState<string>()
  const [ruleSearch, setRuleSearch] = useState('')
  const [revisionConflict, setRevisionConflict] = useState(false)

  useEffect(() => { if (query.data && !dirty) setDraft(structuredClone(query.data)) }, [query.data, dirty])
  useEffect(() => {
    if (!draft?.rules.length) { if (selectedRuleId) setSelectedRuleId(undefined); return }
    if (!selectedRuleId || !draft.rules.some((rule) => rule.id === selectedRuleId)) setSelectedRuleId(draft.rules[0].id)
  }, [draft?.rules, selectedRuleId])

  function update(next: ExtractionPlan) {
    const nextDirty = editablePlanSignature(next) !== editablePlanSignature(query.data)
    setDraft(next)
    setDirty(nextDirty)
    onDirtyChange(nextDirty)
  }

  function revealPlanError(error: unknown) {
    if (!(error instanceof ApiError)) return
    if (error.payload.code === 'EXTRACTION_PLAN_REVISION_CONFLICT') setRevisionConflict(true)
    const details = error.payload.details ?? []
    const ruleId = details.find((item) => typeof item.rule_id === 'string')?.rule_id
    const nodeDetail = details.find((item) => typeof item.node_id === 'string' || Array.isArray(item.node_ids))
    const nodeId = typeof nodeDetail?.node_id === 'string' ? nodeDetail.node_id : Array.isArray(nodeDetail?.node_ids) && typeof nodeDetail.node_ids[0] === 'string' ? nodeDetail.node_ids[0] : undefined
    if (typeof ruleId === 'string') setSelectedRuleId(ruleId)
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      const target = typeof ruleId === 'string' ? document.getElementById(`rule-editor-${ruleId}`) : typeof nodeId === 'string' ? document.getElementById(`schedule-node-${nodeId}`) : undefined
      target?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      target?.querySelector<HTMLElement>('input, button')?.focus({ preventScroll: true })
    }))
  }

  const save = useMutation({
    mutationFn: (current: ExtractionPlan) => api<ExtractionPlan>('/extraction-plan', { method: 'PUT', body: JSON.stringify({ revision: current.revision, rules: current.rules.map(({ id, name, platform_quantities, circle_ids }) => ({ id, name, platform_quantities, circle_ids })), nodes: current.nodes.map(({ id, weekdays: days, time, enabled, rule_id }) => ({ id, weekdays: days, time, enabled, rule_id })) }) }),
    onSuccess: (value) => { setDraft(structuredClone(value)); setDirty(false); onDirtyChange(false); client.setQueryData(['extraction-plan'], value); setSelectedRuleId((current) => value.rules.some((rule) => rule.id === current) ? current : value.rules[0]?.id); toast.success('全部提取计划更改已保存') },
    onError: (error) => { revealPlanError(error); toast.error('保存失败', { description: errorMessage(error) }) },
  })

  async function reloadServerPlan() {
    const result = await query.refetch()
    if (!result.data) return
    setDraft(structuredClone(result.data))
    setDirty(false)
    onDirtyChange(false)
    setSelectedRuleId((current) => result.data?.rules.some((rule) => rule.id === current) ? current : result.data?.rules[0]?.id)
    setRevisionConflict(false)
    toast.success('已加载服务器最新提取计划')
  }

  if (!draft) return <Card><CardContent className='p-10 text-center text-sm text-muted-foreground'>正在加载提取计划…</CardContent></Card>
  const allPlatforms = platforms.data ?? []
  const allCircles = vehicleRows(vehicles.data ?? [])
  const enabledCircles = allCircles.filter((circle) => circle.auto_enabled)
  const defaultQuantity = (platform: Platform) => Math.max(platform.quantity_range.min, Math.min(30, platform.quantity_range.max))
  const updateRule = (ruleId: string, transform: (rule: ExtractionPlan['rules'][number]) => ExtractionPlan['rules'][number]) => update({ ...draft, rules: draft.rules.map((item) => item.id === ruleId ? transform(item) : item) })
  const toggleCircle = (ruleId: string, circle: Circle, checked: boolean) => updateRule(ruleId, (rule) => {
    const ids = checked ? [...new Set([...rule.circle_ids, circle.id])] : rule.circle_ids.filter((id) => id !== circle.id)
    const quantities = { ...rule.platform_quantities }
    const platform = allPlatforms.find((item) => item.code === circle.platform_code)
    if (checked && platform && quantities[platform.code] === undefined) quantities[platform.code] = defaultQuantity(platform)
    if (!ids.some((id) => allCircles.find((item) => item.id === id)?.platform_code === circle.platform_code)) delete quantities[circle.platform_code]
    return { ...rule, circle_ids: ids, platform_quantities: quantities }
  })
  const togglePlatform = (ruleId: string, platform: Platform, checked: boolean) => updateRule(ruleId, (rule) => {
    const platformIds = enabledCircles.filter((circle) => circle.platform_code === platform.code).map((circle) => circle.id)
    const ids = checked ? [...new Set([...rule.circle_ids, ...platformIds])] : rule.circle_ids.filter((id) => !platformIds.includes(id))
    const quantities = { ...rule.platform_quantities }
    if (checked && platformIds.length && quantities[platform.code] === undefined) quantities[platform.code] = defaultQuantity(platform)
    if (!ids.some((id) => allCircles.find((circle) => circle.id === id)?.platform_code === platform.code)) delete quantities[platform.code]
    return { ...rule, circle_ids: ids, platform_quantities: quantities }
  })

  const baselineRules = new Map((query.data?.rules ?? []).map((rule) => [rule.id, rule]))
  const baselineNodes = new Map((query.data?.nodes ?? []).map((node) => [node.id, node]))
  const changedRuleIds = new Set(draft.rules.filter((rule) => editableRuleSignature(rule) !== editableRuleSignature(baselineRules.get(rule.id))).map((rule) => rule.id))
  const changedNodeIds = new Set(draft.nodes.filter((node) => editableNodeSignature(node) !== editableNodeSignature(baselineNodes.get(node.id))).map((node) => node.id))
  const removedRules = [...baselineRules.keys()].filter((id) => !draft.rules.some((rule) => rule.id === id)).length
  const removedNodes = [...baselineNodes.keys()].filter((id) => !draft.nodes.some((node) => node.id === id)).length
  const changeCount = changedRuleIds.size + changedNodeIds.size + removedRules + removedNodes
  const selectedRule = draft.rules.find((rule) => rule.id === selectedRuleId)
  const search = ruleSearch.trim().toLocaleLowerCase('zh-CN')
  const filteredRules = draft.rules.filter((rule) => !search || `${rule.name} ${rule.id} ${rule.circle_ids.map((id) => allCircles.find((circle) => circle.id === id)?.name ?? '').join(' ')}`.toLocaleLowerCase('zh-CN').includes(search))

  function createRule() {
    const rule: ExtractionPlan['rules'][number] = { id: crypto.randomUUID(), name: `新规则 ${draft!.rules.length + 1}`, version: 1, platform_quantities: {}, circle_ids: [], archived: false, updated_at: new Date().toISOString() }
    setSelectedRuleId(rule.id)
    setRuleSearch('')
    update({ ...draft!, rules: [...draft!.rules, rule] })
  }

  function removeSelectedRule() {
    if (!selectedRule) return
    const index = draft!.rules.findIndex((rule) => rule.id === selectedRule.id)
    const remaining = draft!.rules.filter((rule) => rule.id !== selectedRule.id)
    setSelectedRuleId(remaining[index]?.id ?? remaining[index - 1]?.id)
    update({ ...draft!, rules: remaining })
  }

  return <div className='space-y-5'>
    <fieldset disabled={save.isPending} className='contents'>
      <ConfigSectionToolbar icon={<CalendarClock className='size-4.5' />} title='自动提取规则' summary={`${draft.rules.length} 条规则${dirty ? ` · ${changeCount} 项未保存` : ''}`} description='左侧定位规则，右侧只编辑当前规则；保存时仍与每周计划节点统一校验并原子提交。'>
        <Button variant='outline' onClick={createRule}><Plus className='size-4' />新建规则</Button>
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate(draft)}>{save.isPending ? <Loader2 className='size-4 animate-spin' /> : <Save className='size-4' />}{save.isPending ? '正在保存' : `保存全部更改${dirty ? ` (${changeCount})` : ''}`}</Button>
      </ConfigSectionToolbar>

      <div className='grid gap-4 xl:h-[min(65svh,620px)] xl:min-h-[500px] xl:grid-cols-[320px_minmax(0,1fr)]'>
        <Card className='flex min-h-[260px] max-h-[360px] flex-col overflow-hidden border-border/70 bg-card/88 py-0 xl:max-h-none'>
          <CardHeader className='shrink-0 border-b p-3'><Label htmlFor='rule-search' className='sr-only'>搜索规则</Label><Input id='rule-search' value={ruleSearch} onChange={(event) => setRuleSearch(event.target.value)} placeholder='搜索规则名称、ID 或圈子' /></CardHeader>
          <CardContent className='min-h-0 flex-1 space-y-1 overflow-y-auto p-2'>
            {filteredRules.length ? filteredRules.map((rule) => {
              const active = rule.id === selectedRuleId
              const referenceCount = draft.nodes.filter((node) => node.rule_id === rule.id).length
              return <Button key={rule.id} type='button' variant='ghost' aria-current={active ? 'true' : undefined} className={cn('h-auto w-full justify-start rounded-lg px-3 py-2.5 text-left', active && 'bg-primary/10 ring-1 ring-primary/20 hover:bg-primary/12')} onClick={() => setSelectedRuleId(rule.id)}>
                <span className='min-w-0 flex-1'><span className='flex items-center gap-2'><span className='truncate font-medium'>{rule.name}</span>{changedRuleIds.has(rule.id) && <span className='size-2 shrink-0 rounded-full bg-amber-500' aria-label='有未保存修改' />}</span><span className='mt-1 block truncate text-xs font-normal text-muted-foreground'>版本 {rule.version} · {rule.circle_ids.length} 个圈子 · {referenceCount} 个计划引用</span></span>
              </Button>
            }) : <div className='p-8 text-center text-sm text-muted-foreground'>{draft.rules.length ? '没有匹配的规则。' : '尚未创建自动提取规则。'}</div>}
          </CardContent>
        </Card>

        <Card className='min-h-[440px] overflow-hidden border-border/70 bg-card/88 py-0'>
          {selectedRule ? <div className='h-full overflow-y-auto' id={`rule-editor-${selectedRule.id}`}>
            <CardHeader className='sticky top-0 z-10 border-b bg-card/95 p-4 backdrop-blur-xl'><div className='flex items-start gap-3'><div className='min-w-0 flex-1'><Label htmlFor={`rule-${selectedRule.id}`}>规则名称</Label><Input id={`rule-${selectedRule.id}`} className='mt-2' value={selectedRule.name} onChange={(event) => updateRule(selectedRule.id, (item) => ({ ...item, name: event.target.value }))} /></div><Button variant='ghost' size='icon' disabled={draft.nodes.some((node) => node.rule_id === selectedRule.id)} onClick={removeSelectedRule} aria-label={draft.nodes.some((node) => node.rule_id === selectedRule.id) ? '规则仍被计划节点引用' : '删除规则'}><Trash2 className='size-4' /></Button></div><CardDescription>ID {selectedRule.id.slice(0, 8)} · 当前版本 {selectedRule.version} · 已选 {selectedRule.circle_ids.length} 个圈子{changedRuleIds.has(selectedRule.id) && ' · 尚未保存'}</CardDescription></CardHeader>
            <CardContent className='space-y-3 p-4'>{allPlatforms.map((platform) => {
              const platformCircles = enabledCircles.filter((circle) => circle.platform_code === platform.code)
              const selectedCount = platformCircles.filter((circle) => selectedRule.circle_ids.includes(circle.id)).length
              const platformChecked = selectedCount === 0 ? false : selectedCount === platformCircles.length ? true : 'indeterminate'
              const integrated = platform.adapter_status === 'available'
              return <Collapsible key={platform.code} defaultOpen={false} className='rounded-xl border bg-background/55'><div className='grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 p-3 sm:grid-cols-[auto_minmax(0,1fr)_10rem]'><Checkbox checked={platformChecked} disabled={!integrated || !platformCircles.length} onCheckedChange={(checked) => togglePlatform(selectedRule.id, platform, checked === true)} aria-label={`选择${platform.display_name}全部圈子`} /><CollapsibleTrigger asChild><Button type='button' variant='ghost' className='group min-w-0 justify-between gap-3 px-0 hover:bg-transparent' aria-label={`展开或收起${platform.display_name}圈子`}><span className='flex min-w-0 items-center gap-2'><span className='truncate text-sm font-medium'>{platform.display_name}</span><Badge variant='outline'>{integrated ? `${selectedCount}/${platformCircles.length} 个圈子` : '暂未接入'}</Badge></span><ChevronDown className='size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180' /></Button></CollapsibleTrigger><div className='col-start-2 w-full sm:col-start-auto'><Label className='sr-only' htmlFor={`quantity-${selectedRule.id}-${platform.code}`}>{platform.display_name}每圈目标数</Label><Input id={`quantity-${selectedRule.id}-${platform.code}`} type='number' disabled={!integrated || selectedCount === 0} min={platform.quantity_range.min} max={platform.quantity_range.max} value={selectedCount ? selectedRule.platform_quantities[platform.code] ?? '' : ''} onChange={(event) => updateRule(selectedRule.id, (item) => ({ ...item, platform_quantities: { ...item.platform_quantities, [platform.code]: Number(event.target.value) } }))} placeholder='每圈目标数' /></div></div><CollapsibleContent><div className='grid gap-2 border-t p-3 sm:grid-cols-2'>{platformCircles.length ? platformCircles.map((circle) => <label key={circle.id} className='flex w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 hover:bg-muted/40'><Checkbox checked={selectedRule.circle_ids.includes(circle.id)} disabled={!integrated} onCheckedChange={(checked) => toggleCircle(selectedRule.id, circle, checked === true)} /><span className='min-w-0 truncate text-sm font-medium'>{circle.name || circle.external_id}</span></label>) : <div className='rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground sm:col-span-2'>该平台暂无全局启用圈子，请前往“车型与圈子”启用。</div>}</div></CollapsibleContent></Collapsible>
            })}</CardContent>
          </div> : <CardContent className='grid h-full min-h-[440px] place-items-center p-10 text-center text-sm text-muted-foreground'>从左侧选择规则，或新建第一条规则。</CardContent>}
        </Card>
      </div>

      <Separator />
      <div className='flex flex-wrap items-center justify-between gap-3'><div><h2 className='text-lg font-semibold'>每周计划节点</h2><p className='text-sm text-muted-foreground'>选择星期与 24 小时制时分秒，每个节点引用一个规则；规则较多时可按名称或 ID 搜索。</p></div><Button variant='outline' disabled={!draft.rules.length} onClick={() => update({ ...draft, nodes: [...draft.nodes, { id: crypto.randomUUID(), weekdays: [0, 1, 2, 3, 4], time: '09:00:00', enabled: false, rule_id: selectedRule?.id ?? draft.rules[0].id, updated_at: new Date().toISOString() }] })}><CirclePlus className='size-4' />新增节点</Button></div>
      <div className='space-y-3'>{draft.nodes.length ? draft.nodes.map((node) => <Card id={`schedule-node-${node.id}`} key={node.id} className={cn('border-border/70', changedNodeIds.has(node.id) && 'ring-1 ring-amber-500/30')}><CardContent className='grid gap-4 p-4 xl:grid-cols-[auto_1fr_170px_260px_auto] xl:items-center'><Switch checked={node.enabled} onCheckedChange={(enabled) => update({ ...draft, nodes: draft.nodes.map((item) => item.id === node.id ? { ...item, enabled } : item) })} aria-label='启用计划节点' /><div className='flex flex-wrap gap-1.5'>{weekdays.map((label, index) => <Button key={label} type='button' variant={node.weekdays.includes(index) ? 'default' : 'outline'} size='icon' className='size-8 rounded-full' onClick={() => update({ ...draft, nodes: draft.nodes.map((item) => item.id === node.id ? { ...item, weekdays: item.weekdays.includes(index) ? item.weekdays.filter((day) => day !== index) : [...item.weekdays, index].sort() } : item) })} aria-label={`星期${label}`}>{label}</Button>)}</div><Input type='time' step={1} value={node.time} onChange={(event) => update({ ...draft, nodes: draft.nodes.map((item) => item.id === node.id ? { ...item, time: event.target.value.length === 5 ? `${event.target.value}:00` : event.target.value } : item) })} /><RuleCombobox rules={draft.rules} value={node.rule_id} disabled={save.isPending} onChange={(rule_id) => update({ ...draft, nodes: draft.nodes.map((item) => item.id === node.id ? { ...item, rule_id } : item) })} /><Button variant='ghost' size='icon' onClick={() => update({ ...draft, nodes: draft.nodes.filter((item) => item.id !== node.id) })} aria-label='删除计划节点'><Trash2 className='size-4' /></Button></CardContent></Card>) : <div className='rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground'><CalendarClock className='mx-auto mb-3 size-8 text-primary/60' />尚未配置每周计划节点。</div>}</div>

      {draft.archived_rules.length > 0 && <Card><CardHeader><CardTitle className='text-base'>已归档规则</CardTitle><CardDescription>历史批次仍保留规则版本快照；存在未保存修改时先保存，再执行恢复。</CardDescription></CardHeader><CardContent className='space-y-2'>{draft.archived_rules.map((rule) => <div key={rule.id} className='flex items-center justify-between rounded-lg border p-3'><div><div className='text-sm font-medium'>{rule.name}</div><div className='text-xs text-muted-foreground'>版本 {rule.version}</div></div><Button variant='outline' size='sm' disabled={dirty || save.isPending} onClick={async () => { try { const value = await api<ExtractionPlan>(`/extraction-rules/${rule.id}/restore`, { method: 'POST' }); setDraft(value); setDirty(false); onDirtyChange(false); client.setQueryData(['extraction-plan'], value); setSelectedRuleId(rule.id); toast.success('规则已恢复') } catch (error) { toast.error('恢复失败', { description: errorMessage(error) }) } }}><ArchiveRestore className='size-4' />{dirty ? '先保存再恢复' : '恢复'}</Button></div>)}</CardContent></Card>}
    </fieldset>

    <AlertDialog open={revisionConflict} onOpenChange={setRevisionConflict}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>服务器提取计划已有更新</AlertDialogTitle><AlertDialogDescription>当前草稿仍保留。可以继续留在页面核对，或放弃本地草稿并加载服务器最新版本。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel onClick={() => setRevisionConflict(false)}>保留当前草稿</AlertDialogCancel><AlertDialogAction onClick={reloadServerPlan}>放弃草稿并重新加载</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </div>
}

function PlatformPanel({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const client = useQueryClient(); const query = useQuery({ queryKey: ['platforms'], queryFn: () => api<Platform[]>('/platforms') }); const [draft, setDraft] = useState<Platform[]>(); const [auth, setAuth] = useState<Platform>(); const [dirty, setDirty] = useState(false)
  useEffect(() => { if (query.data && !dirty) setDraft(structuredClone(query.data)) }, [query.data, dirty])
  const save = useMutation({ mutationFn: async () => Promise.all((draft ?? []).map((item) => api<Platform>(`/platforms/${item.code}`, { method: 'PUT', body: JSON.stringify({ enabled: item.enabled, internal_concurrency: item.internal_concurrency }) }))), onSuccess: (items) => { setDraft(items); setDirty(false); client.setQueryData(['platforms'], items); onDirtyChange(false); toast.success('平台配置已保存') }, onError: (error) => toast.error('保存失败', { description: errorMessage(error) }) })
  if (!draft) return <Card><CardContent className='p-10 text-center text-sm text-muted-foreground'>正在加载平台配置…</CardContent></Card>
  const update = (code: string, values: Partial<Platform>) => { setDraft(draft.map((item) => item.code === code ? { ...item, ...values } : item)); setDirty(true); onDirtyChange(true) }
  const availableCount = draft.filter((platform) => platform.adapter_status === 'available').length
  return <div className='space-y-5'><ConfigSectionToolbar icon={<Settings2 className='size-4.5' />} title='平台采集配置' summary={`已接入 ${availableCount}/${draft.length}`} description='管理平台接入状态、任务启用、内部并发与 Session。'><Button disabled={save.isPending} onClick={() => save.mutate()}><Save className='size-4' />保存当前标签</Button></ConfigSectionToolbar><div className='grid gap-4 xl:grid-cols-3'>{draft.map((platform) => <Card key={platform.code} className='border-border/70 bg-card/88'><CardHeader><div className='flex items-start justify-between'><div><CardTitle>{platform.display_name}</CardTitle><CardDescription className='mt-1'>{platform.adapter_status === 'available' ? `适配器 ${platform.adapter_version ?? '已接入'}` : '后续平台预留'}</CardDescription></div><StatusBadge value={platform.adapter_status === 'available' ? 'success' : 'unknown'} label={platform.adapter_status === 'available' ? '已接入' : '未接入'} /></div></CardHeader><CardContent className='space-y-5'><div className='flex items-center justify-between rounded-lg border p-3'><div><div className='text-sm font-medium'>平台启用</div><div className='text-xs text-muted-foreground'>决定是否允许新任务</div></div><Switch disabled={platform.adapter_status !== 'available'} checked={platform.enabled} onCheckedChange={(enabled) => update(platform.code, { enabled })} /></div><div><Label>平台内部并发</Label><Input className='mt-2' type='number' disabled={platform.adapter_status !== 'available'} min={platform.concurrency_range.min} max={platform.concurrency_range.max} value={platform.internal_concurrency} onChange={(event) => update(platform.code, { internal_concurrency: Number(event.target.value) })} /></div>{platform.adapter_status === 'available' && <SessionCard platform={platform} onAuth={() => setAuth(platform)} />}</CardContent></Card>)}</div><AuthDialog open={Boolean(auth)} onOpenChange={(open) => !open && setAuth(undefined)} platformCode={auth?.code} platformName={auth?.display_name} /></div>
}

function SessionCard({ platform, onAuth }: { platform: Platform; onAuth: () => void }) {
  const client = useQueryClient(); const session = useQuery({ queryKey: ['session', platform.code], queryFn: () => api<SessionStatus>(`/platforms/${platform.code}/session`) })
  const statusLabel = session.data ? ({ missing: '未认证', valid: '有效', invalid: '已失效' }[session.data.status] ?? session.data.status) : '读取中'
  return <div className='rounded-xl border bg-muted/20 p-3'><div className='flex items-start justify-between gap-2'><div><div className='text-sm font-medium'>Session</div><div className='mt-1 text-xs text-muted-foreground'>最近验证：{formatDate(session.data?.last_verified_at)}</div></div><StatusBadge value={session.data?.status === 'valid' ? 'success' : 'unknown'} label={statusLabel} /></div><div className='mt-3 flex gap-2'><Button size='sm' variant='outline' onClick={onAuth}><KeyRound className='size-4' />去认证</Button><Button size='sm' variant='ghost' onClick={async () => { try { await api(`/platforms/${platform.code}/session`, { method: 'DELETE' }); await client.invalidateQueries({ queryKey: ['session', platform.code] }); toast.success('平台会话已清除') } catch (error) { toast.error('清除失败', { description: errorMessage(error) }) } }}>清除</Button></div></div>
}

function CirclePanel({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['vehicles'], queryFn: () => api<Vehicle[]>('/vehicles') })
  const [rows, setRows] = useState<Circle[]>()
  const [deletedIds, setDeletedIds] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [validationJobIds, setValidationJobIds] = useState<string[]>([])
  const validationJobs = useQuery({
    queryKey: ['circle-validation-jobs', validationJobIds],
    queryFn: () => Promise.all(validationJobIds.map((id) => api<ValidationJob>(`/validation-jobs/${id}`))),
    enabled: validationJobIds.length > 0,
    refetchInterval: (result) => result.state.data?.every(validationSettled) ? false : 1000,
  })
  const bulkValidation = useMutation({
    mutationFn: () => api<ValidationBatchResult>('/circles/validate-unverified', { method: 'POST' }),
    onSuccess: (result) => {
      setValidationJobIds(result.jobs.map((job) => job.id))
      if (result.total_count) toast.success('批量验证已进入队列', { description: `共 ${result.total_count} 个圈子，按顺序验证。` })
      else toast.success('没有待验证圈子')
    },
    onError: (error) => toast.error('批量验证提交失败', { description: errorMessage(error) }),
  })
  useEffect(() => { if (query.data && !dirty) { setRows(vehicleRows(query.data)); setDeletedIds([]) } }, [query.data, dirty])
  if (!rows) return <Card><CardContent className='p-10 text-center text-sm text-muted-foreground'>正在加载车型与圈子…</CardContent></Card>
  const markDirty = () => { setDirty(true); onDirtyChange(true) }
  const update = (index: number, values: Partial<Circle>) => { setRows(rows.map((item, rowIndex) => rowIndex === index ? { ...item, ...values } : item)); markDirty() }
  const remove = (index: number) => { const row = rows[index]; setRows(rows.filter((_, rowIndex) => rowIndex !== index)); if (row.id) setDeletedIds((items) => items.includes(row.id) ? items : [...items, row.id]); markDirty() }
  const save = async () => { setSaving(true); try { const result = await api<CircleBatchResult>('/circles/batch', { method: 'PUT', body: JSON.stringify({ rows: rows.map((item) => ({ id: item.id || undefined, platform_code: item.platform_code || 'dongchedi', url: item.url, vehicle_id: item.vehicle_id || undefined, vehicle_name: item.vehicle_name || undefined, auto_enabled: item.auto_enabled, section: item.section || 'dynamic' })), deleted_ids: deletedIds }) }); const vehicles = rowsAsVehicles(result.items); client.setQueryData(['vehicles'], vehicles); setRows(vehicleRows(vehicles)); setDeletedIds([]); setDirty(false); onDirtyChange(false); await client.invalidateQueries({ queryKey: ['vehicles'] }); toast.success('车型与圈子已保存', { description: `保存 ${result.saved_count} 条，删除 ${result.deleted_count} 条` }) } catch (error) { toast.error('保存失败', { description: errorMessage(error) }) } finally { setSaving(false) } }
  const unverifiedCount = rows.filter((row) => row.id && row.validation_status === 'unverified').length
  const jobs = validationJobs.data ?? []
  const completedJobs = jobs.filter(validationSettled).length
  const successfulJobs = jobs.filter((job) => job.status === 'success').length
  const failedJobs = jobs.filter((job) => job.status === 'failed').length
  const authJobs = jobs.filter((job) => job.status === 'waiting_for_auth').length
  const progress = validationJobIds.length ? completedJobs / validationJobIds.length * 100 : 0
  const validate = async (row: Circle) => {
    try {
      const job = await api<ValidationJob>(`/circles/${row.id}/validate`, { method: 'POST' })
      setValidationJobIds([job.id])
      toast.success(row.first_validated_at ? '重新验证已进入队列' : '首次验证已进入队列')
    } catch (error) {
      toast.error('验证提交失败', { description: errorMessage(error) })
    }
  }
  return <div className='space-y-4'>
    <ConfigSectionToolbar icon={<CarFront className='size-4.5' />} title='车型与圈子来源' summary={`${rows.length} 个圈子`} description='首次验证成功自动开启“自动参与”；以后重新验证保持用户当前开关，不会把手动关闭的圈子再次启用。'>
        <Button variant='outline' disabled={dirty || unverifiedCount === 0 || bulkValidation.isPending} onClick={() => bulkValidation.mutate()}>
          {bulkValidation.isPending ? <Loader2 className='size-4 animate-spin' /> : <RefreshCw className='size-4' />}验证全部待验证（{unverifiedCount}）
        </Button>
        <Button variant='outline' onClick={() => { setRows([...rows, { id: '', platform_code: 'dongchedi', external_id: '', url: '', vehicle_name: '未分组', auto_enabled: false, section: 'dynamic', validation_status: 'unverified' }]); markDirty() }}><Plus className='size-4' />新增圈子</Button>
        <Button disabled={saving} onClick={save}>{saving ? <Loader2 className='size-4 animate-spin' /> : <Save className='size-4' />}保存当前标签</Button>
    </ConfigSectionToolbar>
    {validationJobIds.length > 0 && <Alert>
      <RefreshCw className={completedJobs < validationJobIds.length ? 'size-4 animate-spin' : 'size-4'} />
      <AlertTitle>圈子验证进度 {completedJobs}/{validationJobIds.length}</AlertTitle>
      <AlertDescription className='space-y-2'>
        <Progress value={progress} />
        <div>成功 {successfulJobs}，失败 {failedJobs}，等待认证 {authJobs}。首次验证成功会自动参与；重新验证不会改变现有开关。</div>
      </AlertDescription>
    </Alert>}
    {dirty && <Alert><AlertTitle>请先保存当前编辑</AlertTitle><AlertDescription>批量验证只处理数据库中已经保存的圈子。</AlertDescription></Alert>}
    <div className='max-h-[min(65svh,680px)] overflow-auto rounded-xl border bg-card/90' data-list-viewport='circles'>
      <Table className='min-w-[1050px]'>
        <TableHeader><TableRow><TableHead className='w-16 text-center'>序号</TableHead><TableHead>车型</TableHead><TableHead>圈子 URL</TableHead><TableHead>名称</TableHead><TableHead>验证状态</TableHead><TableHead>自动参与</TableHead><TableHead className='text-right'>操作</TableHead></TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => <TableRow key={row.id || `new-${index}`}>
          <TableCell className='w-16 text-center tabular-nums text-muted-foreground'>{index + 1}</TableCell><TableCell><Input value={row.vehicle_name ?? ''} onChange={(event) => update(index, { vehicle_name: event.target.value, vehicle_id: undefined })} placeholder='车型名称' /></TableCell>
          <TableCell><Input value={row.url} onChange={(event) => update(index, { url: event.target.value })} placeholder='圈子 URL' /></TableCell>
          <TableCell>{row.name || (row.id ? '等待验证' : '保存后验证')}</TableCell>
          <TableCell><div className='space-y-1'><StatusBadge value={row.validation_status === 'verified' ? 'success' : row.validation_status === 'failed' ? 'failed' : 'unknown'} label={{ verified: '已验证', failed: '验证失败', unverified: '未验证' }[row.validation_status] ?? row.validation_status} />{row.id && !row.first_validated_at && row.validation_status !== 'verified' && <div className='text-xs text-muted-foreground'>首次通过后自动参与</div>}</div></TableCell>
          <TableCell><Switch checked={row.auto_enabled} disabled={row.validation_status !== 'verified'} onCheckedChange={(auto_enabled) => update(index, { auto_enabled })} /></TableCell>
          <TableCell><div className='flex justify-end gap-1'>{row.id && <Button variant='outline' size='sm' onClick={() => validate(row)}>{row.first_validated_at ? '重新验证' : '验证'}</Button>}<Button variant='ghost' size='icon' onClick={() => remove(index)} aria-label='删除圈子'><Trash2 className='size-4' /></Button></div></TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>
  </div>
}

function HistoryPanel() {
  const client = useQueryClient(); const query = useQuery({ queryKey: ['manual-history'], queryFn: () => api<Circle[]>('/manual-circle-history') })
  async function remove(id?: string) { try { await api(`/manual-circle-history${id ? `/${id}` : ''}`, { method: 'DELETE' }); await client.invalidateQueries({ queryKey: ['manual-history'] }); toast.success(id ? '历史记录已删除' : '手动圈子历史已清空') } catch (error) { toast.error('删除失败', { description: errorMessage(error) }) } }
  return <Card><CardHeader className='flex-row items-center justify-between'><div><CardTitle>手动圈子历史</CardTitle><CardDescription>只保存曾用于手动提取的临时圈子，不影响自动计划。</CardDescription></div><AlertDialog><AlertDialogTrigger asChild><Button variant='outline' disabled={!query.data?.length}>清空历史</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>清空全部手动圈子历史？</AlertDialogTitle><AlertDialogDescription>历史快捷入口将被移除，已经形成的批次快照保持不变。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => remove()}>确认清空</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></CardHeader><CardContent><div className='max-h-[min(58svh,560px)] overflow-auto rounded-xl border' data-list-viewport='circle-history'><Table><TableHeader><TableRow><TableHead className='w-16 text-center'>序号</TableHead><TableHead>圈子</TableHead><TableHead>平台</TableHead><TableHead>最近使用</TableHead><TableHead className='text-right'>操作</TableHead></TableRow></TableHeader><TableBody>{query.data?.length ? query.data.map((circle, index) => <TableRow key={circle.id}><TableCell className='w-16 text-center tabular-nums text-muted-foreground'>{index + 1}</TableCell><TableCell><div className='font-medium'>{circle.name || circle.external_id}</div><div className='max-w-lg truncate text-xs text-muted-foreground'>{circle.url}</div></TableCell><TableCell>{circle.platform_code === 'dongchedi' ? '懂车帝' : circle.platform_code}</TableCell><TableCell>{formatDate((circle as Circle & { last_used_at?: string }).last_used_at)}</TableCell><TableCell className='text-right'><Button variant='ghost' size='icon' onClick={() => remove(circle.id)} aria-label='删除历史记录'><Trash2 className='size-4' /></Button></TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className='h-40 text-center text-muted-foreground'>暂无手动圈子历史。</TableCell></TableRow>}</TableBody></Table></div></CardContent></Card>
}

function TemplatePanel() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates') })
  const vehicles = useQuery({ queryKey: ['vehicles'], queryFn: () => api<Vehicle[]>('/vehicles') })
  const [name, setName] = useState('')
  const [file, setFile] = useState<File>()
  const [circleKey, setCircleKey] = useState('')
  const [manualCopy, setManualCopy] = useState<string>()
  const circles = vehicles.data?.flatMap((vehicle) => vehicle.circles.map((circle) => ({ ...circle, vehicle_name: vehicle.name }))) ?? []
  const selected = circles.find((circle) => `${circle.platform_code}:${circle.external_id}` === circleKey) ?? circles[0]
  const fields = useQuery({ queryKey: ['template-fields', selected?.platform_code, selected?.external_id], queryFn: () => api<TemplateField[]>(`/template-fields${queryString({ platform_code: selected?.platform_code, circle_id: selected?.external_id })}`), enabled: Boolean(selected) })
  const upload = useMutation({ mutationFn: () => { const data = new FormData(); data.set('name', name); data.set('file', file as Blob); return api('/templates', { method: 'POST', body: data }) }, onSuccess: async () => { setName(''); setFile(undefined); await client.invalidateQueries({ queryKey: ['templates'] }); toast.success('导出模板已上传') }, onError: (error) => toast.error('上传失败', { description: errorMessage(error) }) })
  async function copy(text: string) { try { await navigator.clipboard.writeText(text); toast.success('字段标签已复制') } catch { setManualCopy(text) } }
  return <div className='space-y-5'><div className='grid gap-5 xl:grid-cols-[380px_1fr]'><Card><CardHeader><CardTitle>上传 Excel 模板</CardTitle><CardDescription>模板字段标签由后端校验并生成新版本。</CardDescription></CardHeader><CardContent className='space-y-4'><div><Label>模板名称</Label><Input className='mt-2' value={name} onChange={(event) => setName(event.target.value)} placeholder='例如：标准帖子清单' /></div><div><Label>Excel 文件</Label><Input className='mt-2' type='file' accept='.xlsx' onChange={(event) => setFile(event.target.files?.[0])} /></div><Button className='w-full' disabled={!name.trim() || !file || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? <Loader2 className='size-4 animate-spin' /> : <Upload className='size-4' />}上传模板</Button></CardContent></Card><Card><CardHeader><CardTitle>可用模板</CardTitle><CardDescription>删除会隐藏模板，历史版本和既有导出继续保留。</CardDescription></CardHeader><CardContent className='space-y-2'>{query.data?.length ? query.data.map((item) => <div key={item.id} className='flex items-center justify-between rounded-xl border p-4'><div><div className='font-medium'>{item.name}</div><div className='mt-1 text-xs text-muted-foreground'>版本 {item.versions[0]?.version ?? '—'} · {formatDate(item.versions[0]?.created_at)}</div></div><Button variant='ghost' size='icon' onClick={async () => { try { await api(`/templates/${item.id}`, { method: 'DELETE' }); await client.invalidateQueries({ queryKey: ['templates'] }); toast.success('模板已隐藏') } catch (error) { toast.error('操作失败', { description: errorMessage(error) }) } }} aria-label='隐藏模板'><Trash2 className='size-4' /></Button></div>) : <div className='rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground'>暂无导出模板。</div>}</CardContent></Card></div><Card><CardHeader><div className='flex flex-wrap items-start justify-between gap-3'><div><CardTitle>可用字段标签</CardTitle><CardDescription className='mt-1'>选择已保存圈子生成完整标签；标签单元格就是第一条数据位置。</CardDescription></div><Button variant='outline' disabled={!fields.data?.length} onClick={() => copy((fields.data ?? []).map((item) => item.tag).join('\n'))}><Copy className='size-4' />复制全部标签</Button></div></CardHeader><CardContent className='space-y-4'><Select value={selected ? `${selected.platform_code}:${selected.external_id}` : ''} onValueChange={setCircleKey} disabled={!circles.length}><SelectTrigger className='max-w-xl'><SelectValue placeholder='请先保存至少一个圈子' /></SelectTrigger><SelectContent>{circles.map((circle) => <SelectItem key={`${circle.platform_code}:${circle.external_id}`} value={`${circle.platform_code}:${circle.external_id}`}>{circle.vehicle_name} · {circle.name || circle.external_id}</SelectItem>)}</SelectContent></Select><div className='max-h-[min(60svh,620px)] overflow-auto rounded-xl border' data-list-viewport='template-fields'><Table className='min-w-[760px]'><TableHeader><TableRow><TableHead className='w-16 text-center'>序号</TableHead><TableHead>完整标签</TableHead><TableHead>类型</TableHead><TableHead>说明</TableHead><TableHead className='text-right'>操作</TableHead></TableRow></TableHeader><TableBody>{fields.data?.length ? fields.data.map((field, index) => <TableRow key={field.tag}><TableCell className='w-16 text-center tabular-nums text-muted-foreground'>{index + 1}</TableCell><TableCell><code className='text-xs'>{field.tag}</code></TableCell><TableCell>{{ text: '文本', number: '数值', datetime: '日期时间', collection: '集合文本' }[field.type] ?? field.type}</TableCell><TableCell>{field.description}</TableCell><TableCell className='text-right'><Button variant='ghost' size='icon' onClick={() => copy(field.tag)} aria-label='复制字段标签'><Copy className='size-4' /></Button></TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className='h-32 text-center text-muted-foreground'>{circles.length ? '正在加载字段标签…' : '保存圈子后即可生成完整字段标签。'}</TableCell></TableRow>}</TableBody></Table></div></CardContent></Card><Dialog open={manualCopy !== undefined} onOpenChange={(open) => !open && setManualCopy(undefined)}><DialogContent><DialogHeader><DialogTitle>手动复制字段标签</DialogTitle><DialogDescription>当前浏览器上下文未开放剪贴板写入，文本已全选。</DialogDescription></DialogHeader><Textarea readOnly rows={12} value={manualCopy ?? ''} onFocus={(event) => event.currentTarget.select()} autoFocus /></DialogContent></Dialog></div>
}

type TemplateField = { tag: string; field: string; type: string; description: string }
