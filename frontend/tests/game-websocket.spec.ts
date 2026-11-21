import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { registerPrivateSessionGuard } from '../src/services/session-sync'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { deferred, fail, json, me } from './fixtures'
import { game } from './game-fixture'

class TestSocket {
  static OPEN = 1
  static instances: TestSocket[] = []
  readyState = TestSocket.OPEN
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor(readonly url: URL) {
    TestSocket.instances.push(this)
  }
  receive(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
  snapshot(save: unknown) {
    this.receive({ type: 'snapshot', save })
  }
}

let pinia: ReturnType<typeof createPinia>
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const identity = useIdentityStore()
  identity.account = me.account
  identity.initialized = true
  TestSocket.instances = []
  vi.stubGlobal('WebSocket', TestSocket)
})
afterEach(() => {
  disposePinia(pinia)
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

async function open() {
  const fetch = vi.fn().mockResolvedValueOnce(json(game()))
  vi.stubGlobal('fetch', fetch)
  const store = useGameStore()
  await store.open('save_one')
  return { store, socket: TestSocket.instances[0]!, fetch }
}

it('uses the configured origin, sends only a matching heartbeat reply and accepts a valid snapshot', async () => {
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.twoworlds.test')
  const { store, socket } = await open()
  expect(socket.url.href).toBe('wss://api.twoworlds.test/api/ws/saves/save_one')
  expect(store.realtime).toBe('connecting')
  socket.receive({ type: 'ping', id: '4' })
  socket.receive({ type: 'ping', id: 3, extra: true })
  socket.receive({ type: 'pong', id: 1 })
  socket.receive({ type: 'ping', id: 4 })
  expect(socket.send.mock.calls).toEqual([[JSON.stringify({ type: 'pong', id: 4 })]])
  socket.snapshot(game())
  expect(store.realtime).toBe('live')
  socket.snapshot({ ...game(), version: 8 })
  expect(store.snapshot).toMatchObject({ version: 8, from_realtime: true })
})

it('rejects duplicate, out-of-order, other-role, other-save and malformed snapshots', async () => {
  const { store, socket } = await open()
  socket.snapshot({ ...game(), version: 9 })
  const accepted = store.snapshot
  for (const save of [
    { ...game(), version: 9 },
    { ...game(), version: 8 },
    { ...game(), version: 12, role: 'b' },
    { ...game(), version: 12, id: 'save_other' },
    { ...game(), version: 12, pair_id: 'pair_other' },
    { ...game(), version: 12, personal: null },
  ]) {
    socket.snapshot(save)
    expect(store.snapshot).toBe(accepted)
  }
})

it('accepts projected demo dialogue and leaves the transcript out of the game view', async () => {
  const { store, socket } = await open()
  const sample = game()
  socket.snapshot({
    ...sample,
    version: 8,
    personal: {
      ...sample.personal,
      dialogue: [
        { question: 'my turn', answer: 'answer', mode: 'demo', created_at: '2026-11-21T00:00:00Z' },
      ],
    },
  })
  expect(store.snapshot?.version).toBe(8)
  expect(store.snapshot?.personal.dialogue).toEqual([])
})

it('closes and fences sockets on save changes, page cleanup and logout', async () => {
  const { store, socket, fetch } = await open()
  const late = socket.onmessage!
  fetch.mockResolvedValueOnce(json({ ...game(), id: 'save_other', version: 1 }))
  await store.open('save_other')
  expect(socket.close).toHaveBeenCalledOnce()
  late(
    new MessageEvent('message', {
      data: JSON.stringify({ type: 'snapshot', save: { ...game(), version: 20 } }),
    }),
  )
  expect(store.snapshot).toMatchObject({ id: 'save_other', version: 1 })
  store.reset()
  expect(TestSocket.instances[1]?.close).toHaveBeenCalledOnce()
  expect(store.snapshot).toBeNull()

  fetch
    .mockResolvedValueOnce(json(game()))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
  await store.open('save_one')
  await useIdentityStore().logout()
  expect(TestSocket.instances[2]?.close).toHaveBeenCalledOnce()
  expect(store.snapshot).toBeNull()
})

it('blocks delivery during an unconfirmed session and after an account change', async () => {
  let validGeneration: number | null = 1
  const unregister = registerPrivateSessionGuard(() => validGeneration)
  try {
    const { store, socket } = await open()
    validGeneration = null
    socket.snapshot({ ...game(), version: 12 })
    expect(store.snapshot?.version).toBe(7)
    validGeneration = 1
    const identity = useIdentityStore()
    identity.account = { ...me.account, id: 'account_other' }
    socket.snapshot({ ...game(), version: 12 })
    expect(store.snapshot?.version).toBe(7)
  } finally {
    unregister()
  }
})

it('keeps a newer socket version across late HTTP reads and command acknowledgements', async () => {
  const { store, socket, fetch } = await open()
  const read = deferred<Response>()
  fetch.mockReturnValueOnce(read.promise)
  const reading = store.load('save_one')
  socket.snapshot({ ...game(), version: 9 })
  read.resolve(json({ ...game(), version: 8 }))
  await reading
  expect(store.snapshot?.version).toBe(9)

  const response = deferred<Response>()
  fetch.mockReturnValueOnce(response.promise)
  const submission = store.submit('adjust', { angle: 90, pattern: 'pulse' })
  const pending = store.pending!
  expect(pending.expected_version).toBe(9)
  socket.snapshot({ ...game(), version: 11, audio_events: [{ accepted_version: 10 }] })
  expect(store.pending).toEqual(pending)
  expect(store.snapshot).toMatchObject({ version: 11, from_realtime: true })
  expect(store.snapshot?.audio_events).toBeUndefined()
  response.resolve(
    json({
      receipt: {
        request_id: pending.request_id,
        status: 'accepted',
        accepted_version: 10,
        duplicate: false,
      },
      save: { ...game(), version: 10 },
    }),
  )
  await submission
  expect(store.pending).toBeNull()
  expect(store.snapshot?.version).toBe(11)
})

it('shows the HTTP fallback on disconnect, and rechecks a server-revoked session', async () => {
  const { store, socket, fetch } = await open()
  socket.onclose?.(new CloseEvent('close', { code: 1006 }))
  expect(store.realtime).toBe('offline')
  expect(TestSocket.instances).toHaveLength(1)
  fetch.mockResolvedValueOnce(json({ ...game(), version: 8 })).mockResolvedValueOnce(fail(401))
  await store.open('save_one')
  const recheck = vi.spyOn(useIdentityStore(), 'verifySession')
  TestSocket.instances[1]?.onclose?.(new CloseEvent('close', { code: 4401 }))
  await recheck.mock.results[0]?.value
  expect(fetch.mock.calls.at(-1)?.[0]).toBe('/api/me')
  expect(store.snapshot).toBeNull()
})
