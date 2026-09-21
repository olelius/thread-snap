import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { createEventRefresh } from '@/lib/event-refresh'

export function EventBridge() {
  const client = useQueryClient()
  useEffect(() => {
    const refresh = createEventRefresh(client)
    const source = new EventSource('/api/v1/events')
    const setConnection = (connected: boolean) => {
      document.documentElement.dataset.backendConnected = String(connected)
      window.dispatchEvent(new CustomEvent('threadsnap:connection', { detail: connected }))
    }
    source.onopen = () => { setConnection(true); refresh.invalidate(undefined, true) }
    source.onerror = () => setConnection(false)
    source.addEventListener('run.changed', (event) => {
      refresh.invalidate(['runs'])
      refresh.invalidate(['dashboard'])
      const payload = JSON.parse((event as MessageEvent).data) as { resource_id?: string }
      if (payload.resource_id) {
        refresh.invalidate(['run', payload.resource_id])
        refresh.invalidate(['posts', payload.resource_id])
      }
    })
    source.addEventListener('run.deleted', () => { refresh.invalidate(['runs'], true); refresh.invalidate(['dashboard'], true) })
    source.addEventListener('platform.changed', () => refresh.invalidate(['platforms'], true))
    source.addEventListener('circles.changed', () => refresh.invalidate(['vehicles'], true))
    source.addEventListener('validation.changed', () => refresh.invalidate(['vehicles'], true))
    source.addEventListener('session.changed', (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { resource_id?: string }
      if (payload.resource_id) refresh.invalidate(['session', payload.resource_id], true)
      refresh.invalidate(['runs'], true)
    })
    source.addEventListener('extraction-plan.changed', () => refresh.invalidate(['extraction-plan'], true))
    source.addEventListener('sentiment.config.changed', () => { refresh.invalidate(['sentiment-config'], true); refresh.invalidate(['sentiment-accounts'], true) })
    source.addEventListener('sentiment.changed', () => {
      refresh.invalidate(['posts'], true)
      refresh.invalidate(['post'], true)
    })
    source.addEventListener('reputation.run.changed', (event) => {
      refresh.invalidate(['reputation-runs'], true)
      refresh.invalidate(['dashboard'], true)
      const payload = JSON.parse((event as MessageEvent).data) as { resource_id?: string }
      if (payload.resource_id) {
        refresh.invalidate(['reputation-run', payload.resource_id], true)
      }
    })
    source.addEventListener('reputation.scope.changed', () => {
      refresh.invalidate(['reputation-scope'], true)
    })
    const refreshAll = () => refresh.invalidate(undefined, true)
    window.addEventListener('online', refreshAll)
    window.addEventListener('focus', refreshAll)
    return () => {
      setConnection(false)
      refresh.dispose()
      source.close()
      window.removeEventListener('online', refreshAll)
      window.removeEventListener('focus', refreshAll)
    }
  }, [client])
  return null
}
