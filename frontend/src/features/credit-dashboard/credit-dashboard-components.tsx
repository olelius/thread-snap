import { ArrowUpRight, CalendarClock, Check, ChevronDown, CreditCard as CreditCardIcon, House, Search, TrendingUp } from 'lucide-react'
import type { CreditAccount, CreditChange, CreditDashboardData, CreditMetric, CreditScoreTab } from './credit-dashboard.types'

export const creditScoreTabs: Array<{ value: CreditScoreTab; label: string }> = [
  { value: 'transaction_score', label: 'Transaction Score' },
  { value: 'payments_on_time', label: 'Payments on Time' },
  { value: 'credit_utilization', label: 'Credit Utilization' },
]

export function CreditScoreTabs({ activeTab, onChange }: { activeTab: CreditScoreTab; onChange?: (tab: CreditScoreTab) => void }) {
  return <div className='credit-dashboard__tabs' role='tablist' aria-label='Credit score metrics'>
    {creditScoreTabs.map((tab) => <button key={tab.value} type='button' role='tab' aria-selected={activeTab === tab.value} className={`credit-dashboard__tab ${activeTab === tab.value ? 'is-active' : ''}`} onClick={() => onChange?.(tab.value)}>{tab.label}</button>)}
  </div>
}

export function CreditSearchField({ value, onChange }: { value: string; onChange?: (value: string) => void }) {
  return <label className='credit-dashboard__search'><Search className='size-4' aria-hidden='true' /><span className='sr-only'>Search credits</span><input value={value} onChange={(event) => onChange?.(event.target.value)} placeholder='Search' /></label>
}

export function CreditScoreCard({ data }: { data: CreditDashboardData }) {
  const max = Math.max(...data.score.history.map((point) => point.score), data.score.score)
  const min = Math.min(...data.score.history.map((point) => point.score), data.score.score)
  const points = data.score.history.map((point, index) => `${(index / Math.max(1, data.score.history.length - 1)) * 100},${70 - ((point.score - min) / Math.max(1, max - min)) * 48}`).join(' ')
  return <article className='credit-dashboard__score-card'>
    <div className='credit-dashboard__score-value'>{data.score.score}</div>
    <span className='credit-dashboard__delta'>+{data.score.delta} pts ↗</span>
    <div className='credit-dashboard__updated'><strong>{data.score.updatedAt}</strong><span>Updated</span></div>
    <span className='credit-dashboard__grade'>{data.score.grade}</span>
    <svg className='credit-dashboard__wave' viewBox='0 0 100 82' preserveAspectRatio='none' aria-label='Credit score trend' role='img'><polyline points={points} fill='none' stroke='currentColor' strokeWidth='0.35' vectorEffect='non-scaling-stroke' /></svg>
  </article>
}

export function CreditMetricCard({ metric }: { metric: CreditMetric }) {
  const Icon = metric.icon === 'calendar' ? CalendarClock : metric.icon === 'chart' ? TrendingUp : CreditCardIcon
  return <article className={`credit-dashboard__metric-card tone-${metric.tone ?? 'neutral'}`}><div className='credit-dashboard__metric-icon'><Icon className='size-4' aria-hidden='true' /></div><h2>{metric.label}</h2><div className='credit-dashboard__metric-value'>{metric.value}<span>{metric.denominator}</span></div><div className='credit-dashboard__dots' aria-hidden='true' /></article>
}

export function CreditSectionHeader({ title, count, counters }: { title: string; count?: number; counters?: CreditDashboardData['counters'] }) {
  return <header className='credit-dashboard__panel-header'><h2>{title}</h2>{typeof count === 'number' && <span className='credit-dashboard__count'>{count}</span>}{counters && <div className='credit-dashboard__counters'><span><strong>{counters.inquiries}</strong> Inquiries</span><span><strong>{counters.publicRecords}</strong> Public</span></div>}<ChevronDown className='size-4' aria-hidden='true' /></header>
}

export function CreditRecentChangeRow({ change }: { change: CreditChange }) {
  return <article className='credit-dashboard__change-row'><span className='credit-dashboard__change-icon'><Check className='size-4' aria-hidden='true' /></span><div><strong>{change.title}</strong><span>{change.occurredAt}</span></div>{change.delta && <em className={`tone-${change.tone ?? 'neutral'}`}>{change.delta}</em>}</article>
}

export function CreditAccountRow({ credit }: { credit: CreditAccount }) {
  return <article className='credit-dashboard__credit-row'><span className='credit-dashboard__credit-icon'>{credit.icon === 'home' ? <House className='size-3.5' /> : <CreditCardIcon className='size-3.5' />}</span><div><strong>{credit.title}</strong><span>{credit.meta}</span></div><button type='button' className='credit-dashboard__arrow' aria-label={`Open ${credit.title}`}><ArrowUpRight className='size-3.5' /></button></article>
}
