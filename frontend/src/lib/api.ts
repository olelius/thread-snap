import type { ApiErrorPayload } from './types'

export class ApiError extends Error {
  constructor(
    public status: number,
    public payload: ApiErrorPayload
  ) {
    super(payload.message)
  }
}

export function queryString(values: Record<string, unknown>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) value.forEach((item) => params.append(key, String(item)))
    else params.set(key, String(value))
  })
  const text = params.toString()
  return text ? `?${text}` : ''
}

export async function api<T>(path: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  if (init?.signal?.aborted) controller.abort()
  else init?.signal?.addEventListener('abort', abort, { once: true })
  const timeout = timeoutMs === undefined ? undefined : globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...init?.headers,
      },
    })
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({
        code: 'HTTP_ERROR',
        message: `请求失败（${response.status}）`,
      }))) as ApiErrorPayload
      throw new ApiError(response.status, payload)
    }
    if (response.status === 204) return undefined as T
    return await response.json() as T
  } catch (error) {
    if (timedOut) {
      throw new ApiError(408, {
        code: 'REQUEST_TIMEOUT',
        message: `请求超过 ${Math.ceil((timeoutMs ?? 0) / 1000)} 秒，请重试。`,
      })
    }
    throw error
  } finally {
    if (timeout !== undefined) globalThis.clearTimeout(timeout)
    init?.signal?.removeEventListener('abort', abort)
  }
}

export function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.payload.details?.length) {
    const details = error.payload.details.map((item) => {
      const location = typeof item.row === 'number' ? `第 ${item.row} 行` : ''
      const reason = typeof item.reason === 'string' ? item.reason : ''
      return [location, reason].filter(Boolean).join('：')
    }).filter(Boolean)
    if (details.length) return `${error.message} ${details.join('；')}`
  }
  return error instanceof Error ? error.message : '操作未完成，请稍后重试。'
}

export function formatDate(value?: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}

const platformNames: Record<string, string> = {
  dongchedi: '懂车帝',
  yiche: '易车',
  autohome: '汽车之家',
}

export function platformName(code: string) {
  return platformNames[code] ?? code
}

export function shanghaiDayBoundary(value: string, end = false) {
  return new Date(`${value}T${end ? '23:59:59.999' : '00:00:00'}+08:00`).toISOString()
}
