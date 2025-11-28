export type ChatRole = 'user' | 'assistant' | 'tool'

export interface ChatMessage {
  role: ChatRole
  content: string
}

export type ToolActionType = 'decision' | 'tool_call' | 'tool_result'
export type ToolStatus = 'success' | 'error'
export type ToolName = 'calc' | 'products' | 'outlets'

export interface ToolAction {
  type: ToolActionType
  tool?: ToolName | null
  args?: Record<string, unknown> | null
  status?: ToolStatus | null
  data?: unknown
  message?: string | null
}

export interface ChatRequest {
  sessionId: string
  messages: ChatMessage[]
}

export interface ChatResponse {
  response: ChatMessage
  actions: ToolAction[]
  memory: Record<string, unknown>
}

export interface CalculatorResponse {
  expression: string
  result: number
}

export interface ProductHit {
  title: string
  variantTitle?: string | null
  variantId?: string | null
  score: number
  url?: string | null
  price?: number | null
  compareAtPrice?: number | null
  available?: boolean | null
  imageUrl?: string | null
  sku?: string | null
  productType?: string | null
  tags?: string[]
  snippet?: string | null
}

export interface ProductSearchResponse {
  query: string
  topK: ProductHit[]
  summary?: string | null
}

export interface OutletsQueryResponse {
  query: string
  sql: string
  params: Record<string, unknown>
  rows: Array<Record<string, unknown>>
}

export type ApiResult<T> = Promise<T>

