import { act, renderHook } from '@testing-library/react'
import { StrictMode, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  getCalc,
  getOutlets,
  getProducts,
  postChat,
  resetSession
} from '../api/client'
import {
  bootstrapSessionState,
  clearSessionState,
  loadSessionState,
  updateSessionMessages
} from '../state/storage'
import { useChat } from './useChat'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    postChat: vi.fn(),
    getCalc: vi.fn(),
    getProducts: vi.fn(),
    getOutlets: vi.fn(),
    resetSession: vi.fn()
  }
})

vi.mock('../state/storage', () => ({
  loadSessionState: vi.fn(),
  bootstrapSessionState: vi.fn(),
  updateSessionMessages: vi.fn(),
  clearSessionState: vi.fn()
}))

const makeState = (
  sessionId: string,
  overrides: Partial<{
    messages: { role: 'user' | 'assistant' | 'tool'; content: string }[]
    actionsByTurn: Record<string, unknown>
  }> = {}
) => ({
  sessionId,
  messages: overrides.messages ?? [],
  actionsByTurn: overrides.actionsByTurn ?? {},
  updatedAt: Date.now()
})

const StrictWrapper = ({ children }: { children: ReactNode }) => (
  <StrictMode>{children}</StrictMode>
)

describe('useChat', () => {
  beforeEach(() => {
    vi.mocked(loadSessionState).mockReturnValue(null)
    vi.mocked(bootstrapSessionState).mockReset()
    vi.mocked(bootstrapSessionState).mockReturnValue(makeState('session-test'))
    vi.mocked(updateSessionMessages).mockClear()
    vi.mocked(postChat).mockReset()
    vi.mocked(getCalc).mockReset()
    vi.mocked(getProducts).mockReset()
    vi.mocked(getOutlets).mockReset()
    vi.mocked(resetSession).mockReset()
    vi.mocked(clearSessionState).mockClear()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('sends chat messages through the /chat endpoint', async () => {
    vi.mocked(postChat).mockResolvedValueOnce({
      response: { role: 'assistant', content: 'Hello!' },
      actions: [{ type: 'decision', message: 'reply' }],
      memory: {}
    })

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.sendUserMessage('Hi there')
    })

    expect(postChat).toHaveBeenCalledWith({
      sessionId: 'session-test',
      messages: [{ role: 'user', content: 'Hi there' }]
    })
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.actionsByTurn['0']).toEqual([{ type: 'decision', message: 'reply' }])
  })

  it('handles /calc quick action without hitting /chat', async () => {
    vi.mocked(getCalc).mockResolvedValueOnce({ expression: '1+2', result: 3 })

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.sendUserMessage('/calc 1+2')
    })

    expect(getCalc).toHaveBeenCalledWith('1+2')
    expect(postChat).not.toHaveBeenCalled()
    expect(result.current.messages[result.current.messages.length - 1].content).toMatch(
      /calculator result/i
    )
  })

  it('resets the session when /reset is issued', async () => {
    vi.mocked(bootstrapSessionState)
      .mockImplementationOnce(() => makeState('session-initial'))
      .mockImplementationOnce(() => makeState('session-initial'))
      .mockImplementationOnce(() => makeState('session-new'))

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    vi.mocked(resetSession).mockResolvedValue()

    await act(async () => {
      await result.current.sendUserMessage('/reset')
    })

    expect(resetSession).toHaveBeenCalledWith('session-initial')
    expect(clearSessionState).toHaveBeenCalled()
    expect(result.current.sessionId).toBe('session-new')
    expect(result.current.messages).toEqual([])
  })

  it('resets session state via resetConversation()', async () => {
    vi.mocked(bootstrapSessionState)
      .mockImplementationOnce(() =>
        makeState('session-before-reset', {
          messages: [
            { role: 'user', content: 'Hello' },
            { role: 'assistant', content: 'Hi there' }
          ],
          actionsByTurn: { '0': [{ type: 'tool_result' }] }
        })
      )
      .mockImplementationOnce(() =>
        makeState('session-before-reset', {
          messages: [
            { role: 'user', content: 'Hello' },
            { role: 'assistant', content: 'Hi there' }
          ],
          actionsByTurn: { '0': [{ type: 'tool_result' }] }
        })
      )
      .mockImplementationOnce(() => makeState('session-after-reset'))

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.resetConversation()
    })

    expect(resetSession).toHaveBeenCalledWith('session-before-reset')
    expect(result.current.messages).toEqual([])
    expect(result.current.actionsByTurn).toEqual({})
    expect(result.current.sessionId).toBe('session-after-reset')
  })

  it('handles /products quick action and records tool actions', async () => {
    const productResponse = {
      query: 'bottle',
      summary: 'Steel bottle keeps drinks cold.',
      topK: [
        {
          title: 'Steel Bottle',
          score: 0.98
        }
      ]
    }
    vi.mocked(getProducts).mockResolvedValueOnce(productResponse as never)

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.sendUserMessage('/products bottle')
    })

    expect(getProducts).toHaveBeenCalledWith('bottle', 3)
    const lastMessage = result.current.messages.at(-1)
    expect(lastMessage?.content).toContain('Steel bottle keeps drinks cold')
    expect(result.current.actionsByTurn['0']).toEqual([
      expect.objectContaining({
        type: 'tool_result',
        tool: 'products',
        status: 'success',
        data: productResponse
      })
    ])
  })

  it('handles /outlets quick action and formats response', async () => {
    const outletsResponse = {
      query: 'SS 2 outlet hours',
      sql: 'SELECT * FROM outlets',
      params: {},
      rows: [
        {
          name: 'ZUS Coffee SS 2',
          city: 'Petaling Jaya',
          state: 'Selangor',
          address: '123 Jalan SS 2',
          open_time: '09:00',
          close_time: '21:00'
        }
      ]
    }
    vi.mocked(getOutlets).mockResolvedValueOnce(outletsResponse as never)

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.sendUserMessage('/outlets SS 2 outlet hours')
    })

    expect(getOutlets).toHaveBeenCalledWith('SS 2 outlet hours')
    const lastMessage = result.current.messages.at(-1)
    expect(lastMessage?.content).toContain('ZUS Coffee SS 2')
    expect(result.current.actionsByTurn['0']).toEqual([
      expect.objectContaining({
        type: 'tool_result',
        tool: 'outlets',
        status: 'success',
        data: outletsResponse
      })
    ])
  })

  it('surfaces an assistant error message when quick action fails', async () => {
    vi.mocked(getProducts).mockRejectedValueOnce(new Error('network failure'))

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.sendUserMessage('/products latte')
    })

    const lastMessage = result.current.messages.at(-1)
    expect(lastMessage?.role).toBe('assistant')
    expect(lastMessage?.content).toMatch(/network connection/i)
    expect(result.current.error).toMatch(/network connection/i)
  })

  it('resets the sending flag after a timeout error', async () => {
    vi.mocked(postChat).mockRejectedValueOnce(new ApiError('Timed out', 408))

    const { result } = renderHook(() => useChat(), { wrapper: StrictWrapper })

    await act(async () => {
      await result.current.sendUserMessage('Hello?')
    })

    expect(result.current.isSending).toBe(false)
    expect(result.current.error).toMatch(/timed out/i)
  })
})

