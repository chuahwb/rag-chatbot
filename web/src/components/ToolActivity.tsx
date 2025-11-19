import type { ToolAction } from '../api/types'

interface ToolActivityProps {
  actions?: ToolAction[]
}

const toolLabels: Record<string, string> = {
  calc: 'Calculator',
  products: 'Product Search',
  outlets: 'Outlet Lookup'
}

const formatToolLabel = (tool?: string | null) => {
  if (!tool) {
    return 'Planner'
  }
  return toolLabels[tool] ?? tool
}

export function ToolActivity({ actions }: ToolActivityProps) {
  if (!actions || actions.length === 0) {
    return <p className="tool-activity__placeholder">Tool calls will appear for each turn.</p>
  }

  return (
    <ul className="tool-activity__list">
      {actions.map((action, index) => (
        <li key={`${action.type}-${action.tool ?? 'planner'}-${index}`} className="tool-activity__item">
          <div className="tool-activity__header">
            <span className="tool-activity__tool">{formatToolLabel(action.tool)}</span>
            <span className={`tool-activity__status tool-activity__status--${action.status ?? 'pending'}`}>
              {action.status ?? 'pending'}
            </span>
          </div>
          <p className="tool-activity__type">{action.type}</p>
          {action.message && <p className="tool-activity__message">{action.message}</p>}
        </li>
      ))}
    </ul>
  )
}

