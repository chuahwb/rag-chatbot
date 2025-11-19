import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  getCalc,
  postChat,
  resetSession
} from './client'
import type { ChatRequest, ChatResponse } from './types'

type FetchMock = ReturnType<typeof vi.fn>

const jsonResponse = (body: unknown, init?: ResponseInit) =>
  new Response(JSON.stringify(body), {
    status: init?.status ?? 200,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {})
    }
  })

describe('api client', () => {
  let fetchMock: FetchMock

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('posts chat payload and returns typed response', async () => {
    const payload: ChatRequest = {
      sessionId: 'session-1',
      messages: [{ role: 'user', content: 'hello' }]
    }
    const responseBody: ChatResponse = {
      response: { role: 'assistant', content: 'hi there' },
      actions: [],
      memory: { sessionId: 'session-1' }
    }
    fetchMock.mockResolvedValueOnce(jsonResponse(responseBody))

    const result = await postChat(payload)

    expect(result).toEqual(responseBody)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/chat',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(payload)
      })
    )
  })

  it('surface ApiError when server returns non-2xx response', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'Invalid expression' }, { status: 400 })
    )

    await expect(getCalc('not valid')).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/calc?query=not+valid',
      expect.objectContaining({})
    )
  })

  it('resets a session via DELETE /chat/session/:id', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(null, {
        status: 204,
        headers: { 'Content-Type': 'application/json' }
      })
    )

    await expect(resetSession('abc-123')).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/chat/session/abc-123',
      expect.objectContaining({ method: 'DELETE' })
    )
  })
})

