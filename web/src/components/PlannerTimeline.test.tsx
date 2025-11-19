import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { PlannerTimeline } from './PlannerTimeline'

describe('PlannerTimeline', () => {
  it('renders a placeholder when there are no events', () => {
    render(<PlannerTimeline events={[]} isConnected={false} />)

    expect(screen.getByText(/planner steps will appear here/i)).toBeInTheDocument()
  })

  it('groups planner events by node and summarizes steps', () => {
    const localeSpy = vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('12:34:56')
    render(
      <PlannerTimeline
        isConnected
        events={[
          { id: 'node-start', type: 'node_start', node: 'classify_intent', status: 'pending', timestamp: '2025-01-01T00:00:00.000Z' },
          {
            id: 'llm',
            type: 'llm_call',
            node: 'classify_intent',
            status: 'success',
            timestamp: '2025-01-01T00:00:01.000Z',
            data: { callsUsed: 2, maxCalls: 4 }
          },
          { id: 'decision', type: 'decision', node: 'classify_intent', status: 'success', message: 'Ready to respond', timestamp: '2025-01-01T00:00:02.000Z' },
          { id: 'node-end', type: 'node_end', node: 'classify_intent', status: 'success', timestamp: '2025-01-01T00:00:03.000Z' }
        ]}
      />
    )

    expect(screen.getByText('Classify Intent')).toBeInTheDocument()
    expect(screen.getByText(/llm_call → decision/i)).toBeInTheDocument()
    expect(screen.getByText(/Ready to respond/i)).toBeInTheDocument()
    expect(screen.getByText('LLM calls 2/4')).toBeInTheDocument()
    expect(screen.getByText('12:34:56')).toBeInTheDocument()
    localeSpy.mockRestore()
  })

  it('hides repeated ready and heartbeat events in the main list', () => {
    render(
      <PlannerTimeline
        isConnected
        events={[
          { id: 'ready-1', type: 'ready', status: 'ready', timestamp: '2025-01-01T00:00:00.000Z' },
          { id: 'heartbeat-1', type: 'heartbeat', status: 'idle', timestamp: '2025-01-01T00:00:01.000Z' },
          { id: 'ready-2', type: 'ready', status: 'ready', timestamp: '2025-01-01T00:00:02.000Z' },
          { id: 'heartbeat-2', type: 'heartbeat', status: 'idle', timestamp: '2025-01-01T00:00:03.000Z' },
          { id: 'node-start', type: 'node_start', node: 'classify_intent', status: 'pending', timestamp: '2025-01-01T00:00:04.000Z' }
        ]}
      />
    )

    expect(screen.getAllByText(/planner ready/i)).toHaveLength(1)
    expect(screen.queryByText(/heartbeat/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Planner Activity/i)).toBeVisible()
  })

  it('shows raw event debug output when enabled', async () => {
    const user = userEvent.setup()
    render(
      <PlannerTimeline
        isConnected
        enableDebug
        events={[
          { id: '1', type: 'node_start', node: 'classify_intent', status: 'success', timestamp: 'now' }
        ]}
      />
    )

    const toggle = screen.getByRole('button', { name: /show raw events/i })
    await user.click(toggle)

    const debug = screen.getByText(/classify_intent/i)
    expect(debug).toBeInTheDocument()
  })
})

