import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SESSION_KEY, useIdentityStore } from '../src/stores/identity'
import { account, created, fail, json, me, recovered, session } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  localStorage.clear()
})
afterEach(() => {
  vi.unstubAllGlobals()
})
it('creates identity, persists only token and returns the one-time key to the caller', async () => {
  const fetch = vi.fn().mockResolvedValue(json(created))
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  expect(await store.create('旅人')).toBe(created.recovery_key)
  expect(store.authenticated).toBe(true)
  expect(store.account).toEqual(account)
  expect(sessionStorage.getItem(SESSION_KEY)).toBe(session.token)
  expect(JSON.stringify(store.$state)).not.toContain(created.recovery_key)
  expect(JSON.stringify(sessionStorage)).not.toContain(created.recovery_key)
  expect(localStorage.length).toBe(0)
})
it('recovers the existing account with the exact backend request', async () => {
  const fetch = vi.fn().mockResolvedValue(json(recovered))
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  await store.recover('recovery-secret')
  expect(store.account).toEqual(account)
  expect(fetch.mock.calls[0]![0]).toBe('/api/sessions/recover')
  expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({ recovery_key: 'recovery-secret' })
  expect(JSON.stringify(store.$state)).not.toContain('recovery-secret')
})
it('startup validates a saved token through me and never locally expires it', async () => {
  sessionStorage.setItem(SESSION_KEY, session.token)
  const fetch = vi
    .fn()
    .mockResolvedValue(json({ ...me, session: { expires_at: '2000-01-01T00:00:00Z' } }))
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  await store.initialize()
  await store.initialize()
  expect(store.authenticated).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(new Headers(fetch.mock.calls[0]![1].headers).get('authorization')).toBe(
    `Bearer ${session.token}`,
  )
})
it('startup without token sends no request', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await useIdentityStore().initialize()
  expect(fetch).not.toHaveBeenCalled()
})
it('401 clears the saved token and account', async () => {
  sessionStorage.setItem(SESSION_KEY, session.token)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fail(401)))
  const store = useIdentityStore()
  await store.initialize()
  expect(sessionStorage.getItem(SESSION_KEY)).toBeNull()
  expect(store.account).toBeNull()
  expect(store.error?.code).toBe('UNAUTHENTICATED')
})
it('network failure keeps the token unverified and allows an explicit retry', async () => {
  sessionStorage.setItem(SESSION_KEY, session.token)
  const fetch = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(json(me))
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  await store.initialize()
  expect(store.authenticated).toBe(false)
  expect(store.token).toBe(session.token)
  expect(sessionStorage.getItem(SESSION_KEY)).toBe(session.token)
  await store.verifySession()
  expect(store.authenticated).toBe(true)
})
it('logout 204 clears local identity', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json(created))
      .mockResolvedValueOnce(new Response(null, { status: 204 })),
  )
  const store = useIdentityStore()
  await store.create('旅人')
  await store.logout()
  expect(store.account).toBeNull()
  expect(store.token).toBeNull()
  expect(sessionStorage.length).toBe(0)
})
it('failed logout retains identity and says server revocation is not confirmed', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(json(created)).mockRejectedValueOnce(new Error('offline')),
  )
  const store = useIdentityStore()
  await store.create('旅人')
  await store.logout()
  expect(store.authenticated).toBe(true)
  expect(store.error?.message).toContain('撤销尚未确认')
  expect(sessionStorage.getItem(SESSION_KEY)).toBe(session.token)
})
it('unknown create result never automatically retries', async () => {
  const fetch = vi.fn().mockRejectedValue(new Error('offline'))
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  expect(await store.create('旅人')).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(store.error?.message).toContain('可能已创建')
})
it('malformed successful payload cannot authenticate or persist anything', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(json({ account, session: { expires_at: session.expires_at } })),
  )
  const store = useIdentityStore()
  await store.create('旅人')
  expect(store.authenticated).toBe(false)
  expect(sessionStorage.length).toBe(0)
  expect(store.error?.code).toBe('INVALID_RESPONSE')
})
it('blocked sessionStorage keeps current identity in memory with a notice', async () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(created)))
  const store = useIdentityStore()
  expect(await store.create('旅人')).toBe(created.recovery_key)
  expect(store.authenticated).toBe(true)
  expect(store.storageWarning).toBeTruthy()
})
it('expired or revoked token during logout clears local state rather than claiming a network error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(json(created)).mockResolvedValueOnce(fail(401)),
  )
  const store = useIdentityStore()
  await store.create('旅人')
  await store.logout()
  expect(store.authenticated).toBe(false)
  expect(sessionStorage.length).toBe(0)
  expect(store.error?.code).toBe('UNAUTHENTICATED')
})
it('restoration 503 retains the session and never retries automatically', async () => {
  sessionStorage.setItem(SESSION_KEY, session.token)
  const fetch = vi.fn().mockResolvedValue(fail(503))
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  await store.initialize()
  expect(store.token).toBe(session.token)
  expect(store.authenticated).toBe(false)
  expect(fetch).toHaveBeenCalledTimes(1)
})
it('serializes identity mutations and does not submit another request while creating', async () => {
  let resolve!: (value: Response) => void
  const fetch = vi.fn().mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done
      }),
  )
  vi.stubGlobal('fetch', fetch)
  const store = useIdentityStore()
  const first = store.create('旅人')
  expect(await store.create('另一个名字')).toBeNull()
  await store.recover('another-key')
  expect(fetch).toHaveBeenCalledTimes(1)
  resolve(json(created))
  expect(await first).toBe(created.recovery_key)
})
