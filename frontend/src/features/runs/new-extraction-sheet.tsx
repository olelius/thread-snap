import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, CircleDot, FileText, Loader2, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { api, errorMessage } from '@/lib/api'
import type { Circle, Platform, Run, Vehicle } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

type Mode = 'circle_discovery' | 'url_list'

const listOrderGroups: { value: Circle['list_order']; label: string }[] = [
  { value: 'latest_reply', label: '最新回复' },
  { value: 'latest_publish', label: '最新发布' },
]

export function NewExtractionSheet() {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('circle_discovery')
  const [platform, setPlatform] = useState('dongchedi')
  const [quantity, setQuantity] = useState(30)
  const [selectedCircleIds, setSelectedCircleIds] = useState<string[]>([])
  const [circleUrls, setCircleUrls] = useState('')
  const [postUrls, setPostUrls] = useState('')
  const [aiAnalysisEnabled, setAiAnalysisEnabled] = useState(true)
  const [screenshotEnabled, setScreenshotEnabled] = useState(true)
  const vehicles = useQuery({ queryKey: ['vehicles'], queryFn: () => api<Vehicle[]>('/vehicles') })
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api<Platform[]>('/platforms') })
  const availablePlatforms = platforms.data?.filter((item) => item.adapter_status === 'available' && item.enabled) ?? []
  const selectedPlatform = availablePlatforms.find((item) => item.code === platform)
  useEffect(() => {
    if (availablePlatforms.length && !selectedPlatform) {
      setPlatform(availablePlatforms[0].code)
      setSelectedCircleIds([])
    }
  }, [availablePlatforms, selectedPlatform])
  const circles = useMemo(() => vehicles.data?.flatMap((item) => item.circles) ?? [], [vehicles.data])
  const platformCircles = useMemo(() => circles.filter((circle) => circle.platform_code === platform), [circles, platform])

  const submit = useMutation({
    mutationFn: () => {
      const body =
        mode === 'circle_discovery'
          ? {
              platform_code: platform,
              circle_ids: selectedCircleIds,
              circle_urls: lines(circleUrls),
              known_post_urls: [],
              quantity,
              ai_analysis_enabled: aiAnalysisEnabled,
              screenshot_enabled: screenshotEnabled,
              idempotency_key: crypto.randomUUID(),
            }
          : {
              platform_code: platform,
              circle_ids: [],
              circle_urls: [],
              known_post_urls: lines(postUrls),
              quantity,
              ai_analysis_enabled: aiAnalysisEnabled,
              screenshot_enabled: false,
              idempotency_key: crypto.randomUUID(),
            }
      return api<Run>('/runs/manual', { method: 'POST', body: JSON.stringify(body) })
    },
    onSuccess: async (run) => {
      window.dispatchEvent(new CustomEvent('threadsnap:new-run', { detail: run.id }))
      await client.invalidateQueries({ queryKey: ['runs'] })
      toast.success('提取任务已创建', { description: `批次 ${run.number} 已进入队列。` })
      setOpen(false)
      reset()
    },
    onError: (error) => toast.error('提交失败', { description: errorMessage(error) }),
  })

  function reset() {
    setMode('circle_discovery')
    setSelectedCircleIds([])
    setCircleUrls('')
    setPostUrls('')
    setQuantity(30)
    setAiAnalysisEnabled(true)
    setScreenshotEnabled(true)
  }

  function toggleCircleGroup(groupCircleIds: string[], checked: boolean) {
    setSelectedCircleIds((items) => checked
      ? [...new Set([...items, ...groupCircleIds])]
      : items.filter((id) => !groupCircleIds.includes(id)))
  }

  const currentEmpty =
    mode === 'circle_discovery'
      ? selectedCircleIds.length === 0 && lines(circleUrls).length === 0
      : lines(postUrls).length === 0

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <SheetTrigger asChild>
        <Button className='shadow-lg shadow-primary/20'>
          <Plus className='size-4' />
          新建提取
        </Button>
      </SheetTrigger>
      <SheetContent showClose={false} className='flex w-full flex-col gap-0 p-0 sm:max-w-xl'>
        <SheetHeader className='border-b p-6'>
          <div className='flex items-start justify-between gap-4'>
            <div>
              <SheetTitle className='text-xl'>新建提取</SheetTitle>
              <SheetDescription className='mt-1'>选择一种输入方式，提交时只读取当前模式。</SheetDescription>
            </div>
            <SheetClose asChild>
              <Button variant='ghost' size='icon' aria-label='关闭并放弃当前输入'>
                <X className='size-4' />
              </Button>
            </SheetClose>
          </div>
        </SheetHeader>
        <ScrollArea className='min-h-0 flex-1'>
          <div className='space-y-6 p-6'>
            <div className='space-y-2'>
              <Label>平台</Label>
              <Select value={platform} onValueChange={(value) => { setPlatform(value); setSelectedCircleIds([]) }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{availablePlatforms.map((item) => <SelectItem key={item.code} value={item.code}>{item.display_name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <RadioGroup value={mode} onValueChange={(value) => setMode(value as Mode)} className='grid grid-cols-2 gap-3'>
              <Label htmlFor='mode-circle' className='flex cursor-pointer gap-3 rounded-xl border p-4 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5'>
                <RadioGroupItem id='mode-circle' value='circle_discovery' className='mt-0.5' />
                <span><CircleDot className='mb-2 size-5 text-primary' /><b className='block text-sm'>圈子发现</b><span className='text-xs text-muted-foreground'>按圈子提取最新帖子</span></span>
              </Label>
              <Label htmlFor='mode-url' className='flex cursor-pointer gap-3 rounded-xl border p-4 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5'>
                <RadioGroupItem id='mode-url' value='url_list' className='mt-0.5' />
                <span><FileText className='mb-2 size-5 text-cyan-500' /><b className='block text-sm'>URL 清单</b><span className='text-xs text-muted-foreground'>逐条提取指定帖子</span></span>
              </Label>
            </RadioGroup>

            {mode === 'circle_discovery' ? (
              <div className='space-y-5'>
                <div className='space-y-2'>
                  <Label>已配置圈子</Label>
                  <div className='max-h-56 space-y-2 overflow-auto rounded-xl border p-2'>
                    {platformCircles.length ? listOrderGroups.map((group) => {
                      const groupCircles = platformCircles.filter((circle) => circle.list_order === group.value)
                      if (!groupCircles.length) return null
                      const groupCircleIds = groupCircles.map((circle) => circle.id)
                      const selectedCount = groupCircleIds.filter((id) => selectedCircleIds.includes(id)).length
                      const groupChecked = selectedCount === 0 ? false : selectedCount === groupCircles.length ? true : 'indeterminate'
                      return (
                        <Collapsible key={group.value} defaultOpen={false} className='overflow-hidden rounded-lg border bg-card/70'>
                          <div className='grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2 px-3 py-2'>
                            <Checkbox checked={groupChecked} onCheckedChange={(checked) => toggleCircleGroup(groupCircleIds, checked === true)} aria-label={`选择${group.label}全部来源`} />
                            <CollapsibleTrigger asChild>
                              <Button type='button' variant='ghost' className='group h-8 min-w-0 justify-between px-1 hover:bg-transparent' aria-label={`展开或收起${group.label}来源`}>
                                <span className='flex min-w-0 items-center gap-2'><span className='truncate text-sm font-medium'>{group.label}</span><Badge variant='secondary' className='font-normal'>{selectedCount}/{groupCircles.length}</Badge></span>
                                <ChevronDown className='size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180' />
                              </Button>
                            </CollapsibleTrigger>
                          </div>
                          <CollapsibleContent>
                            <div className='space-y-1 border-t p-2'>{groupCircles.map((circle) => {
                              const checked = selectedCircleIds.includes(circle.id)
                              return (
                                <label key={circle.id} className='flex cursor-pointer items-center gap-3 rounded-lg p-2 hover:bg-muted'>
                                  <Checkbox checked={checked} onCheckedChange={(nextChecked) => setSelectedCircleIds((items) => nextChecked === true ? [...new Set([...items, circle.id])] : items.filter((id) => id !== circle.id))} />
                                  <span className='min-w-0'><span className='block truncate text-sm font-medium'>{circle.name || circle.external_id}</span><span className='block truncate text-xs text-muted-foreground'>{circle.url}</span></span>
                                </label>
                              )
                            })}</div>
                          </CollapsibleContent>
                        </Collapsible>
                      )
                    }) : <div className='p-5 text-center text-sm text-muted-foreground'>暂无已配置圈子，可直接输入圈子链接。</div>}
                  </div>
                </div>
                <div className='space-y-2'><Label htmlFor='circle-urls'>临时圈子链接</Label><Textarea id='circle-urls' rows={5} value={circleUrls} onChange={(event) => setCircleUrls(event.target.value)} placeholder='每行一个圈子 URL' /><p className='text-xs text-muted-foreground'>临时链接验证成功后只进入手动圈子历史。</p></div>
                <div className='space-y-2'><Label htmlFor='quantity'>每圈有效结果目标数</Label><Input id='quantity' type='number' min={selectedPlatform?.quantity_range.min ?? 1} max={selectedPlatform?.quantity_range.max ?? 2000} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></div>
              </div>
            ) : (
              <div className='space-y-2'><Label htmlFor='post-urls'>帖子 URL 清单</Label><Textarea id='post-urls' rows={12} value={postUrls} onChange={(event) => setPostUrls(event.target.value)} placeholder='每行一个帖子 URL，重复链接会自动去重' /><p className='text-xs text-muted-foreground'>当前共识别 {lines(postUrls).length} 行非空输入。</p></div>
            )}
            <div className='grid gap-3 sm:grid-cols-2'>
              <label className='flex cursor-pointer items-center justify-between gap-3 rounded-xl border p-4'>
                <span><span className='block text-sm font-medium'>AI 舆情分析</span><span className='mt-1 block text-xs text-muted-foreground'>为本批次新帖子创建 AI 分析任务</span></span>
                <Switch checked={aiAnalysisEnabled} onCheckedChange={setAiAnalysisEnabled} />
              </label>
              <label className={`flex items-center justify-between gap-3 rounded-xl border p-4 ${mode === 'url_list' || !selectedPlatform?.capabilities.page_evidence ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}>
                <span><span className='block text-sm font-medium'>圈子页面截图</span><span className='mt-1 block text-xs text-muted-foreground'>{mode === 'url_list' ? 'URL 清单没有圈子列表页面' : selectedPlatform?.capabilities.page_evidence ? '保留原始全页并生成负面框选成果' : '当前平台尚未验证页面截图合同'}</span></span>
                <Switch checked={mode === 'circle_discovery' && Boolean(selectedPlatform?.capabilities.page_evidence) && screenshotEnabled} disabled={mode === 'url_list' || !selectedPlatform?.capabilities.page_evidence} onCheckedChange={setScreenshotEnabled} />
              </label>
            </div>
            <Alert><AlertTitle>提交范围</AlertTitle><AlertDescription>切换模式会保留两边输入；关闭窗口会直接放弃，提交只包含当前选择的模式。</AlertDescription></Alert>
          </div>
        </ScrollArea>
        <SheetFooter className='border-t bg-background/95 p-4 backdrop-blur'>
          <SheetClose asChild><Button variant='outline'>关闭</Button></SheetClose>
          <Button disabled={currentEmpty || submit.isPending} onClick={() => submit.mutate()}>
            {submit.isPending && <Loader2 className='size-4 animate-spin' />}
            提交提取
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function lines(value: string) {
  return [...new Set(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))]
}
