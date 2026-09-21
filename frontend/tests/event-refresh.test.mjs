import assert from 'node:assert/strict'
import test from 'node:test'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { createEventRefresh } from '../src/lib/event-refresh.ts'
import { api } from '../src/lib/api.ts'

async function settle() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve()
}

function setup(t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 10_000 })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
  const refresh = createEventRefresh(client)
  t.after(() => { refresh.dispose(); client.clear() })
  return { client, refresh }
}

function observe(t, client, queryKey) {
  const calls = []
  client.setQueryData(queryKey, { status: 'running', completed_count: 0 })
  const observer = new QueryObserver(client, {
    queryKey,
    queryFn: ({ signal }) => new Promise((resolve, reject) => {
      const call = { resolve, reject, signal }
      calls.push(call)
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }),
  })
  const unsubscribe = observer.subscribe(() => {})
  t.after(unsubscribe)
  return { calls, observer, unsubscribe }
}

test('突发通知合并列表、详情、帖子、首页，历史筛选和禁用缓存不发请求', async (t) => {
  const { client, refresh } = setup(t)
  const keys = [['runs', 'extraction', { page: 1 }], ['run', 'r1'], ['posts', 'r1', 1], ['dashboard']]
  const observed = keys.map((key) => observe(t, client, key))
  const inactiveKey = ['runs', 'extraction', { page: 2 }]
  client.setQueryData(inactiveKey, { status: 'success' })
  let disabledCalls = 0
  const disabled = new QueryObserver(client, { queryKey: ['posts', 'r2'], enabled: false, queryFn: async () => { disabledCalls += 1; return {} } })
  const unsubscribeDisabled = disabled.subscribe(() => {})
  t.after(unsubscribeDisabled)
  for (let index = 0; index < 100; index += 1) {
    for (const key of [['runs'], ['run', 'r1'], ['posts'], ['dashboard']]) refresh.invalidate(key)
  }
  t.mock.timers.tick(999)
  assert.deepEqual(observed.map(({ calls }) => calls.length), [0, 0, 0, 0])
  t.mock.timers.tick(1)
  assert.deepEqual(observed.map(({ calls }) => calls.length), [1, 1, 1, 1])
  for (const item of observed) item.calls[0].resolve({ status: 'running', completed_count: 100 })
  await settle()
  t.mock.timers.tick(60_000)
  assert.deepEqual(observed.map(({ calls }) => calls.length), [1, 1, 1, 1])
  assert.equal(disabledCalls, 0)
  assert.equal(client.getQueryState(inactiveKey).isInvalidated, true)
  assert.equal(client.getQueryState(inactiveKey).fetchStatus, 'idle')
})

test('慢请求不取消重发，末次终态在尾轮中继续合并且成功后不自激循环', async (t) => {
  const { client, refresh } = setup(t)
  const key = ['runs', 'extraction']
  const { calls, observer } = observe(t, client, key)
  void observer.refetch({ cancelRefetch: false })
  for (let index = 0; index < 80; index += 1) refresh.invalidate(['runs'])
  t.mock.timers.tick(5_000)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].signal.aborted, false)
  calls[0].resolve({ status: 'running', completed_count: 10 })
  await settle()
  t.mock.timers.tick(0)
  assert.equal(calls.length, 2)
  refresh.invalidate(['runs']) // 终态通知恰好落在尾轮请求中。
  t.mock.timers.tick(1_000)
  assert.equal(calls.length, 2)
  assert.equal(calls[1].signal.aborted, false)
  calls[1].resolve({ status: 'running', completed_count: 99 })
  await settle()
  t.mock.timers.tick(0)
  assert.equal(calls.length, 3)
  calls[2].resolve({ status: 'success', completed_count: 100 })
  await settle()
  t.mock.timers.tick(60_000)
  assert.equal(calls.length, 3)
  assert.deepEqual(client.getQueryData(key), { status: 'success', completed_count: 100 })
})

test('持续进度每秒至多一轮，手动刷新与恢复事件复用在途请求', async (t) => {
  const { client, refresh } = setup(t)
  const { calls, observer } = observe(t, client, ['runs'])
  for (let round = 0; round < 3; round += 1) {
    for (let index = 0; index < 10; index += 1) {
      refresh.invalidate(['runs'])
      t.mock.timers.tick(99)
      assert.equal(calls.length, round)
    }
    t.mock.timers.tick(10)
    assert.equal(calls.length, round + 1)
    calls[round].resolve({ status: 'running', completed_count: round })
    await settle()
  }
  refresh.invalidate(undefined, true)
  assert.equal(calls.length, 4)
  void observer.refetch({ cancelRefetch: false })
  refresh.invalidate(undefined, true) // 聚焦/网络恢复或 SSE 重连。
  assert.equal(calls.length, 4)
  assert.equal(calls[3].signal.aborted, false)
  calls[3].reject(new Error('temporary failure'))
  await settle()
  t.mock.timers.tick(1_000)
  assert.equal(calls.length, 5)
  calls[4].resolve({ status: 'success', completed_count: 100 })
  await settle()
  t.mock.timers.tick(60_000)
  assert.equal(calls.length, 5)
})

test('实际 api 取消链覆盖筛选/summary_version 换键和卸载，旧缓存不被尾轮复活', async (t) => {
  const { client, refresh } = setup(t)
  const requests = []
  t.mock.method(globalThis, 'fetch', (url, init) => new Promise((resolve, reject) => {
    requests.push({ url, signal: init.signal, resolve, reject })
    init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
  }))
  const oldKey = ['posts', 'r1', 1, { page: 1 }]
  const filteredKey = ['posts', 'r1', 1, { page: 2 }]
  const newKey = ['posts', 'r1', 2, { page: 2 }]
  client.setQueryData(oldKey, { items: [] })
  const options = (queryKey) => ({ queryKey, queryFn: ({ signal }) => api('/runs/r1/posts', { signal }, 20_000) })
  const observer = new QueryObserver(client, options(oldKey))
  const unsubscribe = observer.subscribe(() => {})
  t.after(unsubscribe)
  void observer.refetch({ cancelRefetch: false })
  refresh.invalidate(['posts', 'r1'])
  observer.setOptions(options(filteredKey))
  await settle()
  assert.equal(requests.length, 2)
  assert.equal(requests[0].signal.aborted, true)
  assert.equal(requests[1].signal.aborted, false)
  t.mock.timers.tick(1_000)
  assert.equal(requests.length, 2)
  refresh.invalidate(['posts', 'r1'])
  observer.setOptions(options(newKey)) // 仅 HTTP 汇总版本变化，同一筛选也会释放旧请求。
  await settle()
  assert.equal(requests.length, 3)
  assert.equal(requests[1].signal.aborted, true)
  assert.equal(requests[2].signal.aborted, false)
  refresh.invalidate(['posts', 'r1'])
  unsubscribe()
  await settle()
  assert.equal(requests[2].signal.aborted, true)
  t.mock.timers.tick(60_000)
  assert.equal(requests.length, 3)
  assert.equal(client.getQueryState(oldKey).isInvalidated, true)
  assert.equal(client.getQueryState(filteredKey).isInvalidated, true)
  assert.equal(client.getQueryState(newKey).isInvalidated, true)
})

test('事件桥清理后撤销待刷新定时器与完成订阅', async (t) => {
  const { client, refresh } = setup(t)
  const { calls, observer } = observe(t, client, ['dashboard'])
  refresh.invalidate(['dashboard'])
  void observer.refetch({ cancelRefetch: false })
  refresh.dispose()
  calls[0].resolve({ status: 'success' })
  await settle()
  refresh.invalidate(['dashboard'], true)
  t.mock.timers.tick(60_000)
  assert.equal(calls.length, 1)
})
