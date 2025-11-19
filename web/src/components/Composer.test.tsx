import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { useState } from 'react'

import { Composer } from './Composer'

const quickActions = [
  { command: '/calc', description: 'Calculator' },
  { command: '/products', description: 'Products' }
]

const ControlledComposer = ({
  onSubmit
}: {
  onSubmit: () => void
}) => {
  const [value, setValue] = useState('')
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      isSending={false}
      quickActions={quickActions}
    />
  )
}

describe('Composer', () => {
  it('submits message on Enter', async () => {
    const user = userEvent.setup()
    const handleSubmit = vi.fn()
    render(<ControlledComposer onSubmit={handleSubmit} />)

    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'hello')
    await user.keyboard('{Enter}')

    expect(handleSubmit).toHaveBeenCalled()
  })

  it('expands quick action suggestion when typing a slash command', () => {
    const handleSubmit = vi.fn()
    render(<ControlledComposer onSubmit={handleSubmit} />)

    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, { target: { value: '/c' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })

    expect(textarea).toHaveValue('/calc ')
    expect(handleSubmit).not.toHaveBeenCalled()
  })

  it('disables input and shows sending feedback while busy', () => {
    const handleSubmit = vi.fn()
    render(
      <Composer
        value="Working..."
        onChange={() => {}}
        onSubmit={handleSubmit}
        isSending={true}
        quickActions={quickActions}
      />
    )

    const textarea = screen.getByRole('textbox')
    expect(textarea).toBeDisabled()
    expect(screen.getByRole('button', { name: /sending/i })).toBeDisabled()
  })
})

