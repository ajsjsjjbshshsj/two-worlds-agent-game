import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useIdentityStore } from '../src/stores/identity'
import {
  account,
  deferred,
  fail,
  json,
  loginInput,
  me,
  noContent,
  other,
  registerInput,
  resetInput,
} from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function network(...responses: (Response | Error | Promise<Response>)[]) {
  const fetch = vi.fn()
  for (const response of responses) {
    if (response instanceof Error) fetch.mockRejectedValueOnce(response)
    else fetch.mockImplementationOnce(() => Promise.resolve(response))
  }
  vi.stubGlobal('fetch', fetch)
  return fetch
}

it('registers with an exact normalized payload and retains only account and expiry', async () => {
  const fetch = network(
    json({
      ...me,
      session: { ...me.session, token: 'PRIVATE_TOKEN' },
      recovery_key: 'PRIVATE_KEY',
    }),
  )
  const store = useIdentityStore()
  expect(
    await store.register({
      ...registerInput,
      email: ' PLAYER@Example.Test ',
      display_name: ' 旅人 ',
    }),
  ).toBe(true)
  expect(fetch.mock.calls[0]![0]).toBe('/api/accounts')
  expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual(registerInput)
  expect(fetch.mock.calls[0]![1].credentials).toBe('include')
  expect(store.account).toEqual(account)
  expect(store.expiresAt).toBe(me.session.expires_at)
  for (const state of [store.$state, localStorage, sessionStorage])
    expect(JSON.stringify(state)).not.toMatch(/PRIVATE|example-password|123456/)
})

it('logs into an existing account with Cookie issuance and an exact body', async () => {
  const fetch = network(json(me))
  expect(await useIdentityStore().login(loginInput)).toBe(true)
  expect(fetch.mock.calls[0]![0]).toBe('/api/sessions')
  expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual(loginInput)
  expect(useIdentityStore().authenticated).toBe(true)
})

it('verifies exactly once when startup calls overlap and trusts the server on expiry', async () => {
  const next = deferred<Response>()
  const fetch = network(next.promise)
  const store = useIdentityStore()
  const calls = [store.initialize(), store.initialize(), store.verifySession()]
  expect(store.initializing).toBe(true)
  next.resolve(json({ ...me, session: { expires_at: '2000-01-01T00:00:00Z' } }))
  await Promise.all(calls)
  await store.initialize()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0]![0]).toBe('/api/me')
  expect(store.authenticated).toBe(true)
})

it('startup always asks the server, and missing or expired Cookie yields login', async () => {
  const fetch = network(fail(401))
  const store = useIdentityStore()
  await store.initialize()
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me'])
  expect(store.initialized).toBe(true)
  expect(store.authenticated).toBe(false)
  expect(store.verificationUnavailable).toBe(false)
})

it.each([new TypeError('PRIVATE_STACK'), fail(503)])(
  'startup failure leaves the session unconfirmed until a deliberate retry',
  async (fault) => {
    const fetch = network(fault, json(me))
    const store = useIdentityStore()
    await store.initialize()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(store.verificationUnavailable).toBe(true)
    expect(store.error?.message).toContain('暂时无法验证')
    expect(store.authenticated).toBe(false)
    await store.verifySession()
    expect(store.authenticated).toBe(true)
  },
)

it('a login error preserves an existing account and uses unified wording', async () => {
  network(json(me), fail(401, 'INVALID_CREDENTIALS'))
  const store = useIdentityStore()
  await store.initialize()
  const generation = store.sessionGeneration
  expect(await store.login({ ...loginInput, email: other.account.email })).toBe(false)
  expect(store.account).toEqual(account)
  expect(store.sessionGeneration).toBe(generation)
  expect(store.error?.message).toBe('邮箱或密码错误。')
})

it.each([noContent(), fail(401)])(
  'confirmed logout or already revoked session clears local identity',
  async (response) => {
    const fetch = network(json(me), response)
    const store = useIdentityStore()
    await store.initialize()
    const generation = store.sessionGeneration
    expect(await store.logout()).toBe(true)
    expect(fetch.mock.calls[1]![0]).toBe('/api/sessions/current')
    expect(fetch.mock.calls[1]![1]).toMatchObject({ method: 'DELETE', credentials: 'include' })
    expect(store.account).toBeNull()
    expect(store.expiresAt).toBeNull()
    expect(store.sessionGeneration).toBeGreaterThan(generation)
  },
)

it('failed logout retains identity and explains that revocation is unconfirmed', async () => {
  network(json(me), new TypeError('PRIVATE'))
  const store = useIdentityStore()
  await store.initialize()
  const generation = store.sessionGeneration
  expect(await store.logout()).toBe(false)
  expect(store.account).toEqual(account)
  expect(store.sessionGeneration).toBe(generation)
  expect(store.error?.message).toContain('撤销尚未确认')
  expect(store.error?.message).not.toContain('PRIVATE')
})

it('logout timeout does not claim server-side revocation', async () => {
  vi.useFakeTimers()
  const fetch = network(json(me))
  fetch.mockImplementationOnce(
    (_url, options: RequestInit) =>
      new Promise((_resolve, reject) => {
        options.signal?.addEventListener('abort', () =>
          reject(new DOMException('aborted', 'AbortError')),
        )
      }),
  )
  const store = useIdentityStore()
  await store.initialize()
  const pending = store.logout()
  await vi.advanceTimersByTimeAsync(15001)
  expect(await pending).toBe(false)
  expect(store.error?.code).toBe('TIMEOUT')
  expect(store.account).toEqual(account)
})

it.each(['register', 'login'] as const)(
  '%s uncertainty checks me once and never resends credentials',
  async (kind) => {
    const fetch = network(new TypeError('PRIVATE'), json(me))
    const store = useIdentityStore()
    expect(await store[kind](registerInput)).toBe(true)
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      kind === 'register' ? '/api/accounts' : '/api/sessions',
      '/api/me',
    ])
    expect(store.account).toEqual(account)
  },
)

it('an unconfirmed login does not invent a session when me says 401', async () => {
  const fetch = network(new TypeError('PRIVATE'), fail(401))
  const store = useIdentityStore()
  expect(await store.login(loginInput)).toBe(false)
  expect(store.authenticated).toBe(false)
  expect(store.error?.message).toContain('尚未确认')
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('malformed success cannot authenticate or persist anything', async () => {
  network(
    json({ account: { ...account, email: 'INVALID' }, session: { expires_at: 'bad' } }),
    fail(401),
  )
  const store = useIdentityStore()
  expect(await store.register(registerInput)).toBe(false)
  expect(store.authenticated).toBe(false)
  expect(localStorage.length + sessionStorage.length).toBe(0)
})

it('prevents duplicate and competing account and code requests while a write is outstanding', async () => {
  const response = deferred<Response>()
  const fetch = network(response.promise)
  const store = useIdentityStore()
  const pending = store.register(registerInput)
  expect(store.busy).toBe(true)
  expect(await store.login(loginInput)).toBe(false)
  expect(await store.resetPassword(resetInput)).toBe(false)
  expect(await store.requestVerificationCode(account.email, 'register')).toBe(false)
  expect(fetch).toHaveBeenCalledTimes(1)
  response.resolve(json(me))
  expect(await pending).toBe(true)
  expect(store.busy).toBe(false)
})

it.each(['register', 'reset'] as const)(
  'requests only email and %s purpose with neutral accepted response',
  async (purpose) => {
    const fetch = network(json({ status: 'accepted' }, 202))
    expect(await useIdentityStore().requestVerificationCode(' PLAYER@EXAMPLE.TEST ', purpose)).toBe(
      true,
    )
    expect(fetch.mock.calls[0]![0]).toBe('/api/verification-codes')
    expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({ email: account.email, purpose })
  },
)

it('requests verification once when the network result is uncertain', async () => {
  const fetch = network(new TypeError('PRIVATE'))
  const store = useIdentityStore()
  expect(await store.requestVerificationCode(account.email, 'reset')).toBe(false)
  expect(store.error?.message).toContain('申请结果尚未确认')
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('reset success uses the exact reset payload and invalidates the former generation', async () => {
  const fetch = network(json(me), noContent())
  const store = useIdentityStore()
  await store.initialize()
  const generation = store.sessionGeneration
  expect(await store.resetPassword(resetInput)).toBe(true)
  expect(fetch.mock.calls[1]![0]).toBe('/api/password-resets')
  expect(JSON.parse(fetch.mock.calls[1]![1].body)).toEqual(resetInput)
  expect(store.authenticated).toBe(false)
  expect(store.sessionGeneration).toBeGreaterThan(generation)
})

it('reset uncertainty discards former private state, leaves result unknown and does not retry', async () => {
  const fetch = network(json(me), new TypeError('PRIVATE'))
  const store = useIdentityStore()
  await store.initialize()
  expect(await store.resetPassword(resetInput)).toBe(false)
  expect(store.authenticated).toBe(false)
  expect(store.error?.message).toContain('密码重置结果尚未确认')
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('late me response cannot revive an expired session', async () => {
  const next = deferred<Response>()
  network(json(me), next.promise)
  const store = useIdentityStore()
  await store.initialize()
  const pending = store.verifySession()
  store.expireSession()
  next.resolve(json(me))
  await pending
  expect(store.authenticated).toBe(false)
})

it('a new account rotates the generation and an old 401 cannot expire it', async () => {
  network(json(me), json(other))
  const store = useIdentityStore()
  await store.initialize()
  const old = store.sessionGeneration
  expect(await store.login({ ...loginInput, email: other.account.email })).toBe(true)
  store.expireSession(old)
  expect(store.sessionGeneration).toBeGreaterThan(old)
  expect(store.account).toEqual(other.account)
})

it('me 503 leaves the last verified account available for retry', async () => {
  network(json(me), fail(503))
  const store = useIdentityStore()
  await store.initialize()
  await store.verifySession()
  expect(store.account).toEqual(account)
  expect(store.verificationUnavailable).toBe(true)
})

it('an unexpected account in the login body requires confirmation via me', async () => {
  const fetch = network(json(other), fail(401))
  const store = useIdentityStore()
  expect(await store.login(loginInput)).toBe(false)
  expect(store.account).toBeNull()
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/sessions', '/api/me'])
})

it('an already confirmed account alone cannot prove a timed-out login succeeded', async () => {
  network(json(me), new TypeError('PRIVATE'), json(me))
  const store = useIdentityStore()
  await store.initialize()
  const current = store.sessionGeneration
  expect(await store.login(loginInput)).toBe(false)
  expect(store.error?.message).toContain('登录结果尚未确认')
  expect(store.sessionGeneration).toBe(current)
})

it('an unexpected success status cannot confirm logout or reset', async () => {
  network(json(me), json({ accepted: true }))
  const store = useIdentityStore()
  await store.initialize()
  expect(await store.logout()).toBe(false)
  expect(store.error?.message).toContain('撤销尚未确认')
  expect(store.authenticated).toBe(true)
})
