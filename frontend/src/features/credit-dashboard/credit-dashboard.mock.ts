import type { CreditDashboardData, CreditDashboardDataSource } from './credit-dashboard.types'

export const creditDashboardMockData: CreditDashboardData = {
  score: {
    score: 630,
    delta: 5,
    updatedAt: '5 days ago',
    grade: 'Excellent',
    history: [
      { date: '2026-08-01', score: 606 },
      { date: '2026-08-05', score: 615 },
      { date: '2026-08-10', score: 611 },
      { date: '2026-08-15', score: 625 },
      { date: '2026-08-20', score: 630 },
    ],
  },
  metrics: [
    { id: 'payments-on-time', label: 'Payments On Time', value: 24, denominator: '/38', tone: 'neutral', icon: 'calendar' },
    { id: 'credit-utilization', label: 'Credit Utilization', value: '22%', tone: 'positive', icon: 'card' },
  ],
  recentChanges: [
    { id: 'score-updated', title: 'Score updated', occurredAt: '5 days ago', delta: '+5 pts', tone: 'positive' },
    { id: 'payment-recorded', title: 'Payment recorded', occurredAt: '12 days ago', tone: 'neutral' },
  ],
  credits: [
    { id: 'home', title: 'Home', meta: '13 credits', icon: 'home', status: 'active' },
    { id: 'travel', title: 'Travel & dining', meta: '8 credits', icon: 'travel', status: 'inactive' },
  ],
  counters: { inquiries: 20, publicRecords: 10 },
}

/**
 * 本地演示数据源。生产页面传入 createCreditDashboardDataSource() 即可切换真实接口。
 */
export function createMockCreditDashboardDataSource(delayMs = 120): CreditDashboardDataSource {
  return {
    getDashboard: (_query, signal) => new Promise((resolve, reject) => {
      const timer = globalThis.setTimeout(() => resolve(creditDashboardMockData), delayMs)
      signal?.addEventListener('abort', () => {
        globalThis.clearTimeout(timer)
        reject(new DOMException('请求已取消', 'AbortError'))
      }, { once: true })
    }),
  }
}
