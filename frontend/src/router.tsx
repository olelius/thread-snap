import { createRootRoute, createRoute, createRouter, lazyRouteComponent, redirect } from '@tanstack/react-router'
import { AppShell } from '@/components/app-shell'

const rootRoute = createRootRoute({ component: AppShell })
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', beforeLoad: () => { throw redirect({ to: '/runs', search: emptyRunsSearch }) } })
const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/runs',
  component: lazyRouteComponent(() => import('@/features/runs/runs-page'), 'RunsPage'),
  validateSearch: (search: Record<string, unknown>) => ({
    page: optionalPositiveInteger(search.page),
    pageSize: oneOfNumber(search.pageSize, [20, 50, 100] as const),
    number: text(search.number),
    status: oneOf(search.status, ['queued', 'running', 'waiting_for_auth', 'success', 'partial_success', 'failed'] as const),
    trigger: oneOf(search.trigger, ['manual', 'scheduled'] as const),
    listOrder: oneOf(search.listOrder, ['latest_reply', 'latest_publish'] as const),
    from: text(search.from),
    to: text(search.to),
  }),
})
const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/runs/$runId',
  component: lazyRouteComponent(() => import('@/features/runs/run-detail-page'), 'RunDetailPage'),
  validateSearch: (search: Record<string, unknown>) => ({
    view: oneOf(search.view, ['links', 'screenshots'] as const),
    page: optionalPositiveInteger(search.page),
    pageSize: oneOfNumber(search.pageSize, [20, 50, 100] as const),
    title: text(search.title),
    sources: text(search.sources),
    visibility: oneOf(search.visibility, ['visible', 'hidden', 'unknown'] as const),
    sentiment: oneOf(search.sentiment, ['negative', 'non_negative', 'unrelated'] as const),
    analysisStatus: oneOf(search.analysisStatus, ['analysis_queued', 'analysis_running', 'analysis_completed', 'analysis_partial', 'analysis_failed', 'analysis_paused', 'analysis_disabled'] as const),
    sort: oneOf(search.sort, ['source', 'published_at', 'reply_count', 'like_count'] as const),
    direction: oneOf(search.direction, ['asc', 'desc'] as const),
    post: text(search.post),
  }),
})
const configRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/config',
  component: lazyRouteComponent(() => import('@/features/config/config-page'), 'ConfigPage'),
  validateSearch: (search: Record<string, unknown>) => ({ tab: oneOf(search.tab, ['plan', 'rules', 'schedule', 'platforms', 'circles', 'history', 'templates', 'sentiment'] as const) ?? 'rules' }),
})

const routeTree = rootRoute.addChildren([indexRoute, runsRoute, runDetailRoute, configRoute])
export const router = createRouter({ routeTree, defaultPreload: 'intent', scrollRestoration: true })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}

function text(value: unknown) { return typeof value === 'string' && value ? value : undefined }
function optionalPositiveInteger(value: unknown) { const parsed = Number(value); return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined }
function oneOf<const T extends readonly string[]>(value: unknown, allowed: T): T[number] | undefined { return typeof value === 'string' && allowed.includes(value as T[number]) ? value as T[number] : undefined }
function oneOfNumber<const T extends readonly number[]>(value: unknown, allowed: T): T[number] | undefined { const parsed = Number(value); return allowed.includes(parsed as T[number]) ? parsed as T[number] : undefined }

const emptyRunsSearch = { page: undefined, pageSize: undefined, number: undefined, status: undefined, trigger: undefined, listOrder: undefined, from: undefined, to: undefined }
