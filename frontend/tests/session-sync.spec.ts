import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { createAppRouter } from '../src/router'
import { protectedImage } from '../src/services/media'
import { pairApi } from '../src/services/pairs'
import { createSessionSync, SESSION_REVISION } from '../src/services/session-sync'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { usePairsStore } from '../src/stores/pairs'
import {
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
import { game as gameFixture } from './game-fixture'
import { pairA, pairB } from './resource-fixtures'

class TestChannel extends EventTarget {
  static channels = new Set<TestChannel>()
  static posts: unknown[] = []
  static deliver = true
  constructor(public name: string) {
    super()
    TestChannel.channels.add(this)
  }
  postMessage(data: unknown) {
    TestChannel.posts.push(data)
    if (TestChannel.deliver) {
      for (const channel of TestChannel.channels) {
        if (channel !== this && channel.name === this.name)
          channel.dispatchEvent(new MessageEvent('message', { data }))
      }
    }
  }
  close() {
    TestChannel.channels.delete(this)
  }
}

const cleanups: (() => void)[] = []
beforeEach(() => {
  vi.stubGlobal('BroadcastChannel', TestChannel)
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  localStorage.clear()
  TestChannel.posts = []
  TestChannel.deliver = true
})
afterEach(() => {
  cleanups
    .splice(0)
    .reverse()
    .forEach((cleanup) => cleanup())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function tab(start = me) {
  const pinia = createPinia()
  cleanups.push(() => disposePinia(pinia))
  setActivePinia(pinia)
  const identity = useIdentityStore()
  identity.enableSessionSync()
  const fetch = vi.fn().mockResolvedValueOnce(json(start))
  vi.stubGlobal('fetch', fetch)
  await identity.initialize()
  const peer = createSessionSync(() => {})
  cleanups.push(peer.close)
  return { pinia, identity, fetch, peer }
}

it('pauses private UI at peer start, ignores old responses and reloads the verified account’s rooms', async () => {
  const { pinia, identity, fetch, peer } = await tab()
  const router = createAppRouter(createMemoryHistory(), pinia)
  fetch.mockResolvedValueOnce(json([pairA]))
  const w = mount(App, { global: { plugins: [pinia, router] } })
  cleanups.push(() => w.unmount())
  await router.push('/pairs')
  await flushPromises()
  expect(w.text()).toContain('旅人')
  expect(w.text()).toContain(pairA.id)
  const old = deferred<Response>()
  const next = deferred<Response>()
  fetch.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise)
  const oldLoad = usePairsStore(pinia).load()
  const generation = identity.sessionGeneration
  const end = peer.begin()
  await flushPromises()
  expect(identity.authenticated).toBe(false)
  expect(identity.sessionGeneration).toBeGreaterThan(generation)
  expect(w.text()).not.toContain('旅人')
  expect(w.text()).not.toContain(pairA.id)
  expect(w.text()).toContain('私人内容暂时隐藏')
  expect(fetch.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(1)
  end()
  old.resolve(json([pairA]))
  await oldLoad
  expect(usePairsStore(pinia).pairs).toEqual([])
  fetch.mockResolvedValueOnce(json([{ ...pairB, id: 'pair_beta' }]))
  next.resolve(json(other))
  await flushPromises()
  expect(w.text()).toContain(other.account.display_name)
  expect(w.text()).toContain('pair_beta')
  expect(w.text()).not.toContain(pairA.id)
  expect(fetch.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(2)
})

it('a verified peer logout clears identity and old 401s cannot expire a later account', async () => {
  const { identity, fetch, peer } = await tab()
  const old = deferred<Response>()
  fetch
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce(fail(401))
    .mockResolvedValueOnce(json(other))
  const request = pairApi.list().catch((error) => error)
  const end = peer.begin()
  end()
  await flushPromises()
  expect(identity.account).toBeNull()
  peer.begin()()
  await flushPromises()
  old.resolve(fail(401))
  expect(await request).toMatchObject({ code: 'SESSION_UNCONFIRMED' })
  expect(identity.account).toEqual(other.account)
  expect(identity.authenticated).toBe(true)
})

it('reads the non-secret fence even before asynchronous broadcast delivery', async () => {
  const { identity, fetch, peer } = await tab()
  TestChannel.deliver = false
  const pending = deferred<Response>()
  fetch.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(json(other))
  const previous = pairApi.list().catch((error) => error)
  const end = peer.begin()
  // A response using the new Cookie must never be delivered under the old account label,
  // even if the browsing task for the storage or broadcast event has not run.
  pending.resolve(json([pairB]))
  expect(await previous).toMatchObject({ code: 'SESSION_UNCONFIRMED' })
  expect(identity.authenticated).toBe(false)
  expect(fetch).toHaveBeenCalledTimes(2)
  end()
  window.dispatchEvent(new StorageEvent('storage', { key: SESSION_REVISION }))
  await flushPromises()
  expect(identity.account).toEqual(other.account)
  expect(fetch).toHaveBeenCalledTimes(3)
})

it('an old image streamed through a context switch never becomes a Blob URL', async () => {
  const { identity, fetch, peer } = await tab()
  const response = deferred<Response>()
  fetch.mockReturnValueOnce(response.promise).mockResolvedValueOnce(json(other))
  const url = vi.fn(() => 'blob:late')
  const OriginalURL = URL
  vi.stubGlobal(
    'URL',
    class extends OriginalURL {
      static createObjectURL = url
    },
  )
  const image = protectedImage('save_one', 'asset_one', new AbortController().signal).catch(
    (e) => e,
  )
  peer.begin()()
  await flushPromises()
  response.resolve(new Response('synthetic', { headers: { 'Content-Type': 'image/png' } }))
  expect(await image).toMatchObject({ code: 'SESSION_UNCONFIRMED' })
  expect(url).not.toHaveBeenCalled()
  expect(identity.account).toEqual(other.account)
})

it('failed revalidation keeps the former account unconfirmed and blocks reads and commands', async () => {
  const { pinia, identity, fetch, peer } = await tab()
  const game = useGameStore(pinia)
  fetch.mockResolvedValueOnce(json(gameFixture())).mockResolvedValueOnce(fail(503))
  await game.load('save_one')
  expect(game.snapshot).toBeTruthy()
  peer.begin()()
  await flushPromises()
  expect(identity.account).toEqual(me.account)
  expect(identity.authenticated).toBe(false)
  expect(identity.verificationUnavailable).toBe(true)
  expect(game.snapshot).toBeNull()
  await game.submit('inspect', { target: 'maintenance_log' })
  await expect(pairApi.create()).rejects.toMatchObject({ code: 'SESSION_UNCONFIRMED' })
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    '/api/me',
    '/api/saves/save_one',
    '/api/me',
  ])
})

it('keeps a private destination behind the verification screen when session restore fails', async () => {
  const { pinia, identity, fetch } = await tab()
  const router = createAppRouter(createMemoryHistory(), pinia)
  const pending = deferred<Response>()
  fetch.mockReturnValueOnce(pending.promise)
  window.dispatchEvent(new Event('focus'))
  const w = mount(App, { global: { plugins: [pinia, router] } })
  cleanups.push(() => w.unmount())
  const navigation = router.push('/pairs')
  pending.resolve(fail(503))
  await navigation
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/pairs')
  expect(w.text()).toContain('暂时无法验证身份')
  expect(w.text()).not.toContain(me.account.display_name)
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me', '/api/me'])
  fetch.mockResolvedValueOnce(json(other)).mockResolvedValueOnce(json([pairB]))
  await w.get('button').trigger('click')
  await flushPromises()
  expect(identity.account).toEqual(other.account)
  expect(w.text()).toContain(pairB.id)
})

it('a newer peer change supersedes a pending verification and its old 401', async () => {
  const { identity, fetch, peer } = await tab()
  const stale = deferred<Response>()
  const latest = deferred<Response>()
  fetch
    .mockReturnValueOnce(stale.promise)
    .mockResolvedValueOnce(json(other))
    .mockReturnValueOnce(latest.promise)
  peer.begin()()
  peer.begin()()
  await flushPromises()
  expect(identity.account).toEqual(other.account)
  peer.begin()()
  stale.resolve(fail(401))
  await flushPromises()
  expect(identity.authenticated).toBe(false)
  expect(identity.account).toEqual(other.account)
  latest.resolve(json(me))
  await flushPromises()
  expect(identity.account).toEqual(me.account)
  expect(identity.authenticated).toBe(true)
  expect(fetch.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(4)
})

it('automatically retries a transient foreground identity failure on the game route', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  try {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    vi.stubGlobal('WebSocket', undefined)
    const { pinia, identity, fetch } = await tab()
    const router = createAppRouter(createMemoryHistory(), pinia)
    const w = mount(App, { global: { plugins: [pinia, router] } })
    cleanups.push(() => w.unmount())
    fetch.mockResolvedValueOnce(json(gameFixture()))
    await router.push('/saves/save_one')
    await flushPromises()
    expect(useGameStore(pinia).snapshot?.version).toBe(7)

    fetch.mockResolvedValueOnce(fail(503))
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(w.text()).toContain('暂时无法验证身份')
    expect(useGameStore(pinia).snapshot).toBeNull()
    fetch
      .mockResolvedValueOnce(json(me))
      .mockResolvedValueOnce(json({ ...gameFixture(), version: 9 }))
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(identity.authenticated).toBe(true)
    expect(useGameStore(pinia).snapshot?.version).toBe(9)
    expect(fetch.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(3)
  } finally {
    vi.useRealTimers()
  }
})

it('focus, visibility and pageshow coalesce with no polling or response echo when channel is absent', async () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  const { identity, fetch } = await tab()
  const next = deferred<Response>()
  fetch.mockReturnValueOnce(next.promise)
  window.dispatchEvent(new Event('focus'))
  document.dispatchEvent(new Event('visibilitychange'))
  window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))
  expect(identity.authenticated).toBe(false)
  expect(fetch).toHaveBeenCalledTimes(2)
  next.resolve(json(other))
  await flushPromises()
  expect(identity.account).toEqual(other.account)
  expect(identity.authenticated).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(TestChannel.posts).toEqual([])
})

it('a same-account verification and duplicate notices settle without an echo', async () => {
  const { identity, fetch, peer } = await tab()
  fetch.mockResolvedValueOnce(json(me))
  peer.begin()()
  window.dispatchEvent(new StorageEvent('storage', { key: SESSION_REVISION }))
  await flushPromises()
  expect(identity.authenticated).toBe(true)
  expect(identity.account).toEqual(me.account)
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(TestChannel.posts).toHaveLength(2)
})

it.each(['register', 'login', 'resetPassword', 'logout'] as const)(
  'local %s publishes only opaque coordination metadata before and after the write',
  async (action) => {
    const { identity, fetch } = await tab()
    const next = deferred<Response>()
    fetch
      .mockReturnValueOnce(next.promise)
      .mockResolvedValueOnce(
        action === 'logout' || action === 'resetPassword' ? fail(401) : json(me),
      )
    const pending =
      action === 'register'
        ? identity.register(registerInput)
        : action === 'login'
          ? identity.login(loginInput)
          : action === 'resetPassword'
            ? identity.resetPassword(resetInput)
            : identity.logout()
    expect(identity.authenticated).toBe(false)
    expect(TestChannel.posts).toHaveLength(1)
    expect(TestChannel.posts[0]).toMatchObject({ phase: 'start' })
    next.resolve(action === 'logout' || action === 'resetPassword' ? noContent() : json(me))
    expect(await pending).toBe(true)
    expect(TestChannel.posts).toHaveLength(2)
    expect(TestChannel.posts[1]).toMatchObject({ phase: 'finish' })
    expect(Object.keys(TestChannel.posts[0] as object).sort()).toEqual(['id', 'phase', 'until'])
    expect(JSON.stringify(TestChannel.posts)).not.toMatch(
      /player|example|password|123456|account_fixture/,
    )
    expect(fetch.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(2)
  },
)

it.each(['logout', 'resetPassword'] as const)(
  'uncertain %s sends settlement and keeps the former account hidden if verification fails',
  async (action) => {
    const { identity, fetch } = await tab()
    fetch.mockRejectedValueOnce(new TypeError('lost response')).mockResolvedValueOnce(fail(503))
    expect(
      await (action === 'logout' ? identity.logout() : identity.resetPassword(resetInput)),
    ).toBe(false)
    expect(identity.account).toEqual(me.account)
    expect(identity.authenticated).toBe(false)
    expect(identity.verificationUnavailable).toBe(true)
    expect(TestChannel.posts).toEqual([
      expect.objectContaining({ phase: 'start' }),
      expect.objectContaining({ phase: 'finish' }),
    ])
  },
)
