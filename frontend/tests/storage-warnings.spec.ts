import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { useIdentityStore, PENDING_RECOVERY_PREFIX as prefix } from '../src/stores/identity'
import { json, pendingA as a, pendingB as b, pendingMetadata } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

it('read recovery clears only read failure, retaining write and invalid warnings', async () => {
  localStorage.setItem(prefix + 'broken', '{invalid')
  const store = useIdentityStore()
  await store.initialize()
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw Error('blocked')
  })
  store.loadPendingRecoveries()
  expect(store.pendingStorageIssues).toMatchObject({ read: true, invalid: true })
  get.mockRestore()
  store.loadPendingRecoveries()
  expect(store.pendingStorageIssues).toMatchObject({ read: false, invalid: true })
  expect(localStorage.getItem(prefix + 'broken')).toBe('{invalid')
})
it('a later successful write clears write only; successful reads cannot clear it', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(a)).mockResolvedValueOnce(json(b)))
  const original = Storage.prototype.setItem
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
    this: Storage,
    k,
    v,
  ) {
    if (this === localStorage) throw Error('blocked')
    original.call(this, k, v)
  })
  const store = useIdentityStore()
  await store.create('A')
  expect(store.pendingStorageIssues.write).toBe(true)
  store.loadPendingRecoveries()
  expect(store.pendingStorageIssues.write).toBe(true)
  set.mockRestore()
  await store.create('B')
  expect(store.pendingStorageIssues.write).toBe(false)
  expect(store.pendingRecoveries).toHaveLength(2)
})
it('failed remove survives reads and clears only after successful retry', async () => {
  localStorage.setItem(prefix + a.account.id, JSON.stringify(pendingMetadata(a.account)))
  const store = useIdentityStore()
  await store.initialize()
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw Error('blocked')
  })
  store.confirmRecoveryKeySaved(a.account.id)
  store.loadPendingRecoveries()
  expect(store.pendingStorageIssues.remove).toBe(true)
  remove.mockRestore()
  store.confirmRecoveryKeySaved(a.account.id)
  expect(store.pendingStorageIssues.remove).toBe(false)
  expect(store.pendingStorageWarning).toBeNull()
})
it('cannot overwrite or delete an unrecognized record even at the active account key', async () => {
  const raw = '{"future_format":true}'
  localStorage.setItem(prefix + a.account.id, raw)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(a)))
  const store = useIdentityStore()
  await store.create('A')
  expect(localStorage.getItem(prefix + a.account.id)).toBe(raw)
  expect(store.pendingStorageIssues.invalid).toBe(true)
  store.confirmRecoveryKeySaved(a.account.id)
  expect(localStorage.getItem(prefix + a.account.id)).toBe(raw)
  expect(JSON.stringify(localStorage)).not.toContain(a.recovery_key)
  expect(JSON.stringify(localStorage)).not.toContain(a.session.token)
})
it('successful write does not clear an independent read failure or invalid metadata warning', async () => {
  localStorage.setItem(prefix + 'broken', '{invalid')
  const store = useIdentityStore()
  await store.initialize()
  vi.spyOn(Storage.prototype, 'key').mockImplementation(() => {
    throw Error('blocked enumeration')
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(a)))
  await store.create('A')
  expect(store.pendingStorageIssues).toEqual({
    read: true,
    write: false,
    remove: false,
    invalid: true,
  })
  expect(localStorage.getItem(prefix + a.account.id)).not.toBeNull()
  expect(store.pendingStorageWarning).toContain('无法读取')
  expect(store.pendingStorageWarning).toContain('格式无效')
})
it('successful remove clears remove failure without clearing independent write or invalid issues', async () => {
  localStorage.setItem(prefix + 'broken', '{invalid')
  localStorage.setItem(prefix + a.account.id, JSON.stringify(pendingMetadata(a.account)))
  const store = useIdentityStore()
  await store.initialize()
  const original = Storage.prototype.setItem
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, k, v) {
    if (this === localStorage) throw Error('blocked write')
    original.call(this, k, v)
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(b)))
  await store.create('B')
  store.confirmRecoveryKeySaved(a.account.id)
  expect(store.pendingStorageIssues).toEqual({
    read: false,
    write: true,
    remove: false,
    invalid: true,
  })
  expect(localStorage.getItem(prefix + 'broken')).toBe('{invalid')
})
