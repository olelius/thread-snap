import { useMemo, useState } from 'react'
import { Bell, CalendarClock, ChevronDown, CreditCard as CreditCardIcon, House, TrendingUp } from 'lucide-react'
import type { CreditDashboardData, CreditDashboardQuery } from './credit-dashboard.types'
import { CreditAccountRow, CreditMetricCard, CreditRecentChangeRow, CreditScoreCard, CreditScoreTabs, CreditSearchField, CreditSectionHeader } from './credit-dashboard-components'
import './credit-dashboard.css'

export interface CreditDashboardTemplateProps {
  data?: CreditDashboardData
  query?: CreditDashboardQuery
  loading?: boolean
  error?: string
  onRetry?: () => void
  onQueryChange?: (query: CreditDashboardQuery) => void
}

/**
 * 可复用的 Dashboard 组合模板。
 * 组件只接收数据和事件，不负责请求；CreditDashboardPage 可在外层接入 React Query。
 */
export function CreditDashboardTemplate({
  data,
  query = { tab: 'transaction_score', search: '' },
  loading = false,
  error,
  onRetry,
  onQueryChange,
}: CreditDashboardTemplateProps) {
  const activeTab = query.tab ?? 'transaction_score'
  const [filter, setFilter] = useState<'all' | 'active' | 'inactive'>('all')

  const visibleCredits = useMemo(() => {
    const search = query.search?.trim().toLowerCase()
    const filtered = (data?.credits ?? []).filter((item) => filter === 'all' || (item.status ?? 'active') === filter)
    if (!search) return filtered
    return filtered.filter((item) => `${item.title} ${item.meta}`.toLowerCase().includes(search))
  }, [data?.credits, filter, query.search])

  return (
    <section className='credit-dashboard' aria-label='Credit Score Management'>
      <aside className='credit-dashboard__rail' aria-label='Primary navigation'>
        <div className='credit-dashboard__brand' aria-label='Dashboard home'>
          <TrendingUp className='size-5' aria-hidden='true' />
        </div>
        <nav className='credit-dashboard__nav'>
          <RailButton label='Overview'><House aria-hidden='true' /></RailButton>
          <RailButton label='Calendar'><CalendarClock aria-hidden='true' /></RailButton>
          <RailButton label='Analytics'><TrendingUp aria-hidden='true' /></RailButton>
          <span className='credit-dashboard__divider' />
          <RailButton label='Credit score' active><CreditCardIcon aria-hidden='true' /></RailButton>
          <RailButton label='Notifications'><Bell aria-hidden='true' /></RailButton>
        </nav>
      </aside>

      <div className='credit-dashboard__main'>
        <header className='credit-dashboard__topbar'>
          <div className='credit-dashboard__identity'>
            <div className='credit-dashboard__avatar' aria-hidden='true'>JB</div>
            <span>James Brown</span>
            <ChevronDown className='size-4' aria-hidden='true' />
          </div>
          <button type='button' className='credit-dashboard__icon-button' aria-label='Notifications'><Bell className='size-4' /></button>
        </header>

        <div className='credit-dashboard__content'>
          <div className='credit-dashboard__column credit-dashboard__column--primary'>
            <div className='credit-dashboard__heading'>
              <h1>Credit Score Management</h1>
              <p>Track and improve your credit status</p>
            </div>
            <CreditScoreTabs activeTab={activeTab} onChange={(tab) => onQueryChange?.({ ...query, tab })} />
            {loading && <DashboardSkeleton />}
            {error && !loading && <DashboardError message={error} onRetry={onRetry} />}
            {data && !loading && !error && <>
              <CreditScoreCard data={data} />
              <section className='credit-dashboard__panel'>
                <CreditSectionHeader title='Recent Changes' count={data.recentChanges.length} />
                <div className='credit-dashboard__changes'>
                  {data.recentChanges.map((change) => <CreditRecentChangeRow key={change.id} change={change} />)}
                </div>
              </section>
            </>}
          </div>

          <div className='credit-dashboard__column credit-dashboard__column--secondary'>
            <CreditSearchField value={query.search ?? ''} onChange={(search) => onQueryChange?.({ ...query, search })} />
            <div className='credit-dashboard__metrics'>
              {(data?.metrics ?? []).map((metric) => <CreditMetricCard key={metric.id} metric={metric} />)}
            </div>
            <section className='credit-dashboard__panel credit-dashboard__panel--credits'>
              <CreditSectionHeader title='Your credits' counters={data?.counters} />
              <div className='credit-dashboard__filters' role='tablist' aria-label='Credit filters'>
                {(['all', 'active', 'inactive'] as const).map((value) => <button key={value} type='button' className={`credit-dashboard__filter ${filter === value ? 'is-active' : ''}`} aria-selected={filter === value} onClick={() => setFilter(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}
              </div>
              <div className='credit-dashboard__credits'>
                {visibleCredits.length ? visibleCredits.map((credit) => <CreditAccountRow key={credit.id} credit={credit} />) : <p className='credit-dashboard__empty'>No credits match the search.</p>}
              </div>
            </section>
          </div>
        </div>
      </div>
    </section>
  )
}

function RailButton({ label, active = false, children }: { label: string; active?: boolean; children: React.ReactNode }) {
  return <button type='button' className={`credit-dashboard__rail-button ${active ? 'is-active' : ''}`} aria-label={label} aria-current={active ? 'page' : undefined}>{children}</button>
}

function DashboardSkeleton() {
  return <div className='credit-dashboard__skeleton' aria-label='Loading dashboard'><span /><span /><span /></div>
}

function DashboardError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className='credit-dashboard__error' role='alert'><strong>Dashboard unavailable</strong><span>{message}</span>{onRetry && <button type='button' onClick={onRetry}>Retry</button>}</div>
}
