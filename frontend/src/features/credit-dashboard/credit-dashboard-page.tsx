import { useMemo, useState } from 'react'
import { createMockCreditDashboardDataSource } from './credit-dashboard.mock'
import { CreditDashboardTemplate } from './credit-dashboard-template'
import { useCreditDashboard } from './use-credit-dashboard'
import type { CreditDashboardDataSource, CreditDashboardQuery } from './credit-dashboard.types'

export interface CreditDashboardPageProps {
  /** 生产环境传入真实接口适配器；省略时使用可交互的本地模板数据。 */
  dataSource?: CreditDashboardDataSource
  initialQuery?: CreditDashboardQuery
}

/**
 * 带数据加载生命周期的页面模板。
 * 业务路由只需替换 dataSource，不需要修改视觉组件和状态处理。
 */
export function CreditDashboardPage({ dataSource, initialQuery = { tab: 'transaction_score', search: '' } }: CreditDashboardPageProps) {
  const source = useMemo(() => dataSource ?? createMockCreditDashboardDataSource(), [dataSource])
  const [query, setQuery] = useState<CreditDashboardQuery>(initialQuery)
  const result = useCreditDashboard(source, query)
  const error = result.error instanceof Error ? result.error.message : result.error ? 'Request failed' : undefined

  return <CreditDashboardTemplate data={result.data} query={query} loading={result.isLoading} error={error} onRetry={() => void result.refetch()} onQueryChange={setQuery} />
}
