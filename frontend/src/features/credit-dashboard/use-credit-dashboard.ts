import { useQuery } from '@tanstack/react-query'
import type { CreditDashboardDataSource, CreditDashboardQuery } from './credit-dashboard.types'

/**
 * 使用统一的 Query Key 管理 Dashboard 数据缓存和刷新。
 */
export function useCreditDashboard(dataSource: CreditDashboardDataSource, query: CreditDashboardQuery) {
  return useQuery({
    queryKey: ['credit-dashboard', query],
    queryFn: ({ signal }) => dataSource.getDashboard(query, signal),
  })
}
