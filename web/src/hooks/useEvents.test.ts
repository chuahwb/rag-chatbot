import { act, renderHook, waitFor } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { useEvents } from './useEvents'

class MockEventSource extends EventTarget {
  static instances: MockEventSource[] = []
  url: string
  onopen: ((this: MockEventSource, ev: Event) => unknown) | null = null
  onmessage: ((this: MockEventSource, ev: MessageEvent) => unknown) | null = null
  onerror: ((this: MockEventSource, ev: Event) => unknown) | null = null
  withCredentials = false
  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSED = 2
  readyState = this.CONNECTING

  constructor(url: string) {
    super()
    this.url = url
    MockEventSource.instances.push(this)
  }

  emit(type: string, data: unknown): void {
    const event = new MessageEvent(type, { data: JSON.stringify(data) })
    this.dispatchEvent(event)
    if (type === 'message') {
      this.onmessage?.(event)
    }
  }

  simulateOpen(): void {
    this.readyState = this.OPEN
    this.onopen?.(new Event('open'))
  }

  simulateError(): void {
    this.readyState = this.CLOSED
    this.onerror?.(new Event('error'))
  }

  close(): void {
    this.readyState = this.CLOSED
  }
}

const originalEventSource = globalThis.EventSource

describe('useEvents', () => {
  beforeAll(() => {
    ;(globalThis as typeof globalThis & { EventSource: typeof EventSource }).EventSource =
      MockEventSource as unknown as typeof EventSource
  })

  afterEach(() => {
    MockEventSource.instances = []
    vi.clearAllMocks()
  })

  afterAll(() => {
    ;(globalThis as typeof globalThis & { EventSource: typeof EventSource }).EventSource = originalEventSource
  })

  it('connects to the SSE endpoint and tracks events', async () => {
    const { result } = renderHook(({ sessionId }) => useEvents(sessionId), {
      initialProps: { sessionId: 'session-123' }
    })

    const source = MockEventSource.instances.at(-1)!

    act(() => {
      source.simulateOpen()
      source.emit('ready', { status: 'ready', sessionId: 'session-123' })
      source.emit('node_start', { type: 'node_start', node: 'classify_intent' })
    })

    await waitFor(() => expect(result.current.events.length).toBe(2))
    expect(result.current.isConnected).toBe(true)
    expect(source.url).toContain('sessionId=session-123')
  })

  it('clears events and reports errors when the stream fails', async () => {
    const { result, rerender } = renderHook(({ sessionId }) => useEvents(sessionId), {
      initialProps: { sessionId: 'first' }
    })

    const firstSource = MockEventSource.instances.at(-1)!

    act(() => {
      firstSource.emit('node_start', { type: 'node_start', node: 'classify_intent' })
      firstSource.simulateError()
    })

    await waitFor(() => expect(result.current.lastError).toMatch(/lost connection/i))

    rerender({ sessionId: 'second' })
    expect(result.current.events).toEqual([])
  })

  it('keeps the connection healthy when heartbeat events arrive', async () => {
    const { result } = renderHook(({ sessionId }) => useEvents(sessionId), {
      initialProps: { sessionId: 'pulse' }
    })

    const source = MockEventSource.instances.at(-1)!

    act(() => {
      source.simulateError()
    })

    await waitFor(() => expect(result.current.lastError).toMatch(/lost connection/i))

    act(() => {
      source.simulateOpen()
      source.emit('heartbeat', { type: 'heartbeat', status: 'idle' })
    })

    await waitFor(() => expect(result.current.lastError).toBeNull())
    expect(result.current.isConnected).toBe(true)
  })
})

