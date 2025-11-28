import type { ChatMessage, ToolAction } from '../api/types'

export type TurnActionMap = Record<string, ToolAction[]>

export interface PersistedChatState {
  sessionId: string
  messages: ChatMessage[]
  actionsByTurn: TurnActionMap
  updatedAt: number
}

const STORAGE_KEY = 'mh.chat.state'

const noopState: PersistedChatState = {
  sessionId: '',
  messages: [],
  actionsByTurn: {},
  updatedAt: 0
}

function getStorage(): Storage | null {
  if (typeof window === 'undefined' || !window.localStorage) {
    return null
  }
  return window.localStorage
}

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `session-${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`
}

function normalizeState(state: unknown): PersistedChatState | null {
  if (!state || typeof state !== 'object') {
    return null
  }

  const parsed = state as Partial<PersistedChatState>
  if (!parsed.sessionId) {
    return null
  }

  return {
    sessionId: parsed.sessionId,
    messages: Array.isArray(parsed.messages) ? parsed.messages : [],
    actionsByTurn: normalizeActions(parsed.actionsByTurn),
    updatedAt: typeof parsed.updatedAt === 'number' ? parsed.updatedAt : Date.now()
  }
}

function normalizeActions(map: unknown): TurnActionMap {
  if (!map || typeof map !== 'object') {
    return {}
  }

  const entries = Object.entries(map as Record<string, unknown>)
  const normalized: TurnActionMap = {}
  for (const [key, value] of entries) {
    if (!Array.isArray(value)) {
      continue
    }
    const actions = value.filter((item): item is ToolAction => {
      return typeof item === 'object' && item !== null && 'type' in (item as Record<string, unknown>)
    })
    if (actions.length > 0) {
      normalized[key] = actions
    }
  }
  return normalized
}

export function loadSessionState(): PersistedChatState | null {
  const storage = getStorage()
  if (!storage) {
    return null
  }

  try {
    const raw = storage.getItem(STORAGE_KEY)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw)
    return normalizeState(parsed)
  } catch {
    storage.removeItem(STORAGE_KEY)
    return null
  }
}

export function saveSessionState(state: PersistedChatState): PersistedChatState {
  const storage = getStorage()
  if (!storage) {
    return noopState
  }

  const payload: PersistedChatState = {
    sessionId: state.sessionId,
    messages: state.messages,
    actionsByTurn: state.actionsByTurn,
    updatedAt: Date.now()
  }

  storage.setItem(STORAGE_KEY, JSON.stringify(payload))
  return payload
}

export function clearSessionState(): void {
  const storage = getStorage()
  storage?.removeItem(STORAGE_KEY)
}

export function bootstrapSessionState(): PersistedChatState {
  const existing = loadSessionState()
  if (existing) {
    return existing
  }

  const initial: PersistedChatState = {
    sessionId: createSessionId(),
    messages: [],
    actionsByTurn: {},
    updatedAt: Date.now()
  }
  saveSessionState(initial)
  return initial
}

export function updateSessionMessages(
  messages: ChatMessage[],
  actionsByTurn: TurnActionMap,
  sessionId?: string
): PersistedChatState {
  const base = loadSessionState()
  const resolvedSessionId = sessionId ?? base?.sessionId ?? createSessionId()
  const next: PersistedChatState = {
    sessionId: resolvedSessionId,
    messages,
    actionsByTurn,
    updatedAt: Date.now()
  }
  return saveSessionState(next)
}

export function getStorageKey(): string {
  return STORAGE_KEY
}

