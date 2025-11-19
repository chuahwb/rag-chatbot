import { render, screen } from '@testing-library/react'
import { beforeAll, afterAll, describe, expect, it, vi } from 'vitest'

vi.mock('./hooks/useChat', () => ({
  useChat: () => ({
    sessionId: 'session-test',
    messages: [{ role: 'assistant', content: 'Welcome!' }],
    actionsByTurn: {},
    isSending: false,
    error: null,
    sendUserMessage: vi.fn(),
    resetConversation: vi.fn(),
    clearError: vi.fn()
  })
}))

vi.mock('./hooks/useEvents', () => ({
  useEvents: () => ({
    events: [],
    isConnected: true,
    lastError: null
  })
}))

import App from './App'

const originalEventSource = globalThis.EventSource

class StubEventSource implements EventSource {
  readonly url: string
  readonly withCredentials = false
  readyState = 1
  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSED = 2
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null
  constructor(url: string) {
    this.url = url
  }
  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean {
    return true
  }
  close(): void {
    this.readyState = this.CLOSED
  }
}

beforeAll(() => {
  ;(globalThis as typeof globalThis & { EventSource: typeof EventSource }).EventSource =
    StubEventSource as unknown as typeof EventSource
})

afterAll(() => {
  ;(globalThis as typeof globalThis & { EventSource: typeof EventSource }).EventSource =
    originalEventSource
})

describe('App', () => {
  it('renders the chat shell heading', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /zus assistant/i })).toBeInTheDocument()
  })
})

