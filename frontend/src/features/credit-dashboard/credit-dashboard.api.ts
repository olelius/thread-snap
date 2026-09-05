import { api, queryString } from '@/lib/api'
import type { CreditDashboardData, CreditDashboardDataSource, CreditDashboardQuery } from './credit-dashboard.types'

export const defaultCreditDashboardEndpoint = '/credit-dashboard'

/**
 * 创建真实接口数据源。endpoint 由后端路由决定，组件只依赖 CreditDashboardDataSource。
 */
export function createCreditDashboardDataSource(
  endpoint = defaultCreditDashboardEndpoint,
  request: typeof api = api,
): CreditDashboardDataSource {
  return {
    getDashboard: (query?: CreditDashboardQuery, signal?: AbortSignal) =>
      request<CreditDashboardData>(`${endpoint}${queryString((query ?? {}) as Record<string, unknown>)}`, { signal }),
  }
}
