import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createHttpClient } from '../src/services/http'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

describe('HTTP boundary', () => {
  it.each([
    '/api/me',
    '/api/verification-codes',
    '/api/password-resets',
    '/api/pairs/pair_123/invite',
    '/api/saves/save_123',
    '/api/sessions/current',
    `/api/${'a'.repeat(64)}`,
  ])('accepts safe Identifier segments: %s', async (path) => {
    const fetch = vi.fn().mockResolvedValue(json({ ok: true }))
    vi.stubGlobal('fetch', fetch)
    await expect(createHttpClient().request(path)).resolves.toEqual({ ok: true })
    expect(fetch.mock.calls[0]![0]).toBe(path)
  })
  it.each([
    '/api/../me',
    '/api/saves/..',
    '/api/me?token=secret',
    '/api/me#secret',
    '/me',
    'https://example.test/api/me',
    '//api/me',
    '/api//me',
    '/api/me/',
    '/api/123',
    '/api/UPPER',
    '/api/pair-123',
    '/api/%2e%2e/me',
    '/api/saves\\save_123',
    `/api/${'a'.repeat(65)}`,
    '/api/me\n',
    '/api/me\r',
  ])('rejects unsafe paths before fetch: %s', async (path) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(createHttpClient().request(path)).rejects.toMatchObject({
      code: 'INVALID_REQUEST',
    })
    expect(fetch).not.toHaveBeenCalled()
  })
  it('GET lets the browser send cookies and disables cache', async () => {
    const fetch = vi.fn().mockResolvedValue(json({ account: 'ok' }))
    vi.stubGlobal('fetch', fetch)
    expect(await createHttpClient().request('/api/me')).toEqual({
      account: 'ok',
    })
    const [url, options] = fetch.mock.calls[0]!
    expect(url).toBe('/api/me')
    expect(options).toMatchObject({
      method: 'GET',
      cache: 'no-store',
      credentials: 'include',
      redirect: 'error',
    })
    expect(new Headers(options.headers).has('Authorization')).toBe(false)
    expect(new Headers(options.headers).has('Origin')).toBe(false)
    expect(new Headers(options.headers).has('Cookie')).toBe(false)
  })
  it('POST encodes JSON and configured base URL', async () => {
    const fetch = vi.fn().mockResolvedValue(json({ ok: true }))
    vi.stubGlobal('fetch', fetch)
    await createHttpClient({ baseUrl: 'https://api.example.test/' }).request('/api/accounts', {
      method: 'POST',
      body: { display_name: '旅人' },
    })
    expect(fetch.mock.calls[0]![0]).toBe('https://api.example.test/api/accounts')
    expect(fetch.mock.calls[0]![1].body).toBe('{"display_name":"旅人"}')
    expect(new Headers(fetch.mock.calls[0]![1].headers).get('content-type')).toBe(
      'application/json',
    )
  })
  it('DELETE accepts empty 204 without parsing JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    expect(
      await createHttpClient().request('/api/sessions/current', { method: 'DELETE' }),
    ).toBeUndefined()
  })
  it.each([401, 422, 429, 503])(
    'preserves status, business code and retryability for %i',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi
          .fn()
          .mockResolvedValue(
            json(
              { error: { code: 'TEST_ERROR', message: '安全文案', retryable: status === 503 } },
              status,
            ),
          ),
      )
      await expect(createHttpClient().request('/api/me')).rejects.toMatchObject({
        status,
        code: 'TEST_ERROR',
        retryable: status === 503,
      })
    },
  )
  it('does not expose raw network exception or submitted secrets', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('PRIVATE_TOKEN PRIVATE_KEY')))
    const error = await createHttpClient()
      .request('/api/me')
      .catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    if (!(error instanceof ApiError)) throw new Error('Expected safe API error')
    expect(error.code).toBe('NETWORK_ERROR')
    expect(String(error)).not.toContain('PRIVATE')
  })
  it.each([200, 503])('rejects malformed JSON safely at status %i', async (status) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('PRIVATE_INVALID_BODY', { status })),
    )
    const error = await createHttpClient()
      .request('/api/me')
      .catch((e) => e)
    expect(error).toMatchObject({ status, code: 'INVALID_RESPONSE' })
    expect(String(error)).not.toContain('PRIVATE')
  })
  it('times out both response acquisition and body parsing without retry', async () => {
    vi.useFakeTimers()
    const fetch = vi
      .fn()
      .mockImplementation(
        (_url, options: RequestInit) =>
          new Promise((_resolve, reject) =>
            options.signal!.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            ),
          ),
      )
    vi.stubGlobal('fetch', fetch)
    const result = createHttpClient({ timeoutMs: 30 })
      .request('/api/me')
      .catch((e) => e)
    await vi.advanceTimersByTimeAsync(31)
    expect(await result).toMatchObject({ code: 'TIMEOUT', status: 0 })
    expect(fetch).toHaveBeenCalledTimes(1)
  })
  it('rejects credential-bearing base URLs before sending anything', () => {
    expect(() => createHttpClient({ baseUrl: 'https://secret@api.example.test' })).toThrow()
  })
  it('keeps the timeout active while receiving a slow JSON body', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url, options: RequestInit) =>
        Promise.resolve({
          status: 200,
          ok: true,
          json: () =>
            new Promise((_resolve, reject) =>
              options.signal!.addEventListener('abort', () =>
                reject(new DOMException('aborted', 'AbortError')),
              ),
            ),
        }),
      ),
    )
    const result = createHttpClient({ timeoutMs: 30 })
      .request('/api/me')
      .catch((e) => e)
    await vi.advanceTimersByTimeAsync(31)
    expect(await result).toMatchObject({ status: 0, code: 'TIMEOUT' })
  })
})

it.each([
  ['60', 60],
  ['0', 0],
  ['0007', 7],
  ['-1', undefined],
  ['1.5', undefined],
  ['1e3', undefined],
  ['9007199254740992', undefined],
  ['Wed, 21 Oct 2015 07:28:00 GMT', undefined],
] as const)(
  'accepts Retry-After %s only as safe nonnegative integer seconds',
  async (value, expected) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('unusable error envelope', {
          status: 429,
          headers: { 'Retry-After': value },
        }),
      ),
    )
    await expect(createHttpClient().request('/api/me')).rejects.toMatchObject({
      status: 429,
      retryAfter: expected,
    })
  },
)

it.each(['/api/verification-codes/extra', '/api/password-resets?grant=unsafe'])(
  'rejects non-exact static credential route %s',
  async (path) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(createHttpClient().request(path)).rejects.toMatchObject({
      code: 'INVALID_REQUEST',
    })
    expect(fetch).not.toHaveBeenCalled()
  },
)
