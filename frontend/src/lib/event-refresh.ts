import type { Query, QueryClient, QueryKey } from '@tanstack/react-query'

/** 合并事件失效通知；在途查询只留一个尾部刷新，HTTP 结果仍是唯一数据来源。 */
export function createEventRefresh(client: QueryClient) {
  const cache = client.getQueryCache()
  const pending = new Set<Query>()
  let timer: ReturnType<typeof setTimeout> | undefined
  let lastRefreshAt = Date.now()
  let disposed = false

  function schedule() {
    if (disposed || timer !== undefined) return
    // 慢请求和离线暂停交由查询状态通知唤醒，不为它们永久轮询。
    if (![...pending].some((query) => query.isActive() && query.state.fetchStatus === 'idle')) return
    timer = setTimeout(() => {
      timer = undefined
      flush([...pending])
    }, Math.max(0, lastRefreshAt + 1_000 - Date.now()))
  }

  function flush(queries: Query[]) {
    const ready = queries.filter((query) => pending.has(query) && query.isActive() && query.state.fetchStatus === 'idle')
    if (ready.length) lastRefreshAt = Date.now()
    for (const query of ready) {
      // 必须在发请求前消费标记；本轮成功本身不应再生成下一轮。
      pending.delete(query)
      void client.refetchQueries({ queryKey: query.queryKey, exact: true, type: 'active' }, { cancelRefetch: false })
    }
    schedule()
  }

  const unsubscribe = cache.subscribe(({ type, query }) => {
    if (!pending.has(query)) return
    if (type === 'removed') {
      pending.delete(query)
    } else if (!query.isActive()) {
      pending.delete(query)
      // 卸载取消可能恢复旧状态；保留失效标记供下次进入页面读取。
      query.invalidate()
    } else if (query.state.fetchStatus === 'idle') {
      schedule()
    }
  })

  return {
    /** 普通通知至多约每秒一轮；重连等恢复入口立即刷新空闲查询。 */
    invalidate(queryKey?: QueryKey, immediate = false) {
      if (disposed) return
      const queries = cache.findAll({ queryKey })
      for (const query of queries) {
        query.invalidate()
        // 不激活历史筛选页或其它无观察者缓存，也不为它们保存尾轮。
        if (query.isActive()) pending.add(query)
      }
      if (immediate) flush(queries)
      else schedule()
    },
    /** 事件桥卸载时只清理本协调器；请求取消由查询观察者和 AbortSignal 负责。 */
    dispose() {
      disposed = true
      if (timer !== undefined) clearTimeout(timer)
      pending.clear()
      unsubscribe()
    },
  }
}
