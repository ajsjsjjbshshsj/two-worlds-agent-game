import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useIdentityStore, SESSION_KEY } from '../src/stores/identity'
import {
  json,
  pendingA as a,
  pendingB as b,
  pendingC as c,
  pendingMetadata as record,
} from './fixtures'

const prefix = 'twoworlds.recovery.pending.v1.'
beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  localStorage.clear()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

it('creation stores only per-account whitelisted metadata, never credentials', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(a)))
  const store = useIdentityStore()
  expect(await store.create(a.account.display_name)).toBe(a.recovery_key)
  const raw = JSON.parse(localStorage.getItem(prefix + a.account.id) ?? 'null')
  expect(raw).toEqual({
    account_id: a.account.id,
    display_name: a.account.display_name,
    created_at: expect.any(String),
    pending: true,
  })
  expect(Number.isFinite(Date.parse(raw.created_at))).toBe(true)
  expect(store.$state).toMatchObject({ pendingRecoveries: [raw] })
  for (const secret of [a.recovery_key, a.session.token])
    expect(JSON.stringify(localStorage)).not.toContain(secret)
  expect(JSON.stringify(sessionStorage)).not.toContain(a.recovery_key)
  expect(sessionStorage.getItem(SESSION_KEY)).toBe(a.session.token)
})
it('recovering B does not clear A, and recovering A clears only A', async () => {
  localStorage.setItem(prefix + a.account.id, JSON.stringify(record(a.account)))
  localStorage.setItem(prefix + b.account.id, JSON.stringify(record(b.account)))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(b)).mockResolvedValueOnce(json(a)))
  const store = useIdentityStore()
  await store.recover(b.recovery_key)
  expect(localStorage.getItem(prefix + a.account.id)).toBe(JSON.stringify(record(a.account)))
  expect(localStorage.getItem(prefix + b.account.id)).toBeNull()
  expect(store.$state).toMatchObject({ pendingRecoveries: [record(a.account)] })
  localStorage.setItem(prefix + c.account.id, JSON.stringify(record(c.account)))
  await store.recover(a.recovery_key)
  expect(localStorage.getItem(prefix + a.account.id)).toBeNull()
  expect(localStorage.getItem(prefix + c.account.id)).toBe(JSON.stringify(record(c.account)))
})
it('creating A B C then confirming C preserves A and B; confirming B affects only B', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json(a))
      .mockResolvedValueOnce(json(b))
      .mockResolvedValueOnce(json(c)),
  )
  const store = useIdentityStore()
  for (const item of [a, b, c]) await store.create(item.account.display_name)
  store.confirmRecoveryKeySaved(c.account.id)
  expect(localStorage.getItem(prefix + a.account.id)).not.toBeNull()
  expect(localStorage.getItem(prefix + b.account.id)).not.toBeNull()
  expect(localStorage.getItem(prefix + c.account.id)).toBeNull()
  store.confirmRecoveryKeySaved(b.account.id)
  expect(localStorage.getItem(prefix + a.account.id)).not.toBeNull()
  expect(localStorage.getItem(prefix + b.account.id)).toBeNull()
})
it('logout preserves pending across a new store with no session', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json(a))
      .mockResolvedValueOnce(new Response(null, { status: 204 })),
  )
  const store = useIdentityStore()
  await store.create(a.account.display_name)
  await store.logout()
  expect(store.account).toBeNull()
  expect(sessionStorage.getItem(SESSION_KEY)).toBeNull()
  const raw = localStorage.getItem(prefix + a.account.id)
  expect(raw).not.toBeNull()
  setActivePinia(createPinia())
  const reopened = useIdentityStore()
  await reopened.initialize()
  expect(reopened.$state).toMatchObject({ pendingRecoveries: [JSON.parse(raw!)] })
})
it('blocked localStorage keeps the record in memory and explicitly warns', async () => {
  const original = Storage.prototype.setItem
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
    this: Storage,
    key: string,
    value: string,
  ) {
    if (this === localStorage) throw new Error('blocked')
    original.call(this, key, value)
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(a)))
  const store = useIdentityStore()
  await store.create(a.account.display_name)
  expect(store.$state).toMatchObject({
    pendingRecoveries: [expect.objectContaining({ account_id: a.account.id })],
  })
  expect(store.pendingStorageWarning).toBeTruthy()
})
it('rejects malformed or credential-bearing metadata without deleting stored data', async () => {
  localStorage.setItem(
    prefix + a.account.id,
    JSON.stringify({ ...record(), recovery_key: 'PRIVATE_SECRET' }),
  )
  localStorage.setItem(prefix + b.account.id, JSON.stringify({ ...record(a.account) }))
  localStorage.setItem(prefix + c.account.id, '{bad json')
  const store = useIdentityStore()
  await store.initialize()
  expect(store.$state).toMatchObject({ pendingRecoveries: [] })
  expect(JSON.stringify(store.$state)).not.toContain('PRIVATE_SECRET')
  expect(store.pendingStorageWarning).toBeTruthy()
  expect(localStorage.length).toBe(3)
})
it('localStorage read failure does not erase already-created memory reminders', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(a)).mockResolvedValueOnce(json(b)))
  const store = useIdentityStore()
  await store.create(a.account.display_name)
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new Error('blocked')
  })
  await store.create(b.account.display_name)
  expect(store.pendingRecoveries.map((record) => record.account_id)).toEqual([
    a.account.id,
    b.account.id,
  ])
  expect(store.pendingStorageWarning).toBeTruthy()
})
it('failed removal warns without erasing other identities or touching their persisted records', async () => {
  for (const item of [a, b])
    localStorage.setItem(prefix + item.account.id, JSON.stringify(record(item.account)))
  const store = useIdentityStore()
  await store.initialize()
  const original = Storage.prototype.removeItem
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function (
    this: Storage,
    key: string,
  ) {
    if (this === localStorage) throw new Error('blocked')
    original.call(this, key)
  })
  store.confirmRecoveryKeySaved(a.account.id)
  expect(store.pendingRecoveries).toEqual([record(b.account)])
  expect(store.pendingStorageWarning).toContain('重开后可能再次出现')
  expect(localStorage.getItem(prefix + b.account.id)).toBe(JSON.stringify(record(b.account)))
})
