import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sendUserMessage = vi.fn().mockResolvedValue(undefined)
const resetConversation = vi.fn().mockResolvedValue(undefined)
const clearError = vi.fn()

const mockUseChat = vi.fn()

const buildChatState = (overrides: Partial<ReturnType<typeof mockUseChat>> = {}) => ({
  sessionId: 'session-1',
  messages: [
    { role: 'user', content: 'Hi' },
    { role: 'assistant', content: 'Hello' }
  ],
  actionsByTurn: {
    '0': [{ type: 'tool_result', tool: 'calc', status: 'success', message: 'done' }]
  },
  isSending: false,
  error: null,
  sendUserMessage,
  resetConversation,
  clearError,
  ...overrides
})

vi.mock('../hooks/useChat', () => ({
  useChat: () => mockUseChat()
}))

vi.mock('../hooks/useEvents', () => ({
  useEvents: () => ({
    events: [],
    isConnected: true,
    lastError: null
  })
}))

import { ChatWindow } from './ChatWindow'

describe('ChatWindow', () => {
  beforeEach(() => {
    sendUserMessage.mockClear()
    resetConversation.mockClear()
    clearError.mockClear()
    mockUseChat.mockReset()
    mockUseChat.mockReturnValue(buildChatState())
  })

  it('submits input via the composer', async () => {
    const user = userEvent.setup()
    render(<ChatWindow />)

    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'calculate 1+1')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(sendUserMessage).toHaveBeenCalledWith('calculate 1+1')
  })

  it('invokes reset when reset session button is clicked', async () => {
    const user = userEvent.setup()
    render(<ChatWindow />)

    await user.click(screen.getByRole('button', { name: /reset session/i }))
    expect(resetConversation).toHaveBeenCalled()
  })

  it('disables reset when chat is busy', () => {
    mockUseChat.mockReturnValueOnce(buildChatState({ isSending: true }))
    render(<ChatWindow />)

    const resetButton = screen.getByRole('button', { name: /reset session/i })
    expect(resetButton).toBeDisabled()
  })

  it('exposes scrollable regions for chat and planner activity', () => {
    render(<ChatWindow />)

    expect(screen.getByTestId('message-list')).toBeInTheDocument()
    expect(screen.getByTestId('planner-timeline')).toBeInTheDocument()
    expect(screen.getByTestId('planner-timeline-body')).toBeInTheDocument()
  })
})

