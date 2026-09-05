/**
 * 信用分数 Dashboard 的领域类型。
 * 这些类型是组件和后端适配器之间的唯一数据契约，避免组件直接依赖接口响应细节。
 */
export type CreditScoreTab = 'transaction_score' | 'payments_on_time' | 'credit_utilization'

export type CreditMetricTone = 'neutral' | 'positive' | 'warning'

export interface CreditScorePoint {
  date: string
  score: number
}

export interface CreditScoreSummary {
  score: number
  delta: number
  updatedAt: string
  grade: string
  history: CreditScorePoint[]
}

export interface CreditMetric {
  id: string
  label: string
  value: string | number
  denominator?: string
  tone?: CreditMetricTone
  icon?: 'calendar' | 'card' | 'chart'
}

export interface CreditChange {
  id: string
  title: string
  occurredAt: string
  delta?: string
  tone?: CreditMetricTone
}

export interface CreditAccount {
  id: string
  title: string
  meta: string
  icon?: 'home' | 'card' | 'travel'
  status?: 'active' | 'inactive'
}

export interface CreditDashboardData {
  score: CreditScoreSummary
  metrics: CreditMetric[]
  recentChanges: CreditChange[]
  credits: CreditAccount[]
  counters: {
    inquiries: number
    publicRecords: number
  }
}

export interface CreditDashboardQuery {
  tab?: CreditScoreTab
  search?: string
}

export interface CreditDashboardDataSource {
  getDashboard(query?: CreditDashboardQuery, signal?: AbortSignal): Promise<CreditDashboardData>
}
