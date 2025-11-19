import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  ApiError,
  getCalc,
  getOutlets,
  getProducts,
  postChat,
  resetSession
} from '../api/client'
import type { ChatMessage, ToolAction } from '../api/types'
import {
  bootstrapSessionState,
  clearSessionState,
  loadSessionState,
  updateSessionMessages
} from '../state/storage'

type QuickActionType = 'calc' | 'products' | 'outlets' | 'reset'

interface QuickAction {
  type: QuickActionType
  argument?: string
}

interface UseChatResult {
  sessionId: string
  messages: ChatMessage[]
  actionsByTurn: Record<string, ToolAction[]>
  isSending: boolean
  error: string | null
  sendUserMessage: (content: string) => Promise<void>
  resetConversation: () => Promise<void>
  clearError: () => void
}

const SUPPORTED_COMMANDS: QuickActionType[] = ['calc', 'products', 'outlets', 'reset']
type ToolQuickAction = Exclude<QuickActionType, 'reset'>

const QUICK_ACTION_FALLBACK: Record<ToolQuickAction, string> = {
  calc: 'The calculator service is unavailable. Try again in a moment.',
  products: 'Product search is unavailable right now. Please retry shortly.',
  outlets: 'Outlet lookup is unavailable. Please try again in a bit.'
}

const CHAT_FAILURE_MESSAGE =
  'The assistant hit an issue while replying. Please try again in a few seconds.'
const CHAT_SERVER_UNAVAILABLE =
  'The assistant services are temporarily unavailable. Please try again shortly.'
const NETWORK_ERROR_MESSAGE =
  'Network connection lost. Check your internet connection and try again.'

const countUserTurns = (messages: ChatMessage[]): number =>
  messages.reduce((count, message) => (message.role === 'user' ? count + 1 : count), 0)

const deriveTurnKey = (messages: ChatMessage[]): string | null => {
  const userTurns = countUserTurns(messages)
  if (userTurns === 0) {
    return null
  }
  return String(userTurns - 1)
}

const formatCalcResponse = (expression: string, result: number): string =>
  `Calculator result: ${expression} = ${result}`

const formatProductsResponse = (query: string, summary?: string | null, titles?: string[]): string => {
  if (summary && summary.trim().length > 0) {
    return summary.trim()
  }
  if (!titles || titles.length === 0) {
    return `No product matches were found for "${query}".`
  }
  const list = titles.slice(0, 3).map((title) => `• ${title}`)
  return [`Top products for "${query}":`, ...list].join('\n')
}

const formatOutletsResponse = (query: string, rows: Array<Record<string, unknown>>): string => {
  if (!rows.length) {
    return `I couldn't find an outlet for "${query}".`
  }
  const first = rows[0]
  const name = typeof first.name === 'string' ? first.name : 'Outlet'
  const city = typeof first.city === 'string' ? first.city : undefined
  const state = typeof first.state === 'string' ? first.state : undefined
  const address = typeof first.address === 'string' ? first.address : undefined
  const hours =
    typeof first.open_time === 'string' && typeof first.close_time === 'string'
      ? `${first.open_time} – ${first.close_time}`
      : undefined

  const lines = [`${name}${city || state ? ` — ${[city, state].filter(Boolean).join(', ')}` : ''}`]
  if (address) {
    lines.push(address)
  }
  if (hours) {
    lines.push(`Hours: ${hours}`)
  }
  return lines.join('\n')
}

const parseQuickAction = (content: string): QuickAction | null => {
  if (!content.startsWith('/')) {
    return null
  }
  const [command, ...rest] = content.trim().split(/\s+/)
  const normalized = command.slice(1).toLowerCase()
  if (!SUPPORTED_COMMANDS.includes(normalized as QuickActionType)) {
    return null
  }
  return {
    type: normalized as QuickActionType,
    argument: rest.join(' ').trim()
  }
}

const extractBodyDetail = (payload: unknown): string | undefined => {
  if (!payload || typeof payload !== 'object') {
    return undefined
  }
  const detail = (payload as Record<string, unknown>).detail
  if (typeof detail === 'string' && detail.trim().length > 0) {
    return detail
  }
  const message = (payload as Record<string, unknown>).message
  if (typeof message === 'string' && message.trim().length > 0) {
    return message
  }
  return undefined
}

const isLikelyNetworkError = (error: unknown): boolean => {
  if (!(error instanceof Error)) {
    return false
  }
  return /network|fetch/i.test(error.message)
}

const getApiErrorMessage = (error: ApiError, fallback: string, serverFallback?: string): string => {
  if (error.status >= 500) {
    return serverFallback ?? fallback
  }
  const detail = extractBodyDetail(error.body)
  if (detail) {
    return detail
  }
  return error.message || fallback
}

const getQuickActionErrorMessage = (type: ToolQuickAction, error: unknown): string => {
  const fallback = QUICK_ACTION_FALLBACK[type]
  if (error instanceof ApiError) {
    return getApiErrorMessage(error, fallback)
  }
  if (error instanceof Error && error.message.trim().length > 0) {
    if (isLikelyNetworkError(error)) {
      return NETWORK_ERROR_MESSAGE
    }
    return error.message
  }
  return fallback
}

const getChatErrorMessage = (error: unknown): string => {
  if (error instanceof ApiError) {
    return getApiErrorMessage(error, CHAT_FAILURE_MESSAGE, CHAT_SERVER_UNAVAILABLE)
  }
  if (error instanceof Error && error.message.trim().length > 0) {
    if (isLikelyNetworkError(error)) {
      return NETWORK_ERROR_MESSAGE
    }
    return error.message
  }
  return CHAT_FAILURE_MESSAGE
}

export function useChat(): UseChatResult {
  const initialState = useMemo(
    () => loadSessionState() ?? bootstrapSessionState(),
    []
  )
  const [sessionId, setSessionId] = useState(initialState.sessionId)
  const [messages, setMessages] = useState<ChatMessage[]>(initialState.messages)
  const [actionsByTurn, setActionsByTurn] = useState<Record<string, ToolAction[]>>(
    initialState.actionsByTurn
  )
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const messagesRef = useRef(messages)
  const isMounted = useRef(false)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  useEffect(() => {
    updateSessionMessages(messages, actionsByTurn, sessionId)
  }, [messages, actionsByTurn, sessionId])

  const appendMessage = useCallback((message: ChatMessage) => {
    const next = [...messagesRef.current, message]
    messagesRef.current = next
    setMessages(next)
    return next
  }, [])

  const setTurnActions = useCallback((turnKey: string, actions: ToolAction[]) => {
    setActionsByTurn((prev) => ({ ...prev, [turnKey]: actions }))
  }, [])

  const acknowledgeError = useCallback((message: string) => {
    setError(message)
    appendMessage({
      role: 'assistant',
      content: message
    })
  }, [appendMessage])

  const reportToolError = useCallback(
    (tool: ToolQuickAction, turnKey: string | null, err: unknown) => {
      const message = getQuickActionErrorMessage(tool, err)
      acknowledgeError(message)
      if (turnKey) {
        setTurnActions(turnKey, [
          {
            type: 'tool_result',
            tool,
            status: 'error',
            message
          }
        ])
      }
    },
    [acknowledgeError, setTurnActions]
  )

  const resetConversation = useCallback(async () => {
    setError(null)
    setIsSending(true)
    try {
      if (sessionId) {
        try {
          await resetSession(sessionId)
        } catch {
          // Swallow server errors; local reset still proceeds.
        }
      }
      clearSessionState()
      const freshState = bootstrapSessionState()
      if (!isMounted.current) {
        return
      }
      setSessionId(freshState.sessionId)
      messagesRef.current = []
      setMessages([])
      setActionsByTurn({})
    } finally {
      setIsSending(false)
    }
  }, [sessionId])

  const handleQuickAction = useCallback(
    async (
      action: QuickAction,
      turnKey: string | null
    ) => {
      if (action.type !== 'reset' && !turnKey) {
        acknowledgeError('Unable to record tool activity for this turn.')
        return
      }

      switch (action.type) {
        case 'calc': {
          if (!action.argument) {
            acknowledgeError('Provide an expression after /calc to evaluate.')
            return
          }
          try {
            const result = await getCalc(action.argument)
            appendMessage({
              role: 'assistant',
              content: formatCalcResponse(result.expression, result.result)
            })
            if (turnKey) {
              setTurnActions(turnKey, [
                {
                  type: 'tool_result',
                  tool: 'calc',
                  status: 'success',
                  data: result,
                  message: `Evaluated ${result.expression}`
                }
              ])
            }
          } catch (err) {
            reportToolError('calc', turnKey, err)
            return
          }
          break
        }
        case 'products': {
          if (!action.argument) {
            acknowledgeError('Provide a query after /products to search the catalog.')
            return
          }
          try {
            const response = await getProducts(action.argument, 3)
            appendMessage({
              role: 'assistant',
              content: formatProductsResponse(
                response.query,
                response.summary,
                response.topK.map((hit) =>
                  [hit.title, hit.variantTitle].filter(Boolean).join(' ').trim()
                )
              )
            })
            if (turnKey) {
              setTurnActions(turnKey, [
                {
                  type: 'tool_result',
                  tool: 'products',
                  status: 'success',
                  data: response,
                  message: `Retrieved ${response.topK.length} product hits`
                }
              ])
            }
          } catch (err) {
            reportToolError('products', turnKey, err)
            return
          }
          break
        }
        case 'outlets': {
          if (!action.argument) {
            acknowledgeError('Provide a query after /outlets to search store locations.')
            return
          }
          try {
            const response = await getOutlets(action.argument)
            appendMessage({
              role: 'assistant',
              content: formatOutletsResponse(response.query, response.rows)
            })
            if (turnKey) {
              setTurnActions(turnKey, [
                {
                  type: 'tool_result',
                  tool: 'outlets',
                  status: 'success',
                  data: response,
                  message: `Executed SQL: ${response.sql}`
                }
              ])
            }
          } catch (err) {
            reportToolError('outlets', turnKey, err)
            return
          }
          break
        }
        case 'reset': {
          await resetConversation()
          break
        }
      }
    },
    [acknowledgeError, appendMessage, reportToolError, resetConversation, setTurnActions]
  )

  const sendUserMessage = useCallback(
    async (rawContent: string) => {
      const content = rawContent.trim()
      if (!content || isSending) {
        return
      }

      setIsSending(true)
      setError(null)

      const quickAction = parseQuickAction(content)

      const executeSend = async () => {
        if (quickAction?.type === 'reset') {
          await handleQuickAction(quickAction, null)
          return
        }

        const userMessage: ChatMessage = { role: 'user', content }
        const nextMessages = appendMessage(userMessage)
        const turnKey = deriveTurnKey(nextMessages)

        if (quickAction) {
          await handleQuickAction(quickAction, turnKey)
          return
        }

        const response = await postChat({
          sessionId,
          messages: nextMessages
        })
        appendMessage(response.response)
        if (turnKey) {
          setTurnActions(turnKey, response.actions)
        }
      }

      try {
        await executeSend()
      } catch (err) {
        const friendlyMessage = getChatErrorMessage(err)
        acknowledgeError(friendlyMessage)
        console.error(err)
      } finally {
        if (isMounted.current) {
          setIsSending(false)
        }
      }
    },
    [
      acknowledgeError,
      appendMessage,
      handleQuickAction,
      isSending,
      sessionId,
      setTurnActions
    ]
  )

  const clearError = useCallback(() => setError(null), [])

  return {
    sessionId,
    messages,
    actionsByTurn,
    isSending,
    error,
    sendUserMessage,
    resetConversation,
    clearError
  }
}

