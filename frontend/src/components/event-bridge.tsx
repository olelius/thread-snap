import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

export function EventBridge() {
  const client = useQueryClient()
  useEffect(() => {
    const source = new EventSource('/api/v1/events')
    const setConnection = (connected: boolean) => {
      document.documentElement.dataset.backendConnected = String(connected)
      window.dispatchEvent(new CustomEvent('threadsnap:connection', { detail: connected }))
    }
    source.onopen = () => setConnection(true)
    source.onerror = () => setConnection(false)
    const refreshRuns = () => client.invalidateQueries({ queryKey: ['runs'] })
    source.addEventListener('run.changed', (event) => {
      refreshRuns()
      const payload = JSON.parse((event as MessageEvent).data) as { resource_id?: string }
      if (payload.resource_id) {
        client.invalidateQueries({ queryKey: ['run', payload.resource_id] })
        client.invalidateQueries({ queryKey: ['posts', payload.resource_id] })
      }
    })
    source.addEventListener('run.deleted', refreshRuns)
    source.addEventListener('platform.changed', () => client.invalidateQueries({ queryKey: ['platforms'] }))
    source.addEventListener('circles.changed', () => client.invalidateQueries({ queryKey: ['vehicles'] }))
    source.addEventListener('validation.changed', () => client.invalidateQueries({ queryKey: ['vehicles'] }))
    source.addEventListener('session.changed', (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { resource_id?: string }
      if (payload.resource_id) client.invalidateQueries({ queryKey: ['session', payload.resource_id] })
      client.invalidateQueries({ queryKey: ['runs'] })
    })
    source.addEventListener('extraction-plan.changed', () => client.invalidateQueries({ queryKey: ['extraction-plan'] }))
    const refreshAll = () => client.invalidateQueries()
    window.addEventListener('online', refreshAll)
    window.addEventListener('focus', refreshAll)
    return () => {
      setConnection(false)
      source.close()
      window.removeEventListener('online', refreshAll)
      window.removeEventListener('focus', refreshAll)
    }
  }, [client])
  return null
}
