import { useEffect, useMemo, useRef, useState } from 'react'

interface QuickAction {
  command: string
  description: string
}

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  isSending: boolean
  quickActions: QuickAction[]
}

export function Composer({
  value,
  onChange,
  onSubmit,
  isSending,
  quickActions
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const containerClassName = [
    'composer__input',
    isSending ? 'composer__input--busy' : null
  ]
    .filter(Boolean)
    .join(' ')

  const showSuggestions = value.startsWith('/') && !value.includes(' ')
  const filterValue = value.slice(1).toLowerCase()
  const suggestions = useMemo(() => {
    if (!showSuggestions) {
      return []
    }
    return quickActions.filter((action) =>
      action.command.toLowerCase().startsWith(`/${filterValue}`)
    )
  }, [filterValue, quickActions, showSuggestions])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        textareaRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (isSending) {
      event.preventDefault()
      return
    }
    if (event.key === 'ArrowDown' && suggestions.length > 0) {
      event.preventDefault()
      setActiveIndex((prev) => (prev + 1) % suggestions.length)
      return
    }
    if (event.key === 'ArrowUp' && suggestions.length > 0) {
      event.preventDefault()
      setActiveIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length)
      return
    }
    if (
      showSuggestions &&
      suggestions.length > 0 &&
      !value.includes(' ') &&
      event.key === 'Enter' &&
      !event.shiftKey
    ) {
      event.preventDefault()
      const safeIndex = Math.min(activeIndex, suggestions.length - 1)
      onChange(`${suggestions[safeIndex].command} `)
      return
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <div className="composer">
      <div className={containerClassName}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Send a message. Use /calc, /products, /outlets, or /reset for quick actions."
          rows={3}
          aria-disabled={isSending}
          aria-live="off"
          disabled={isSending}
        />
        <button
          type="button"
          className="composer__send"
          onClick={onSubmit}
          disabled={isSending || value.trim().length === 0}
        >
          {isSending ? 'Sending…' : 'Send'}
        </button>
      </div>
      {isSending && (
        <p className="composer__status" role="status" aria-live="polite">
          Assistant is thinking…
        </p>
      )}
      {suggestions.length > 0 && (
        <ul className="composer__suggestions">
          {suggestions.map((action, index) => (
            <li
              key={action.command}
              className={
                index === activeIndex
                  ? 'composer__suggestion composer__suggestion--active'
                  : 'composer__suggestion'
              }
              onMouseDown={(event) => {
                event.preventDefault()
                onChange(`${action.command} `)
                setActiveIndex(index)
              }}
            >
              <span className="composer__suggestion-command">{action.command}</span>
              <span className="composer__suggestion-description">{action.description}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

