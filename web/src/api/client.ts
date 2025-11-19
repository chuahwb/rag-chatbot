import type {
  CalculatorResponse,
  ChatRequest,
  ChatResponse,
  OutletsQueryResponse,
  ProductSearchResponse
} from './types'

const DEFAULT_BASE_URL = 'http://localhost:8000'

const baseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') ??
  DEFAULT_BASE_URL

const jsonHeaders = {
  'Content-Type': 'application/json'
}

const CHAT_REQUEST_TIMEOUT_MS = 20000

export class ApiError extends Error {
  status: number
  body?: unknown

  constructor(message: string, status: number, body?: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

function buildUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${baseUrl}${normalizedPath}`
}

function buildUrlWithSearch(
  path: string,
  params: Record<string, string | number | undefined>
): string {
  const url = new URL(buildUrl(path))
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null) {
      return
    }
    url.searchParams.set(key, String(value))
  })
  return url.toString()
}

async function parseBody(response: Response): Promise<unknown> {
  const raw = await response.text()
  if (!raw) {
    return null
  }

  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

async function handleJson<T>(response: Response): Promise<T> {
  const body = await parseBody(response)

  if (!response.ok) {
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? (body as { detail?: string }).detail
        : undefined
    const message = (detail ?? response.statusText) || 'Request failed'
    throw new ApiError(message, response.status, body)
  }

  return body as T
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...jsonHeaders,
      ...(init?.headers ?? {})
    }
  })
  return handleJson<T>(response)
}

const isAbortError = (error: unknown): boolean => {
  if (!(error instanceof Error)) {
    return false
  }
  return error.name === 'AbortError'
}

export async function postChat(payload: ChatRequest): Promise<ChatResponse> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), CHAT_REQUEST_TIMEOUT_MS)
  try {
    return await requestJson<ChatResponse>(buildUrl('/chat'), {
      method: 'POST',
      body: JSON.stringify(payload),
      signal: controller.signal
    })
  } catch (error) {
    if (isAbortError(error)) {
      throw new ApiError(
        'The assistant is taking longer than expected to respond.',
        408
      )
    }
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

export async function getCalc(query: string): Promise<CalculatorResponse> {
  const url = buildUrlWithSearch('/calc', { query })
  return requestJson<CalculatorResponse>(url)
}

export async function getProducts(
  query: string,
  k = 3
): Promise<ProductSearchResponse> {
  const url = buildUrlWithSearch('/products', { query, k })
  return requestJson<ProductSearchResponse>(url)
}

export async function getOutlets(
  query: string
): Promise<OutletsQueryResponse> {
  const url = buildUrlWithSearch('/outlets', { query })
  return requestJson<OutletsQueryResponse>(url)
}

export async function resetSession(sessionId: string): Promise<void> {
  await requestJson<void>(buildUrl(`/chat/session/${sessionId}`), {
    method: 'DELETE'
  })
}

export function getApiBaseUrl(): string {
  return baseUrl
}

