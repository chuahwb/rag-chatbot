import { useEffect, useMemo, useRef } from 'react'

import type { ChatMessage, ToolAction } from '../api/types'
import { MessageItem } from './MessageItem'

interface MessageListProps {
  messages: ChatMessage[]
  timestamps: number[]
  actionsByTurn: Record<string, ToolAction[]>
}

const userTurnsUntilIndex = (messages: ChatMessage[], index: number) =>
  messages.slice(0, index + 1).reduce((count, message) => (message.role === 'user' ? count + 1 : count), 0)

export function MessageList({ messages, timestamps, actionsByTurn }: MessageListProps) {
  const listRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = listRef.current
    if (container) {
      container.scrollTop = container.scrollHeight
    }
  }, [messages.length])

  const renderedMessages = useMemo(
    () =>
      messages.map((message, index) => {
        let actions: ToolAction[] | undefined
        if (message.role === 'assistant') {
          const userTurns = userTurnsUntilIndex(messages, index)
          if (userTurns > 0) {
            const turnKey = String(userTurns - 1)
            actions = actionsByTurn[turnKey]
          }
        }
        return (
          <MessageItem
            key={`${message.role}-${index}-${message.content.slice(0, 8)}`}
            message={message}
            timestamp={timestamps[index]}
            actions={actions}
          />
        )
      }),
    [messages, timestamps, actionsByTurn]
  )

  return (
    <div className="message-list" ref={listRef} data-testid="message-list">
      <ul>{renderedMessages}</ul>
    </div>
  )
}

