import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ChatMessage, ToolAction } from '../api/types'
import { MessageList } from './MessageList'

describe('MessageList', () => {
  it('renders roles and timestamps', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'Hi' },
      { role: 'assistant', content: 'Welcome' }
    ]
    const actionsByTurn: Record<string, ToolAction[]> = {
      '0': [{ type: 'tool_result', tool: 'calc', status: 'success', message: 'done' }]
    }

    render(
      <MessageList
        messages={messages}
        timestamps={[Date.now(), Date.now()]}
        actionsByTurn={actionsByTurn}
      />
    )

    expect(screen.getByText(/You/i)).toBeInTheDocument()
    expect(screen.getByText(/Assistant/i)).toBeInTheDocument()
    expect(screen.getByText(/calc/i)).toBeInTheDocument()
  })
})

