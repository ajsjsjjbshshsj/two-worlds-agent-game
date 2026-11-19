const messages: Record<number, string> = {
  400: '填写内容不符合要求，请检查后再提交。',
  401: '会话已失效，请重新登录。',
  422: '填写内容不符合要求，请检查后再提交。',
  429: '请求过于频繁，请稍后再试。',
  503: '服务暂时不可用，请稍后再试。',
}
const resourceMessages: Record<string, string> = {
  INVITE_INVALID: '邀请无效、已过期或已刷新。请向搭档索取新链接。',
  PAIR_FULL: '房间已满员，无法加入或刷新邀请。',
  PAIR_NOT_FOUND: '房间不存在或你无权访问，请刷新房间列表。',
  SAVE_NOT_FOUND: '存档不存在或你无权访问，请返回书架。',
  SCRIPT_NOT_FOUND: '此内容版本尚未发布或不可用，请返回书架。',
  SCRIPT_VERSION_CONFLICT: '已有存档绑定旧版本，请刷新书架并继续原存档。',
  PAIR_NOT_READY: '请等待搭档加入后再开始。',
  INVALID_CREDENTIALS: '邮箱或密码错误。',
  CSRF_REJECTED: '请求来源未获授权，请检查前后端地址配置。',
  EMAIL_ALREADY_REGISTERED: '此邮箱已注册，请登录或找回密码。',
  INVALID_CODE: '验证码不正确，请核对后再试。',
  CODE_EXPIRED: '验证码已过期，请重新申请。',
  CODE_LOCKED: '验证码尝试次数已达上限，请重新申请。',
  DEPENDENCY_UNAVAILABLE: '服务暂时不可用，请稍后再试。',
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly retryable: boolean,
    readonly retryAfter?: number,
  ) {
    super(
      code === 'TIMEOUT'
        ? '请求超时，请检查连接。'
        : code === 'NETWORK_ERROR'
          ? '无法连接服务，请检查网络或服务地址。'
          : code === 'INVALID_RESPONSE'
            ? '服务返回的数据无法识别，请稍后再试。'
            : (resourceMessages[code] ?? messages[status] ?? '请求未能完成，请稍后再试。'),
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
  expectedStatus?: 200 | 202 | 204
  query?: { pair_id: string }
}

function retryAfterSeconds(value: string | null): number | undefined {
  if (value === null || !/^\d+$/.test(value)) return
  const seconds = Number(value)
  return Number.isSafeInteger(seconds) ? seconds : undefined
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
      if (!validPath && path !== '/api/verification-codes' && path !== '/api/password-resets')
        throw new ApiError(0, 'INVALID_REQUEST', false)
      let query = ''
      if (request.query !== undefined) {
        if (
          path !== '/api/saves' ||
          (request.method ?? 'GET') !== 'GET' ||
          Object.keys(request.query).join(',') !== 'pair_id' ||
          typeof request.query.pair_id !== 'string' ||
          /^[a-z][a-z0-9_]{0,63}$/.exec(request.query.pair_id)?.[0] !== request.query.pair_id
        )
          throw new ApiError(0, 'INVALID_REQUEST', false)
        query = '?' + new URLSearchParams(request.query).toString()
      }
      const controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? 15000)
      let status = 0
      try {
        const headers = new Headers({ Accept: 'application/json' })
        if (request.body !== undefined) headers.set('Content-Type', 'application/json')
        const response = await fetch(base + path + query, {
          method: request.method ?? 'GET',
          headers,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
          cache: 'no-store',
          credentials: 'include',
          redirect: 'error',
          signal: controller.signal,
        })
        status = response.status
        if (
          response.ok &&
          request.expectedStatus !== undefined &&
          status !== request.expectedStatus
        )
          throw new ApiError(status, 'INVALID_RESPONSE', false)
        const retryAfter =
          status === 429 ? retryAfterSeconds(response.headers.get('Retry-After')) : undefined
        if (response.status === 204 && response.ok) return undefined as T
        let data: unknown
        try {
          data = await response.json()
        } catch {
          if (controller.signal.aborted) throw new ApiError(0, 'TIMEOUT', true)
          throw new ApiError(status, 'INVALID_RESPONSE', false, retryAfter)
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
            throw new ApiError(status, data.error.code, data.error.retryable, retryAfter)
          }
          throw new ApiError(status, 'INVALID_RESPONSE', false, retryAfter)
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
