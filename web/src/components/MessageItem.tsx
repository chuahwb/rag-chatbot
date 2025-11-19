import type { ChatMessage, ToolAction } from '../api/types'

interface MessageItemProps {
  message: ChatMessage
  timestamp?: number
  actions?: ToolAction[]
}

const roleLabels: Record<ChatMessage['role'], string> = {
  user: 'You',
  assistant: 'Assistant',
  tool: 'Tool'
}

const formatTimestamp = (timestamp?: number) => {
  if (!timestamp) {
    return ''
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit'
  }).format(timestamp)
}

const renderContent = (content: string) => {
  const lines = content.split('\n')
  return lines.map((line, index) => (
    <span key={`${line}-${index}`}>
      {line}
      {index < lines.length - 1 && <br />}
    </span>
  ))
}

export function MessageItem({ message, timestamp, actions }: MessageItemProps) {
  const roleClass = `message__bubble message__bubble--${message.role}`

  return (
    <li className={`message message--${message.role}`}>
      <div className="message__meta">
        <span className="message__role">{roleLabels[message.role]}</span>
        {timestamp && <time>{formatTimestamp(timestamp)}</time>}
      </div>
      <div className={roleClass}>{renderContent(message.content)}</div>
      {actions && actions.length > 0 && (
        <div className="message__actions">
          {actions.map((action, index) => (
            <span key={`${action.tool ?? 'planner'}-${index}`} className="message__tag">
              {action.tool ?? action.type}
            </span>
          ))}
        </div>
      )}
    </li>
  )
}

