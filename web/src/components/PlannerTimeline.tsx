import { useEffect, useMemo, useRef, useState } from 'react'

import type { PlannerEvent } from '../hooks/useEvents'

interface PlannerTimelineProps {
  events: PlannerEvent[]
  isConnected: boolean
  enableDebug?: boolean
}

interface TimelineBlock {
  key: string
  title: string
  status: string
  sequence?: string
  message?: string
  timestamp?: string
  meta?: string
}

interface NodeBlock extends TimelineBlock {
  node: string
  events: PlannerEvent[]
}

const statusLabel = (status?: string) => {
  if (!status) {
    return 'pending'
  }
  return status.toLowerCase()
}

const NODE_LABELS: Record<string, string> = {
  classify_intent: 'Classify Intent',
  extract_slots: 'Extract Slots',
  decide_action: 'Decide Action',
  synthesize: 'Synthesize Reply'
}

const describeNode = (node?: string): string | undefined => {
  if (!node) {
    return undefined
  }
  const readable = NODE_LABELS[node]
  if (readable) {
    return readable
  }
  return node
}

const buildSequence = (events: PlannerEvent[]): string | undefined => {
  const interestingTypes = events
    .map((evt) => evt.type)
    .filter(
      (type): type is string =>
        Boolean(type) && !['node_start', 'node_end', 'heartbeat', 'ready'].includes(type!)
    )
  if (interestingTypes.length === 0) {
    return undefined
  }
  const compact = interestingTypes.filter((type, index) => type !== interestingTypes[index - 1])
  const base = compact.join(' → ')
  return base
}

const formatTimestamp = (value?: string): string | undefined => {
  if (!value) {
    return undefined
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return undefined
  }
  return parsed.toLocaleTimeString([], { hour12: false })
}

const createSystemBlock = (event: PlannerEvent): TimelineBlock => ({
  key: event.id,
  title: event.type === 'ready' ? 'Planner ready' : event.type,
  status: statusLabel(event.status),
  message: event.message,
  timestamp: formatTimestamp(event.timestamp)
})

const deriveMeta = (events: PlannerEvent[]): string | undefined => {
  const reversed = [...events].reverse()
  const llmEvent = reversed.find((evt) => evt.type === 'llm_call')
  if (llmEvent && llmEvent.data) {
    const used = typeof llmEvent.data.callsUsed === 'number' ? llmEvent.data.callsUsed : undefined
    const max = typeof llmEvent.data.maxCalls === 'number' ? llmEvent.data.maxCalls : undefined
    if (used !== undefined && max !== undefined) {
      return `LLM calls ${used}/${max}`
    }
  }
  const toolEvent = reversed.find((evt) => evt.type === 'tool_call' || evt.type === 'tool_result')
  if (toolEvent?.message) {
    return toolEvent.message
  }
  return undefined
}

const summarizeBlocks = (events: PlannerEvent[]): TimelineBlock[] => {
  const blocks: Array<TimelineBlock | NodeBlock> = []
  const activeNodes = new Map<string, NodeBlock>()
  let readyRendered = false

  for (const event of events) {
    if (event.type === 'heartbeat') {
      continue
    }
    if (event.type === 'ready') {
      if (readyRendered) {
        continue
      }
      readyRendered = true
      blocks.push(createSystemBlock(event))
      continue
    }

    if (!event.node) {
      blocks.push(createSystemBlock(event))
      continue
    }

    const existingBlock = activeNodes.get(event.node)
    const shouldStartNewBlock =
      !existingBlock || event.type === 'node_start' || existingBlock.events.length === 0

    let currentBlock = existingBlock
    if (shouldStartNewBlock) {
      const key = `${event.node}-${event.timestamp ?? event.id}`
      currentBlock = {
        key,
        node: event.node,
        title: describeNode(event.node) ?? event.node,
        status: 'pending',
        events: []
      }
      activeNodes.set(event.node, currentBlock)
      blocks.push(currentBlock)
    }

    currentBlock!.events.push(event)
    if (event.status) {
      currentBlock!.status = statusLabel(event.status)
    }
    if (event.message) {
      const prefersErrorMessage = event.status === 'error'
      if (prefersErrorMessage || !currentBlock!.message) {
        currentBlock!.message = event.message
      }
    }
    if (event.type === 'node_end') {
      activeNodes.delete(event.node)
    }
  }

  return blocks.map<TimelineBlock>((block) => {
    if ('node' in block) {
      const finalStatus = block.status ?? 'pending'
      const lastEvent = block.events.at(-1)
      return {
        key: block.key,
        title: block.title,
        status: finalStatus,
        sequence: buildSequence(block.events),
        message: block.message,
        timestamp: formatTimestamp(lastEvent?.timestamp),
        meta: deriveMeta(block.events)
      }
    }
    return block
  })
}

export function PlannerTimeline({ events, isConnected, enableDebug = false }: PlannerTimelineProps) {
  const [showDebug, setShowDebug] = useState(false)
  const summaries = useMemo(() => summarizeBlocks(events), [events])
  const scrollSignature = useMemo(
    () =>
      summaries
        .map((block) => `${block.key}:${block.timestamp ?? ''}:${block.status}:${block.sequence ?? ''}`)
        .join('|'),
    [summaries]
  )
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const lastItemRef = useRef<HTMLLIElement | null>(null)

  useEffect(() => {
    if (lastItemRef.current && typeof lastItemRef.current.scrollIntoView === 'function') {
      lastItemRef.current.scrollIntoView({ block: 'end' })
    } else if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [scrollSignature])

  const debugPayload = useMemo(() => {
    if (!enableDebug) {
      return ''
    }
    const recent = events.slice(-10)
    return JSON.stringify(recent, null, 2)
  }, [enableDebug, events])

  return (
    <section className="planner-timeline" data-testid="planner-timeline">
      <header className="planner-timeline__header">
        <div>
          <p className="planner-timeline__title">Planner Activity</p>
          <p className="planner-timeline__subtitle">
            {isConnected ? 'Live updates' : 'Disconnected'}
          </p>
        </div>
        <span
          className={`planner-timeline__pill ${
            isConnected ? 'planner-timeline__pill--online' : 'planner-timeline__pill--offline'
          }`}
        >
          {isConnected ? 'Online' : 'Offline'}
        </span>
      </header>
      <div className="planner-timeline__body" data-testid="planner-timeline-body" ref={bodyRef}>
        {summaries.length === 0 ? (
          <p className="planner-timeline__placeholder">Planner steps will appear here.</p>
        ) : (
          <ul className="planner-timeline__list">
            {summaries.map((block, index) => {
              const isLast = index === summaries.length - 1
              return (
                <li
                  key={block.key}
                  className="planner-timeline__block"
                  ref={isLast ? lastItemRef : undefined}
                >
                  <div className="planner-timeline__block-header">
                    <p className="planner-timeline__node-label">{block.title}</p>
                    <div className="planner-timeline__block-meta">
                      {block.timestamp && (
                        <time className="planner-timeline__timestamp">{block.timestamp}</time>
                      )}
                      <span className={`planner-timeline__status planner-timeline__status--${block.status}`}>
                        {block.status}
                      </span>
                    </div>
                  </div>
                  {(block.sequence || block.meta) && (
                    <div className="planner-timeline__chips">
                      {block.sequence && (
                        <span className="planner-timeline__chip">{block.sequence}</span>
                      )}
                      {block.meta && (
                        <span className="planner-timeline__chip planner-timeline__chip--muted">
                          {block.meta}
                        </span>
                      )}
                    </div>
                  )}
                  {block.message && (
                    <p className="planner-timeline__message">
                      {block.message}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
      {enableDebug && (
        <div className="planner-timeline__debug">
          <button
            type="button"
            className="planner-timeline__debug-toggle"
            onClick={() => setShowDebug((prev) => !prev)}
          >
            {showDebug ? 'Hide raw events' : 'Show raw events'}
          </button>
          {showDebug && <pre>{debugPayload}</pre>}
        </div>
      )}
    </section>
  )
}

