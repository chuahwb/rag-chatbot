import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ToolAction } from '../api/types'
import { ChatWindow } from './ChatWindow'

vi.mock('../api/client', () => {
  const postChat = vi.fn()
  const resetSession = vi.fn().mockResolvedValue(undefined)
  return {
    postChat,
    resetSession,
    getCalc: vi.fn(),
    getProducts: vi.fn(),
    getOutlets: vi.fn(),
    getApiBaseUrl: () => 'http://localhost:8000'
  }
})

const { postChat } = await import('../api/client')
const SESSION_ID = '00000000-0000-4000-8000-000000000000'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

const createDeferred = <T,>(): Deferred<T> => {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

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

  simulateReady(): void {
    this.readyState = this.OPEN
    this.onopen?.(new Event('open'))
    this.emit('ready', { status: 'ready', sessionId: SESSION_ID })
  }

  close(): void {
    this.readyState = this.CLOSED
  }
}

const originalEventSource = globalThis.EventSource

describe('ChatWindow (integration)', () => {
  let randomUuidSpy: ReturnType<typeof vi.spyOn> | undefined

  beforeAll(() => {
    ;(globalThis as typeof globalThis & { EventSource: typeof EventSource }).EventSource =
      MockEventSource as unknown as typeof EventSource
  })

  beforeEach(() => {
    localStorage.clear()
    randomUuidSpy = vi.spyOn(crypto, 'randomUUID').mockReturnValue(SESSION_ID)
    vi.mocked(postChat).mockReset()
    MockEventSource.instances = []
  })

  afterEach(() => {
    randomUuidSpy?.mockRestore()
    vi.clearAllMocks()
  })

  afterAll(() => {
    ;(globalThis as typeof globalThis & { EventSource: typeof EventSource }).EventSource =
      originalEventSource
  })

  it('renders assistant replies, planner events, and tool activity after a chat turn', async () => {
    const actions: ToolAction[] = [
      {
        type: 'tool_call',
        tool: 'products',
        status: 'success',
        message: 'Queried drinkware'
      }
    ]
    vi.mocked(postChat).mockResolvedValueOnce({
      response: { role: 'assistant', content: 'Here are some drinkware options.' },
      actions,
      memory: { sessionId: SESSION_ID }
    })

    render(<ChatWindow />)

    const source = MockEventSource.instances.at(-1)
    await act(async () => {
      source?.simulateReady()
      source?.emit('node_start', {
        type: 'node_start',
        node: 'classify_intent',
        status: 'success',
        message: 'Determining intent'
      })
    })

    const user = userEvent.setup()
    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'Tell me about drinkware')
    await user.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(screen.getByText(/drinkware options/i)).toBeInTheDocument()
    })

    expect(postChat).toHaveBeenCalledWith({
      sessionId: SESSION_ID,
      messages: [{ role: 'user', content: 'Tell me about drinkware' }]
    })

    await waitFor(() => {
      expect(screen.getByText(/classify intent/i)).toBeInTheDocument()
    })

    const toolCard = screen.getByText(/Tool Activity/i).closest('.chat-sidebar__card')
    expect(toolCard).not.toBeNull()
    const cardQueries = within(toolCard as HTMLElement)
    await waitFor(() => {
      expect(cardQueries.getByText(/Product Search/i)).toBeInTheDocument()
    })
  })

  it('disables composer controls while awaiting a response', async () => {
    const deferred = createDeferred<{
      response: { role: 'assistant'; content: string }
      actions: ToolAction[]
      memory: Record<string, unknown>
    }>()
    vi.mocked(postChat).mockReturnValueOnce(deferred.promise)

    render(<ChatWindow />)

    const source = MockEventSource.instances.at(-1)
    await act(async () => {
      source?.simulateReady()
    })

    const user = userEvent.setup()
    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'First turn message')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(postChat).toHaveBeenCalledTimes(1)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sending/i })).toBeDisabled()
    })
    expect(textarea).toBeDisabled()

    await act(async () => {
      deferred.resolve({
        response: { role: 'assistant', content: 'Done processing turn.' },
        actions: [],
        memory: { sessionId: SESSION_ID }
      })
    })

    await waitFor(() => {
      expect(screen.getByText(/Done processing turn/i)).toBeInTheDocument()
    })

    expect(textarea).not.toBeDisabled()
    await user.type(textarea, 'Queued follow up')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /send/i })).not.toBeDisabled()
    })
  })

  it('shows planner-only small talk decisions as success', async () => {
    vi.mocked(postChat).mockResolvedValueOnce({
      response: { role: 'assistant', content: 'Just a friendly reminder to ask about outlets or drinkware.' },
      actions: [
        {
          type: 'decision',
          tool: null,
          status: 'success',
          message: 'Responded with small-talk guidance.'
        }
      ],
      memory: { sessionId: SESSION_ID }
    })

    render(<ChatWindow />)

    const source = MockEventSource.instances.at(-1)
    await act(async () => {
      source?.simulateReady()
    })

    const user = userEvent.setup()
    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'hello?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(screen.getByText(/friendly reminder/i)).toBeInTheDocument()
    })

    const assistantLabels = screen.getAllByText('Assistant')
    expect(assistantLabels).toHaveLength(1)

    const toolCard = screen.getByText(/Tool Activity/i).closest('.chat-sidebar__card')
    expect(toolCard).not.toBeNull()
    const cardQueries = within(toolCard as HTMLElement)
    expect(cardQueries.getByText(/Planner/i)).toBeInTheDocument()
    expect(cardQueries.getByText(/success/i)).toBeInTheDocument()
  })
})

