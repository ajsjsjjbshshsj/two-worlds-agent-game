const messages: Record<number, string> = {
  401: '会话已失效或恢复密钥不正确，请重新验证身份。',
  422: '填写内容不符合要求，请检查后再提交。',
  429: '请求过于频繁，请稍后再试。',
  503: '服务暂时不可用，请稍后再试。',
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly retryable: boolean,
  ) {
    super(
      code === 'TIMEOUT'
        ? '请求超时，请检查连接。'
        : code === 'NETWORK_ERROR'
          ? '无法连接服务，请检查网络或服务地址。'
          : code === 'INVALID_RESPONSE'
            ? '服务返回的数据无法识别，请稍后再试。'
            : (messages[status] ?? '请求未能完成，请稍后再试。'),
    )
    this.name = 'ApiError'
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  token?: string
}

export function createHttpClient(options: { baseUrl?: string; timeoutMs?: number } = {}) {
  const base = (options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  if (base) {
    const parsed = new URL(base, window.location.origin)
    if (
      !['http:', 'https:'].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      base.startsWith('//')
    ) {
      throw new ApiError(0, 'INVALID_CONFIGURATION', false)
    }
  }
  return {
    async request<T>(path: string, request: RequestOptions = {}): Promise<T> {
      // Compare the entire match: JavaScript's $ alone also accepts a final newline.
      const validPath =
        /^\/api\/[a-z][a-z0-9_]{0,63}(?:\/[a-z][a-z0-9_]{0,63})*$/.exec(path)?.[0] === path
      if (!validPath) throw new ApiError(0, 'INVALID_REQUEST', false)
      const controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? 15000)
      let status = 0
      try {
        const headers = new Headers({ Accept: 'application/json' })
        if (request.token) headers.set('Authorization', `Bearer ${request.token}`)
        if (request.body !== undefined) headers.set('Content-Type', 'application/json')
        const response = await fetch(base + path, {
          method: request.method ?? 'GET',
          headers,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
          cache: 'no-store',
          credentials: 'omit',
          redirect: 'error',
          signal: controller.signal,
        })
        status = response.status
        if (response.status === 204 && response.ok) return undefined as T
        let data: unknown
        try {
          data = await response.json()
        } catch {
          if (controller.signal.aborted) throw new ApiError(0, 'TIMEOUT', true)
          throw new ApiError(status, 'INVALID_RESPONSE', false)
        }
        if (!response.ok) {
          if (
            isRecord(data) &&
            isRecord(data.error) &&
            typeof data.error.code === 'string' &&
            /^[A-Z][A-Z0-9_]{0,63}$/.test(data.error.code) &&
            typeof data.error.message === 'string' &&
            typeof data.error.retryable === 'boolean'
          ) {
            // Fixed local messages never echo response bodies or submitted credentials.
            throw new ApiError(status, data.error.code, data.error.retryable)
          }
          throw new ApiError(status, 'INVALID_RESPONSE', false)
        }
        return data as T
      } catch (error) {
        if (error instanceof ApiError) throw error
        throw new ApiError(status, controller.signal.aborted ? 'TIMEOUT' : 'NETWORK_ERROR', true)
      } finally {
        window.clearTimeout(timeout)
      }
    },
  }
}
