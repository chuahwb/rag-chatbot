import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolActivity } from './ToolActivity'

describe('ToolActivity', () => {
  it('shows placeholder when no actions exist', () => {
    render(<ToolActivity actions={[]} />)
    expect(screen.getByText(/tool calls will appear/i)).toBeInTheDocument()
  })

  it('renders tool details for each action', () => {
    render(
      <ToolActivity
        actions={[
          {
            type: 'tool_result',
            tool: 'calc',
            status: 'success',
            message: 'Computed expression.'
          }
        ]}
      />
    )

    expect(screen.getByText(/Calculator/i)).toBeInTheDocument()
    expect(screen.getByText(/Computed expression/i)).toBeInTheDocument()
  })
})

