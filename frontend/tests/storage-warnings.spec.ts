import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useIdentityStore } from '../src/stores/identity'
import { fail, json, loginInput, me, noContent, registerInput, resetInput } from './fixtures'

const token = 'twoworlds.session.token'
const reminder = 'twoworlds.recovery.pending.v1.account_fixture'
const legacy = 'twoworlds.recovery.pending'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('ignores old browser state and keeps it intact for the migration task', async () => {
  sessionStorage.setItem(token, 'LEGACY_SESSION_TEST')
  sessionStorage.setItem(legacy, '1')
  localStorage.setItem(reminder, '{"unknown":"LEGACY_TEST"}')
  localStorage.setItem('unrelated', 'leave intact')
  const fetch = vi.fn().mockResolvedValue(fail(401))
  vi.stubGlobal('fetch', fetch)
  await useIdentityStore().initialize()
  expect(fetch.mock.calls[0]![0]).toBe('/api/me')
  expect(new Headers(fetch.mock.calls[0]![1].headers).has('Authorization')).toBe(false)
  expect(useIdentityStore().authenticated).toBe(false)
  expect(sessionStorage.getItem(token)).toBe('LEGACY_SESSION_TEST')
  expect(sessionStorage.getItem(legacy)).toBe('1')
  expect(localStorage.getItem(reminder)).toBe('{"unknown":"LEGACY_TEST"}')
  expect(localStorage.getItem('unrelated')).toBe('leave intact')
})

it.each(['register', 'login', 'resetPassword', 'logout'] as const)(
  '%s works without reading or writing browser storage or cookie contents',
  async (operation) => {
    const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw Error('Storage unavailable')
    })
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw Error('Storage unavailable')
    })
    const remove = vi.spyOn(Storage.prototype, 'removeItem')
    const clear = vi.spyOn(Storage.prototype, 'clear')
    const cookie = vi.spyOn(document, 'cookie', 'get').mockImplementation(() => {
      throw Error('Cookie cannot be read')
    })
    const store = useIdentityStore()
    const fetch = vi
      .fn()
      .mockResolvedValue(operation === 'register' || operation === 'login' ? json(me) : noContent())
    vi.stubGlobal('fetch', fetch)
    if (operation === 'register') expect(await store.register(registerInput)).toBe(true)
    if (operation === 'login') expect(await store.login(loginInput)).toBe(true)
    if (operation === 'resetPassword') expect(await store.resetPassword(resetInput)).toBe(true)
    if (operation === 'logout') expect(await store.logout()).toBe(true)
    expect(read).not.toHaveBeenCalled()
    expect(write).not.toHaveBeenCalled()
    expect(remove).not.toHaveBeenCalled()
    expect(clear).not.toHaveBeenCalled()
    expect(cookie).not.toHaveBeenCalled()
    expect(JSON.stringify(store.$state)).not.toMatch(/123456|example-password/)
    expect(location.href).not.toMatch(/123456|example-password/)
  },
)

it('verification-code request stores neither email nor delivery response in browser data', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(json({ status: 'accepted', code: 'PRIVATE_CODE' }, 202)),
  )
  const store = useIdentityStore()
  expect(await store.requestVerificationCode(me.account.email, 'reset')).toBe(true)
  expect(JSON.stringify(store.$state)).not.toContain('PRIVATE')
  expect(localStorage.length + sessionStorage.length).toBe(0)
})
