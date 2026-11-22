import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { registerPwa } from '../src/services/pwa'
import { attachWorker } from '../src/pwa/worker'
import PwaStatus from '../src/components/PwaStatus.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

it('never registers a worker in development', async () => {
  const register = vi.fn()
  vi.stubGlobal('navigator', { serviceWorker: { register } })
  await registerPwa(vi.fn())
  expect(register).not.toHaveBeenCalled()
})

it('registers only in a secure production context and reports waiting without forcing activation', async () => {
  vi.stubEnv('PROD', true)
  vi.stubGlobal('isSecureContext', true)
  const registration = Object.assign(new EventTarget(), { waiting: {}, installing: null })
  const register = vi.fn().mockResolvedValue(registration)
  vi.stubGlobal('navigator', { serviceWorker: { register } })
  const waiting = vi.fn()
  expect(await registerPwa(waiting)).toBe(registration)
  expect(register).toHaveBeenCalledWith('/sw.js', { scope: '/', updateViaCache: 'none' })
  expect(waiting).toHaveBeenCalledOnce()
})

it('insecure production keeps the ordinary online application', async () => {
  vi.stubEnv('PROD', true)
  vi.stubGlobal('isSecureContext', false)
  expect(await registerPwa(vi.fn())).toBeNull()
})

it('has no install button until a real browser offer and consumes that offer only once', async () => {
  const w = mount(PwaStatus)
  expect(w.find('button').exists()).toBe(false)
  const event = new Event('beforeinstallprompt', { cancelable: true })
  const prompt = vi.fn().mockResolvedValue(undefined)
  Object.assign(event, { prompt, userChoice: Promise.resolve({ outcome: 'dismissed' }) })
  window.dispatchEvent(event)
  await flushPromises()
  expect(event.defaultPrevented).toBe(true)
  await w.get('button').trigger('click')
  await flushPromises()
  expect(prompt).toHaveBeenCalledOnce()
  expect(w.find('button').exists()).toBe(false)
  w.unmount()
  window.dispatchEvent(new Event('beforeinstallprompt'))
  expect(prompt).toHaveBeenCalledOnce()
})

function worker(failure = false) {
  const listeners = new Map<string, (event: unknown) => void>()
  const put = vi.fn().mockResolvedValue(undefined)
  const match = vi.fn().mockResolvedValue(new Response('public'))
  const cache = { put, match }
  const caches = {
    open: vi.fn().mockResolvedValue(cache),
    keys: vi.fn().mockResolvedValue(['test-old', 'other-app', 'test-new']),
    delete: vi.fn().mockResolvedValue(true),
  }
  const fetch = failure
    ? vi.fn().mockRejectedValue(new Error('unavailable'))
    : vi.fn().mockResolvedValue(new Response('public'))
  const scope = {
    registration: { scope: 'https://twoworlds.test/' },
    caches,
    clients: { claim: vi.fn() },
    fetch,
    addEventListener: (type: string, callback: (event: unknown) => void) =>
      listeners.set(type, callback),
  }
  attachWorker(scope as unknown as Parameters<typeof attachWorker>[0], {
    prefix: 'test-',
    version: 'new',
    resources: [{ path: 'offline.html', integrity: 'sha256-test' }],
  })
  return { listeners, scope, put, match, fetch, caches }
}

it('install fetches only public bytes with omitted credentials, no redirects and integrity', async () => {
  const w = worker()
  const waitUntil = vi.fn()
  w.listeners.get('install')!({ waitUntil })
  await waitUntil.mock.calls[0]![0]
  const request = w.fetch.mock.calls[0]![0] as Request
  expect(request).toMatchObject({
    credentials: 'omit',
    redirect: 'error',
    cache: 'no-store',
    integrity: 'sha256-test',
  })
  expect(w.put).toHaveBeenCalledOnce()
})

it('failed install removes its incomplete shell, without activating', async () => {
  const w = worker(true),
    waitUntil = vi.fn()
  w.listeners.get('install')!({ waitUntil })
  await expect(waitUntil.mock.calls[0]![0]).rejects.toThrow('unavailable')
  expect(w.caches.delete).toHaveBeenCalledWith('test-new')
  expect(w.scope.clients.claim).not.toHaveBeenCalled()
})

it('activation cleans only this deployment prefix', async () => {
  const w = worker(),
    waitUntil = vi.fn()
  w.listeners.get('activate')!({ waitUntil })
  await waitUntil.mock.calls[0]![0]
  expect(w.caches.delete.mock.calls).toEqual([['test-old']])
})

it.each(['/api/me', '/api/saves/save_one', '/%61pi/me', 'https://other.test/api/me'])(
  'does not intercept or clone %s',
  (url) => {
    const w = worker(),
      respondWith = vi.fn()
    w.listeners.get('fetch')!({
      request: new Request(new URL(url, 'https://twoworlds.test/')),
      respondWith,
    })
    expect(respondWith).not.toHaveBeenCalled()
    expect(w.caches.open).not.toHaveBeenCalled()
    expect(w.fetch).not.toHaveBeenCalled()
  },
)

it('private navigation falls back only to public offline bytes and never writes HTML', async () => {
  const w = worker(true),
    respondWith = vi.fn()
  const request = new Request('https://twoworlds.test/saves/private_id')
  Object.defineProperty(request, 'mode', { value: 'navigate' })
  w.listeners.get('fetch')!({ request, respondWith })
  expect(await (await respondWith.mock.calls[0]![0]).text()).toBe('public')
  expect(w.put).not.toHaveBeenCalled()
  expect((w.match.mock.calls[0]![0] as Request).url).toBe('https://twoworlds.test/offline.html')
})
