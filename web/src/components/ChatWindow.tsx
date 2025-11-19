import { useEffect, useMemo, useState } from 'react'

import type { ToolAction } from '../api/types'
import { Composer } from './Composer'
import { MessageList } from './MessageList'
import { PlannerTimeline } from './PlannerTimeline'
import { ToolActivity } from './ToolActivity'
import { useChat } from '../hooks/useChat'
import { useEvents } from '../hooks/useEvents'

const QUICK_ACTIONS = [
  { command: '/calc', description: 'Evaluate an expression quickly' },
  { command: '/products', description: 'Search curated product snippets' },
  { command: '/outlets', description: 'Query outlet information via Text2SQL' },
  { command: '/reset', description: 'Reset the conversation session' }
]

const countUserMessages = (messages: { role: string }[]) =>
  messages.reduce((count, message) => (message.role === 'user' ? count + 1 : count), 0)

const PLANNER_DEBUG_ENABLED = import.meta.env.VITE_ENABLE_PLANNER_DEBUG === 'true'

export function ChatWindow() {
  const [input, setInput] = useState('')
  const {
    sessionId,
    messages,
    actionsByTurn,
    isSending,
    error,
    sendUserMessage,
    resetConversation,
    clearError
  } = useChat()
  const { events, isConnected, lastError: eventsError } = useEvents(sessionId)
  const [timestamps, setTimestamps] = useState<number[]>([])

  useEffect(() => {
    // This effect derives display timestamps from the message list.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTimestamps((previous) => {
      if (messages.length === 0) {
        return []
      }
      if (messages.length < previous.length) {
        return previous.slice(0, messages.length)
      }
      if (messages.length === previous.length) {
        return previous
      }
      const additional = Array.from(
        { length: messages.length - previous.length },
        () => Date.now()
      )
      return [...previous, ...additional]
    })
  }, [messages])

  const latestActions = useMemo<ToolAction[]>(() => {
    const userTurns = countUserMessages(messages)
    if (userTurns === 0) {
      return []
    }
    const turnKey = String(userTurns - 1)
    return actionsByTurn[turnKey] ?? []
  }, [messages, actionsByTurn])

  const handleSubmit = async () => {
    const message = input.trim()
    if (!message) {
      return
    }
    // Clear immediately so the composer reflects the pending send.
    setInput('')
    await sendUserMessage(message)
  }

  const handleReset = async () => {
    setInput('')
    await resetConversation()
  }

  return (
    <div className="chat-layout">
      <div className="chat-panel">
        <header className="chat-panel__header">
          <div>
            <h1>ZUS Assistant</h1>
            <p className="chat-panel__subtitle">
              Multi-turn chat with tool and planner visibility
            </p>
          </div>
          <button
            className="chat-panel__reset"
            type="button"
            onClick={handleReset}
            disabled={isSending}
          >
            Reset Session
          </button>
        </header>
        <MessageList messages={messages} timestamps={timestamps} actionsByTurn={actionsByTurn} />
        {(error || eventsError) && (
          <div className="chat-panel__alerts">
            {error && (
              <div className="chat-panel__alert">
                <span>{error}</span>
                <button type="button" onClick={clearError}>
                  Dismiss
                </button>
              </div>
            )}
            {eventsError && <div className="chat-panel__alert">{eventsError}</div>}
          </div>
        )}
        <Composer
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          isSending={isSending}
          quickActions={QUICK_ACTIONS}
        />
      </div>
      <aside className="chat-sidebar">
        <PlannerTimeline events={events} isConnected={isConnected} enableDebug={PLANNER_DEBUG_ENABLED} />
        <div className="chat-sidebar__card">
          <div className="chat-sidebar__card-header">
            <p className="chat-sidebar__card-title">Tool Activity</p>
            <p className="chat-sidebar__card-subtitle">
              Latest turn tool calls and outcomes
            </p>
          </div>
          <ToolActivity actions={latestActions} />
        </div>
      </aside>
    </div>
  )
}

