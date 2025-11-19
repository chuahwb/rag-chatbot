import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PersistedChatState } from './storage'
import {
  bootstrapSessionState,
  clearSessionState,
  getStorageKey,
  loadSessionState,
  saveSessionState,
  updateSessionMessages
} from './storage'

const STORAGE_KEY = getStorageKey()

describe('storage helpers', () => {
  let randomUuidSpy: ReturnType<typeof vi.spyOn> | undefined

  beforeEach(() => {
    localStorage.clear()
    if (typeof crypto.randomUUID === 'function') {
      randomUuidSpy = vi
        .spyOn(crypto, 'randomUUID')
        .mockReturnValue('00000000-0000-4000-8000-000000000000')
    }
  })

  afterEach(() => {
    randomUuidSpy?.mockRestore()
    vi.restoreAllMocks()
  })

  it('bootstraps a new session when none exists', () => {
    const state = bootstrapSessionState()

    expect(state.sessionId).toBe('00000000-0000-4000-8000-000000000000')
    expect(state.messages).toEqual([])
    const persisted = loadSessionState()
    expect(persisted?.sessionId).toBe('00000000-0000-4000-8000-000000000000')
  })

  it('persists and loads session state', () => {
    const payload: PersistedChatState = {
      sessionId: 'existing-session',
      messages: [{ role: 'user', content: 'hello' }],
      actionsByTurn: { '0': [] },
      updatedAt: 0
    }

    const saved = saveSessionState(payload)
    expect(saved.sessionId).toBe('existing-session')

    const loaded = loadSessionState()
    expect(loaded).toMatchObject({
      sessionId: 'existing-session',
      messages: [{ role: 'user', content: 'hello' }]
    })
  })

  it('handles corrupted storage by clearing the entry', () => {
    localStorage.setItem(STORAGE_KEY, '{bad-json')
    expect(loadSessionState()).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('updates session messages with a provided session id', () => {
    const next = updateSessionMessages(
      [
        { role: 'user', content: 'hi' },
        { role: 'assistant', content: 'hello' }
      ],
      { '0': [] },
      'session-x'
    )

    expect(next.sessionId).toBe('session-x')
    const persisted = loadSessionState()
    expect(persisted?.messages).toHaveLength(2)
  })

  it('clears the session state', () => {
    saveSessionState({
      sessionId: 'to-clear',
      messages: [],
      actionsByTurn: {},
      updatedAt: 0
    })

    clearSessionState()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
})

