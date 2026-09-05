import { useMemo, useRef, useState } from 'react'
import { motion, useMotionValue, useReducedMotion, useSpring } from 'motion/react'
import { Activity, ArrowUpRight, Check, CircleAlert, FileStack, FolderOpen, LayoutList, Sparkles, Waves } from 'lucide-react'
import type { Run } from '@/lib/types'
import { formatDate } from '@/lib/api'

const fallbackCards = [
  { label: '提取工作台', meta: '等待真实批次数据', tone: 'neutral' },
  { label: '来源快照', meta: '冻结列表证据', tone: 'blue' },
  { label: '口碑巡检', meta: '指标与页面证据', tone: 'green' },
  { label: '循环计划', meta: '持久 FIFO 队列', tone: 'violet' },
  { label: '配置版本', meta: '规则与节点快照', tone: 'amber' },
  { label: '团队协作', meta: '循环批次队列', tone: 'green' },
  { label: '数据分析', meta: '排名与页面证据', tone: 'blue' },
  { label: '知识库', meta: '手动来源历史', tone: 'neutral' },
] as const

type WorkspaceVisualProps = {
  runs: Run[]
  kind: 'extraction' | 'recurring'
  onOpen: (run: Run) => void
}

/**
 * 工作台的可交互视觉层。卡片选择只更新右侧检查器，只有明确点击“打开批次”才进入详情，
 * 避免鼠标探索被路由切换打断，同时所有指标都明确标注为当前页口径。
 */
export function WorkspaceVisual({ runs, kind, onOpen }: WorkspaceVisualProps) {
  const reduceMotion = useReducedMotion()
  const stageRef = useRef<HTMLDivElement>(null)
  const pointerX = useMotionValue(0)
  const pointerY = useMotionValue(0)
  const rotateX = useSpring(pointerY, { stiffness: 120, damping: 18, mass: 0.8 })
  const rotateY = useSpring(pointerX, { stiffness: 120, damping: 18, mass: 0.8 })
  const [selectedId, setSelectedId] = useState<string>()

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedId) ?? runs[0],
    [runs, selectedId],
  )
  const cards = runs.length > 0 ? runs.slice(0, 8) : fallbackCards
  const activeCount = runs.filter((run) => ['queued', 'running', 'waiting_for_auth'].includes(run.status)).length
  const completedCount = runs.filter((run) => run.status === 'success').length
  const attentionCount = runs.filter((run) => ['failed', 'partial_success', 'waiting_for_auth'].includes(run.status)).length
  const total = runs.length

  function updatePointer(event: React.PointerEvent<HTMLDivElement>) {
    if (reduceMotion || !stageRef.current || event.pointerType === 'touch') return
    const bounds = stageRef.current.getBoundingClientRect()
    const x = (event.clientX - bounds.left) / bounds.width - 0.5
    const y = (event.clientY - bounds.top) / bounds.height - 0.5
    pointerX.set(x * 3.5)
    pointerY.set(y * -2.5)
  }

  function resetPointer() {
    pointerX.set(0)
    pointerY.set(0)
  }

  function selectRun(run: Run) {
    setSelectedId(run.id)
  }

  const progress = selectedRun?.planned_count
    ? Math.min(100, Math.round(((selectedRun.completed_count + selectedRun.failed_count) / selectedRun.planned_count) * 100))
    : 0

  return (
    <section className='workspace-visual' aria-label='任务管理工作台'>
      <div className='workspace-visual__ambient workspace-visual__ambient--one' />
      <div className='workspace-visual__ambient workspace-visual__ambient--two' />
      <div className='workspace-visual__header'>
        <div>
          <div className='workspace-kicker'><Sparkles className='size-3.5' />实时工作台</div>
          <h1>{kind === 'recurring' ? '循环计划控制台' : '任务管理'}</h1>
          <p>{kind === 'recurring' ? '按持久计划查看独立触发批次。' : '把批次、证据和队列状态收拢到一个可操作的空间。'}</p>
        </div>
        <div className='workspace-live-pill'><span className='workspace-live-dot' />数据来自当前批次</div>
      </div>

      <div className='workspace-kpi-grid'>
        <MetricCard icon={FileStack} label='当前页批次' value={total} detail={total ? '已加载列表页' : '等待批次数据'} tone='blue' />
        <MetricCard icon={Activity} label='当前页进行中' value={activeCount} detail='队列与处理中' tone='violet' />
        <MetricCard icon={Check} label='当前页已完成' value={completedCount} detail='成功终态批次' tone='green' />
        <MetricCard icon={CircleAlert} label='当前页需关注' value={attentionCount} detail='失败或等待会话' tone='amber' />
      </div>

      <div className='workspace-main-grid'>
        <aside className='workspace-task-rail' aria-label='当前页任务队列'>
          <div className='workspace-task-rail__heading'>
            <div><span className='workspace-section-label'>任务队列</span><span className='workspace-section-note'>当前页批次</span></div>
            <LayoutList className='size-4 text-emerald-300/80' aria-hidden='true' />
          </div>
          <div className='workspace-task-rail__tabs' aria-hidden='true'><span className='is-active'>全部</span><span>进行中</span><span>已完成</span></div>
          <div className='workspace-task-rail__list'>
            {runs.length ? runs.slice(0, 7).map((run) => (
              <button key={run.id} type='button' className={`workspace-task-rail__item ${run.id === selectedRun?.id ? 'is-selected' : ''}`} onClick={() => selectRun(run)}>
                <span className={`workspace-task-rail__dot workspace-task-rail__dot--${statusTone(run.status)}`} />
                <span className='min-w-0'><strong>{run.number}</strong><small>{run.source_names?.[0] || run.circle_names?.[0] || statusLabel(run.status)}</small></span>
                <ArrowUpRight className='size-3.5' />
              </button>
            )) : (
              <div className='workspace-task-rail__empty'><FileStack className='size-5' /><strong>等待批次数据</strong><small>真实批次进入后会显示在这里。</small></div>
            )}
          </div>
          <div className='workspace-task-rail__footer'><span className='workspace-live-dot' /> SSE 状态流</div>
        </aside>
        <div
          ref={stageRef}
          className='workspace-stage-shell'
          onPointerMove={updatePointer}
          onPointerLeave={resetPointer}
        >
          <div className='workspace-stage-heading'>
            <div>
              <span className='workspace-section-label'>项目文档</span>
              <span className='workspace-section-note'>悬停查看层次 · 点击选择批次</span>
            </div>
            <Waves className='size-4 text-emerald-300/80' aria-hidden='true' />
          </div>
          <motion.div
            className='workspace-stage'
            style={{ rotateX, rotateY, transformPerspective: 1200 }}
            transition={{ type: 'spring', stiffness: 120, damping: 20 }}
          >
            <div className='workspace-stage__glow' />
            <div className='workspace-stage__grid' />
            <div className='dashboard-file-stack' style={{ '--card-center': (cards.length - 1) / 2, '--fan-step': cards.length > 5 ? '2.5rem' : '4.8rem' } as React.CSSProperties}>
              {cards.map((item, index) => {
                const run = 'id' in item ? item : undefined
                const fallback = 'label' in item ? item : (fallbackCards[index] ?? fallbackCards[0])
                const label = run?.number ?? fallback.label
                const meta = run ? statusLabel(run.status) : fallback.meta
                const tone = run ? statusTone(run.status) : fallback.tone
                return (
                  <button
                    key={run?.id ?? fallback.label}
                    type='button'
                    className={`dashboard-file-card dashboard-file-card--${tone} ${run && run.id === selectedRun?.id ? 'is-selected' : ''}`}
                    style={{ '--card-index': index } as React.CSSProperties}
                    onClick={() => run && selectRun(run)}
                    aria-disabled={!run}
                    aria-label={run ? `查看批次 ${label}` : `${label}，暂无批次`}
                  >
                    <span className='dashboard-file-card__shine' />
                    <span className='dashboard-file-card__icon'><FolderOpen className='size-5' /></span>
                    <span className='dashboard-file-card__body'>
                      <strong>{label}</strong>
                      <small>{meta}</small>
                    </span>
                    <ArrowUpRight className='dashboard-file-card__arrow size-4' />
                  </button>
                )
              })}
            </div>
            <div className='workspace-stage__caption'>
              <span>ThreadSnap / {kind === 'recurring' ? 'RECURRING' : 'RUNS'}</span>
              <span>{selectedRun ? '已绑定真实批次' : '等待首个批次'}</span>
            </div>
          </motion.div>
        </div>

        <aside className='workspace-inspector'>
          <div className='workspace-inspector__top'>
            <div>
              <span className='workspace-section-label'>批次详情</span>
              <span className='workspace-section-note'>选择层</span>
            </div>
            <span className='workspace-inspector__search'><Sparkles className='size-3.5' /></span>
          </div>
          {selectedRun ? (
            <div className='workspace-inspector__content'>
              <div className='workspace-inspector__id'>{selectedRun.number}</div>
              <h2>{selectedRun.status_name}</h2>
              <p>{selectedRun.source_names?.join('、') || selectedRun.circle_names?.join('、') || `${selectedRun.circle_count} 个来源`}</p>
              <div className='workspace-detail-list'>
                <DetailRow label='创建时间' value={formatDate(selectedRun.created_at)} />
                <DetailRow label='完成进度' value={`${selectedRun.completed_count} / ${selectedRun.planned_count}`} />
                <DetailRow label='当前状态' value={selectedRun.status_name} tone={statusTone(selectedRun.status)} />
              </div>
              <div className='workspace-progress'>
                <div className='workspace-progress__label'><span>批次进度</span><strong>{progress}%</strong></div>
                <div className='workspace-progress__track'><span style={{ width: `${progress}%` }} /></div>
              </div>
              <button type='button' className='workspace-inspector__open' onClick={() => onOpen(selectedRun)}>
                打开批次详情 <ArrowUpRight className='size-3.5' />
              </button>
            </div>
          ) : (
            <div className='workspace-inspector__empty'>
              <div className='workspace-inspector__empty-icon'><FileStack className='size-5' /></div>
              <strong>等待批次进入工作台</strong>
              <p>创建手动提取或等待计划触发后，详情会绑定到真实批次。</p>
            </div>
          )}
        </aside>
      </div>
      <WorkspaceTimeline runs={runs} selectedId={selectedRun?.id} onSelect={selectRun} />
    </section>
  )
}

function WorkspaceTimeline({ runs, selectedId, onSelect }: { runs: Run[]; selectedId?: string; onSelect: (run: Run) => void }) {
  if (!runs.length) return null
  const visibleRuns = runs.slice(0, 8)
  return (
    <div className='workspace-timeline' aria-label='当前页批次时间线'>
      <div className='workspace-timeline__heading'>
        <div><span className='workspace-section-label'>批次时间线</span><span className='workspace-section-note'>当前页创建顺序 · 显示前 8 条</span></div>
        <span className='workspace-timeline__count'>{visibleRuns.length} / {runs.length} 个批次</span>
      </div>
      <div className='workspace-timeline__track'>
        {visibleRuns.map((run, index) => (
          <button key={run.id} type='button' className={`workspace-timeline__item ${run.id === selectedId ? 'is-selected' : ''}`} onClick={() => onSelect(run)}>
            <span className={`workspace-timeline__dot workspace-timeline__dot--${statusTone(run.status)}`} />
            <span className='workspace-timeline__line' aria-hidden='true' />
            <span className='workspace-timeline__meta'>#{index + 1} · {formatDate(run.created_at)}</span>
            <strong>{run.number}</strong>
            <small>{statusLabel(run.status)}</small>
          </button>
        ))}
      </div>
    </div>
  )
}

function MetricCard({ icon: Icon, label, value, detail, tone }: { icon: typeof FileStack; label: string; value: number; detail: string; tone: string }) {
  return (
    <div className={`workspace-metric workspace-metric--${tone}`}>
      <div className='workspace-metric__top'><span>{label}</span><Icon className='size-4' /></div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  )
}

function DetailRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div className='workspace-detail-row'><span>{label}</span><strong className={`workspace-detail-row__value${tone ? ` workspace-detail-row__value--${tone}` : ''}`}>{value}</strong></div>
}

function statusLabel(value: Run['status']) {
  return { queued: '排队中', running: '提取中', waiting_for_auth: '等待平台会话', success: '已完成', partial_success: '部分成功', failed: '失败' }[value] ?? '状态未知'
}

function statusTone(value: Run['status']) {
  return { queued: 'violet', running: 'blue', waiting_for_auth: 'amber', success: 'green', partial_success: 'amber', failed: 'red' }[value] ?? 'neutral'
}
