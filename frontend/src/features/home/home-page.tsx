import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'
import { ArrowUpRight, ChartNoAxesCombined, CircleAlert, Clock3, FolderOpen, Layers3, LayoutList, RefreshCw, Repeat2, Sparkles } from 'lucide-react'
import { NewExtractionSheet } from '@/features/runs/new-extraction-sheet'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { SpotlightCard } from '@/components/react-bits/spotlight-card'
import { CountUp } from '@/components/react-bits/count-up'
import { api, errorMessage, formatDate } from '@/lib/api'
import './home-page.css'

type Kind = 'extraction' | 'recurring' | 'reputation'
type Batch = {
  id: string; number: string; status: string; planned_count: number; completed_count: number;
  failed_count: number; created_at: string; finished_at: string | null; planned_date?: string; source_type?: string;
}
type Category = {
  key: Kind; label: string; total: number; today: number; active: number; attention: number;
  today_basis: 'created_at' | 'planned_date'; recent: Batch[]; attention_items: Batch[];
}
type Dashboard = { generated_at: string; timezone: string; date: string; categories: Category[] }
const kinds = [
  { key: 'extraction' as const, label: '提取批次', description: '手动与每周计划', icon: LayoutList },
  { key: 'recurring' as const, label: '循环批次', description: '独立周期快照', icon: Repeat2 },
  { key: 'reputation' as const, label: '口碑巡检', description: '正式巡检与真实验收', icon: ChartNoAxesCombined },
]
const statuses: Record<string, string> = { queued: '排队中', running: '进行中', waiting_for_auth: '等待会话', success: '成功', partial_success: '部分成功', failed: '失败', deleted: '已删除' }
const emptySearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, listOrder: undefined, from: undefined, to: undefined }
const detailSearch = { view: undefined, page: undefined, pageSize: undefined, title: undefined, sources: undefined, visibility: undefined, sentiment: undefined, analysisStatus: undefined, sort: undefined, direction: undefined, post: undefined }

/** 首页只消费全量聚合接口；列表筛选/分页不改变首页统计口径。 */
export function HomePage() {
  const navigate = useNavigate()
  const reduceMotion = useReducedMotion()
  const [kind, setKind] = useState<Kind>('extraction')
  const [selection, setSelection] = useState<string>()
  const query = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api<Dashboard>('/dashboard', undefined, 20_000),
    refetchInterval: ({ state }) => state.data?.categories.some((category) => category.active > 0) ? 3_000 : 60_000,
  })
  const category = query.data?.categories.find((item) => item.key === kind)
  const current = category?.recent.find((item) => item.id === selection) ?? category?.recent[0]
  const unavailable = query.isError || query.isLoading
  const progress = current?.planned_count ? Math.min(100, Math.round((current.completed_count + current.failed_count) / current.planned_count * 100)) : 0

  function openBatch(key: Kind, item: Batch) {
    if (key === 'reputation') navigate({ to: '/reputation/runs/$runId', params: { runId: item.id }, search: { view: 'ranking' } })
    else navigate({ to: key === 'recurring' ? '/recurring-runs/$runId' : '/runs/$runId', params: { runId: item.id }, search: detailSearch })
  }

  return (
    <div className='home-page'>
      <header className='home-heading'>
        <div><span className='home-eyebrow'><Sparkles size={14} /> THREADSNAP · 首页</span><h1>让每一次快照，<span>井然有序。</span></h1><p>看全局进展，处理待关注批次，再轻盈地回到工作中。</p></div>
        <div className='home-heading-actions'><span className='home-date'><Clock3 size={14} />{query.data?.date ?? '正在读取日期'} · 上海时间</span><div><Button variant='outline' size='icon' aria-label='刷新首页' onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw className={`size-4 ${query.isFetching ? 'animate-spin' : ''}`} /></Button><NewExtractionSheet /></div></div>
      </header>
      {query.isError && <div role='alert' className='home-error'><CircleAlert size={18} /><div><strong>首页数据暂未取得</strong><p>{errorMessage(query.error)}{query.data ? ' 当前仍展示上次成功读取的摘要，统计以刷新成功为准。' : ''}</p></div><Button variant='outline' onClick={() => query.refetch()}>重试</Button></div>}

      <section className='home-metrics' aria-label='全局批次统计'>
        {kinds.map(({ key, label, description, icon: Icon }, index) => {
          const value = query.data?.categories.find((item) => item.key === key)
          return <motion.article key={key} className='home-metric-entry' initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .24, delay: index * .04 }}>
            <SpotlightCard className={`home-metric home-metric--${key}`}>
            <div className='home-metric-heading'><span className='home-module-icon'><Icon size={21} /></span><div><h2>{label}</h2><p>{description}</p></div><span className='home-metric-index'>0{index + 1}</span></div>
            <div className='home-total'><strong data-home-total={key}><CountUp value={unavailable ? undefined : value?.total} /></strong><span>累计现存批次</span></div>
            <dl className='home-counts'><div><dt>{key === 'reputation' ? '今日巡检 / 基线' : '今日创建'}</dt><dd>{unavailable ? '—' : value?.today ?? '—'}</dd></div><div><dt>当前处理中</dt><dd>{unavailable ? '—' : value?.active ?? '—'}</dd></div><div><dt>原批次需关注</dt><dd>{unavailable ? '—' : value?.attention ?? '—'}</dd></div></dl>
            </SpotlightCard>
          </motion.article>
        })}
      </section>
      <div className='home-scope-note'>统计覆盖全部现存记录，不受列表分页影响；口碑巡检不计补跑及合成测试。处理中包括排队、运行和等待会话。</div>

      <section className='home-workbench home-surface' aria-labelledby='home-recent-title'>
        <div className='home-section-heading'><div><span className='home-eyebrow'>继续你的工作</span><h2 id='home-recent-title'>近期批次</h2></div><span className='home-section-hint'>每类最近 8 个 · 选择后查看摘要</span></div>
        <div className='home-segments' role='group' aria-label='选择近期批次类别'>
          {kinds.map(({ key, label, icon: Icon }) => <button key={key} className='home-segment' type='button' aria-pressed={key === kind} onClick={() => { setKind(key); setSelection(undefined) }}>{key === kind && <motion.span className='home-segment-active' layoutId='home-category' transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 400, damping: 32 }} aria-hidden='true' />}<Icon size={16} />{label}</button>)}
        </div>
        <div className='home-batch-layout'>
          <div className='home-batch-list' role='group' aria-label='近期批次快选'>
            {query.isLoading ? <div className='home-empty' role='status'>正在加载批次…</div> : category?.recent.length ? category.recent.map((item, index) => <motion.button type='button' key={item.id} className='home-batch' aria-pressed={current?.id === item.id} onClick={() => setSelection(item.id)} whileTap={reduceMotion ? undefined : { scale: .985, y: 2 }} transition={{ type: 'spring', stiffness: 380, damping: 24 }}>
              <span className='home-batch-index'>{String(index + 1).padStart(2, '0')}</span><span className='home-batch-copy'><strong>{item.number}</strong><small>{item.planned_date ? `${item.source_type === 'real_acceptance' ? '真实验收基线' : '正式巡检'} · ${item.planned_date}` : formatDate(item.created_at)}</small></span><StatusBadge value={item.status} label={statuses[item.status] ?? item.status} />
            </motion.button>) : <div className='home-empty'><FolderOpen size={30} /><strong>{query.isError ? '等待首页数据恢复' : '暂无该类批次'}</strong><p>{query.isError ? '点击上方重试，或从导航进入业务列表。' : '创建任务或计划触发后，近期摘要会出现在这里。'}</p></div>}
          </div>
          <aside className='home-inspector' aria-label='选中批次摘要'>
            <span className='home-eyebrow'><Layers3 size={14} /> 批次摘要</span>
            {current ? <motion.div key={`${kind}-${current.id}`} className='home-inspector-content' initial={reduceMotion ? false : { opacity: .4, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .2 }}>
              <span className='home-selected-number'>{current.number}</span><h3>{statuses[current.status] ?? current.status}</h3>
              <dl className='home-detail-list'><div><dt>所属模块</dt><dd>{category?.label}</dd></div><div><dt>创建时间</dt><dd>{formatDate(current.created_at)}</dd></div>{current.planned_date && <div><dt>{current.source_type === 'real_acceptance' ? '真实验收基线日期' : '计划日期'}</dt><dd>{current.planned_date}</dd></div>}<div><dt>已完成 / 目标</dt><dd>{current.completed_count} / {current.planned_count}</dd></div><div><dt>失败项</dt><dd>{current.failed_count}</dd></div></dl>
              <div className='home-progress'><span>处理进度 <strong>{progress}%</strong></span><Progress value={progress} /></div><p>摘要保留原批次状态；关联补跑与完整证据请进入详情查看。</p>
              <Button className='home-open-detail' onClick={() => openBatch(kind, current)}>打开批次详情<ArrowUpRight size={16} /></Button>
            </motion.div> : <div className='home-empty'><Layers3 size={28} /><p>选择一个批次，继续查看它的快照。</p></div>}
          </aside>
        </div>
        <div className='home-workbench-footer'><span>最近更新：{formatDate(query.data?.generated_at)}</span>{kind === 'reputation' ? <Link to='/reputation' search={{ tab: 'runs', page: undefined }}>查看全部巡检<ArrowUpRight size={14} /></Link> : <Link to={kind === 'recurring' ? '/recurring-runs' : '/runs'} search={emptySearch}>查看完整列表<ArrowUpRight size={14} /></Link>}</div>
      </section>

      <section className='home-attention home-surface' aria-labelledby='home-attention-title'>
        <div className='home-section-heading'><div><span className='home-eyebrow'>按模块分别处理</span><h2 id='home-attention-title'>值得留意</h2></div><CircleAlert size={18} /></div>
        <p className='home-attention-note'>累计部分成功、失败或等待会话的原批次，每类展示最近 3 个；不表示关联补跑仍有缺口。</p>
        <div className='home-attention-grid'>{kinds.map(({ key, label, icon: Icon }) => {
          const items = query.data?.categories.find((item) => item.key === key)?.attention_items ?? []
          return <div className='home-attention-group' key={key}><h3><Icon size={16} />{label}</h3>{items.length ? items.map((item) => <button type='button' key={item.id} onClick={() => openBatch(key, item)}><span>{item.number}<small>{statuses[item.status] ?? item.status}</small></span><ArrowUpRight size={15} /></button>) : <p>{unavailable ? '等待数据' : '暂无需关注的原批次'}</p>}</div>
        })}</div>
      </section>
    </div>
  )
}
