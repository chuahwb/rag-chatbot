import { useEffect, useMemo, useRef, useState } from 'react'

import { getApiBaseUrl } from '../api/client'

export interface PlannerEvent {
  id: string
  type: string
  node?: string
  status?: string
  message?: string
  timestamp?: string
  data?: Record<string, unknown> | null
}

interface UseEventsResult {
  events: PlannerEvent[]
  isConnected: boolean
  lastError: string | null
}

const MAX_EVENTS = 150
const EVENT_TYPES = [
  'ready',
  'heartbeat',
  'message',
  'node_start',
  'node_end',
  'llm_call',
  'tool_call',
  'tool_result',
  'decision',
  'error',
  'planner_state'
]

const SSE_ENABLED =
  (import.meta.env.VITE_ENABLE_SSE === undefined ||
    import.meta.env.VITE_ENABLE_SSE === 'true')

const normalizeEvent = (event: MessageEvent, payload: Record<string, unknown>): PlannerEvent => {
  const payloadType =
    (typeof payload.type === 'string' && payload.type.length > 0
      ? payload.type
      : undefined) ?? event.type ?? 'message'
  const timestamp =
    typeof payload.timestamp === 'string' && payload.timestamp.length > 0
      ? payload.timestamp
      : new Date().toISOString()
  const status =
    typeof payload.status === 'string'
      ? payload.status
      : typeof payload.data === 'object' && payload.data !== null
        ? (() => {
            const nested = payload.data as Record<string, unknown>
            return typeof nested.status === 'string' ? nested.status : undefined
          })()
        : undefined
  const message =
    typeof payload.message === 'string'
      ? payload.message
      : typeof payload.data === 'object' && payload.data !== null
        ? (() => {
            const nested = payload.data as Record<string, unknown>
            return typeof nested.message === 'string' ? nested.message : undefined
          })()
        : undefined

  return {
    id:
      (typeof payload.id === 'string' && payload.id.length > 0
        ? payload.id
        : `${payloadType}-${timestamp}-${Math.random().toString(16).slice(2)}`),
    type: payloadType,
    node: typeof payload.node === 'string' ? payload.node : undefined,
    status,
    message,
    timestamp,
    data: payload
  }
}

export function useEvents(sessionId: string | null): UseEventsResult {
  const [events, setEvents] = useState<PlannerEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [lastError, setLastError] = useState<string | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const eventsUrl = useMemo(() => {
    if (!sessionId) {
      return null
    }
    const base = getApiBaseUrl().replace(/\/$/, '')
    const search = new URLSearchParams({ sessionId })
    return `${base}/events?${search.toString()}`
  }, [sessionId])

  useEffect(() => {
    // Reset events whenever the logical chat session changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEvents([])
  }, [sessionId])

  useEffect(() => {
    if (!SSE_ENABLED || !eventsUrl) {
      // When SSE is disabled or there is no events URL, clear local subscription state.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEvents([])
      setIsConnected(false)
      return
    }

    const source = new EventSource(eventsUrl)
    eventSourceRef.current = source
    setLastError(null)
    const handleEvent = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>
        const normalized = normalizeEvent(event, payload)
        if (normalized.type === 'heartbeat') {
          setIsConnected(true)
          setLastError(null)
          return
        }
        setEvents((prev) => {
          const next = [...prev, normalized]
          return next.slice(-MAX_EVENTS)
        })
      } catch (err) {
        console.error('Failed to parse planner event payload', err)
      }
    }

    EVENT_TYPES.forEach((type) => {
      source.addEventListener(type, handleEvent as EventListener)
    })

    source.onopen = () => {
      setIsConnected(true)
    }

    source.onerror = () => {
      setIsConnected(false)
      setLastError('Lost connection to planner events.')
    }

    return () => {
      EVENT_TYPES.forEach((type) => {
        source.removeEventListener(type, handleEvent as EventListener)
      })
      source.close()
      eventSourceRef.current = null
    }
  }, [eventsUrl])

  return { events, isConnected, lastError }
}

