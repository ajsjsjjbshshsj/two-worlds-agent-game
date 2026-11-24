import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { registerPrivateSessionGuard } from '../src/services/session-sync'
import { pendingScope, readPending, savePending } from '../src/services/pending'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { parseGame } from '../src/types/game'
import { deferred, fail, json, me, other } from './fixtures'
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
  end(code = 1006) {
    this.readyState = 3
    this.onclose?.(new CloseEvent('close', { code }))
  }
}

let pinia: ReturnType<typeof createPinia>
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'],
  })
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
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.useRealTimers()
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

it('resolves the production API and WSS from the same HTTPS page', async () => {
  vi.stubEnv('VITE_API_BASE_URL', '')
  vi.stubGlobal('location', new URL('https://twoworlds.test/game/save_one'))
  const { socket, fetch } = await open()
  expect(fetch).toHaveBeenCalledWith('/api/saves/save_one', expect.anything())
  expect(socket.url.href).toBe('wss://twoworlds.test/api/ws/saves/save_one')
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
  await vi.waitFor(() => expect(store.pendingState).toBe('sending'))
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

it('blocks commands after a drop until an authenticated snapshot confirms current progress', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  socket.end()
  expect(store.canAct).toBe(false)
  await store.submit('adjust', { angle: 90, pattern: 'pulse' })
  expect(fetch).toHaveBeenCalledTimes(1)

  fetch.mockRejectedValueOnce(new Error('offline'))
  await vi.advanceTimersByTimeAsync(500)
  expect(TestSocket.instances).toHaveLength(2)
  expect(store.canAct).toBe(false)
  TestSocket.instances[1]!.snapshot({ ...game(), version: 8 })
  expect(store.snapshot).toMatchObject({ version: 8, restored: true })
  expect(store.realtime).toBe('live')
  expect(store.canAct).toBe(true)

  fetch.mockResolvedValueOnce(fail(409))
  await store.submit('adjust', { angle: 90, pattern: 'pulse' })
  const body = JSON.parse(fetch.mock.calls.at(-1)![1].body)
  expect(body.expected_version).toBe(8)
})

it.each([0, 0.5, 0.99999])(
  'uses bounded jittered backoff and resets it after recovery (%s)',
  async (random) => {
    vi.spyOn(Math, 'random').mockReturnValue(random)
    const { socket, fetch } = await open()
    fetch.mockRejectedValue(new Error('offline'))
    socket.end()
    for (const [index, base] of [500, 1000, 2000, 4000, 8000, 15000, 15000].entries()) {
      const delay = Math.round(base * (0.8 + random * 0.4))
      await vi.advanceTimersByTimeAsync(delay - 1)
      expect(TestSocket.instances).toHaveLength(index + 1)
      await vi.advanceTimersByTimeAsync(1)
      expect(TestSocket.instances).toHaveLength(index + 2)
      if (index < 6) TestSocket.instances.at(-1)!.end()
    }
    TestSocket.instances.at(-1)!.snapshot({ ...game(), version: 8 })
    TestSocket.instances.at(-1)!.end()
    await vi.advanceTimersByTimeAsync(Math.round(500 * (0.8 + random * 0.4)))
    expect(TestSocket.instances).toHaveLength(9)
  },
)

it('cancels a pending restart retry offline and opens one socket after the session is verified', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  const network = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  socket.end(1012)
  network.mockReturnValue(false)
  window.dispatchEvent(new Event('offline'))
  await vi.advanceTimersByTimeAsync(30000)
  expect(TestSocket.instances).toHaveLength(1)
  expect(fetch).toHaveBeenCalledOnce()
  expect(store.canAct).toBe(false)

  const session = deferred<Response>()
  fetch.mockReturnValueOnce(session.promise).mockResolvedValueOnce(json({ ...game(), version: 8 }))
  network.mockReturnValue(true)
  window.dispatchEvent(new Event('online'))
  window.dispatchEvent(new Event('online'))
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/saves/save_one', '/api/me'])
  expect(TestSocket.instances).toHaveLength(1)

  session.resolve(json(me))
  await vi.advanceTimersByTimeAsync(0)
  expect(TestSocket.instances).toHaveLength(2)
  TestSocket.instances[1]!.snapshot({ ...game(), version: 8 })
  await vi.advanceTimersByTimeAsync(1000)
  expect(TestSocket.instances).toHaveLength(2)
  expect(store.snapshot?.version).toBe(8)
  expect(store.realtime).toBe('live')
  expect(store.canAct).toBe(true)
})

it('uses fresh HTTP snapshots while WebSocket is unavailable and preserves an unknown command', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  fetch.mockRejectedValueOnce(new Error('command response lost'))
  await store.submit('adjust', { angle: 90, pattern: 'pulse' })
  const pending = store.pending
  socket.end()
  fetch.mockImplementation(async () => json({ ...game(), version: 9 }))
  await vi.advanceTimersByTimeAsync(500)
  TestSocket.instances.at(-1)!.end()
  expect(store.realtime).toBe('http')
  expect(store.snapshot).toMatchObject({ version: 9, restored: true })
  expect(store.canAct).toBe(true)
  expect(store.pending).toEqual(pending)
  expect(store.error).toContain('操作结果未知')
  await vi.advanceTimersByTimeAsync(1000)
  expect(store.pending).toEqual(pending)
  expect(fetch.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1)
})

it('coalesces a live compensation read with a manual sync and keeps a newer push', async () => {
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  const response = deferred<Response>()
  fetch.mockReturnValueOnce(response.promise)
  await vi.advanceTimersByTimeAsync(15000)
  const manual = store.open('save_one')
  socket.snapshot({ ...game(), version: 10 })
  expect(fetch).toHaveBeenCalledTimes(2)
  response.resolve(json({ ...game(), version: 8 }))
  await manual
  expect(store.snapshot?.version).toBe(10)
  expect(store.canAct).toBe(true)
  expect(TestSocket.instances).toHaveLength(1)
})

it('pauses background work, then verifies the account before a foreground save read', async () => {
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  document.dispatchEvent(new Event('visibilitychange'))
  expect(store.realtime).toBe('paused')
  expect(socket.close).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(45000)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(store.canAct).toBe(false)

  const identity = deferred<Response>()
  fetch.mockReturnValueOnce(identity.promise).mockResolvedValueOnce(json({ ...game(), version: 8 }))
  hidden.mockReturnValue(false)
  document.dispatchEvent(new Event('visibilitychange'))
  window.dispatchEvent(new Event('online'))
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/saves/save_one', '/api/me'])
  identity.resolve(json(me))
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    '/api/saves/save_one',
    '/api/me',
    '/api/saves/save_one',
  ])
  expect(TestSocket.instances).toHaveLength(2)
  expect(store.snapshot).toMatchObject({ version: 8, restored: true })
  expect(store.canAct).toBe(true)
})

it('uses heartbeat activity to keep a quiet socket and recovers a silent one', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  const { socket, fetch, store } = await open()
  fetch.mockImplementation(async () => json(game()))
  socket.snapshot(game())
  await vi.advanceTimersByTimeAsync(12000)
  socket.receive({ type: 'ping', id: 1 })
  await vi.advanceTimersByTimeAsync(24999)
  expect(TestSocket.instances).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(socket.close).toHaveBeenCalledOnce()
  expect(store.canAct).toBe(false)
  await vi.advanceTimersByTimeAsync(500)
  expect(TestSocket.instances).toHaveLength(2)
})

it('cancels an old read and all retry work when switching saves or signing out', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  socket.end()
  const oldRead = deferred<Response>()
  fetch.mockReturnValueOnce(oldRead.promise)
  await vi.advanceTimersByTimeAsync(500)
  TestSocket.instances.at(-1)!.end()
  const oldSignal = fetch.mock.calls[1]![1].signal as AbortSignal
  fetch.mockResolvedValueOnce(json({ ...game(), id: 'save_other', version: 2 }))
  await store.open('save_other')
  expect(oldSignal.aborted).toBe(true)
  oldRead.resolve(json({ ...game(), version: 20 }))
  await vi.advanceTimersByTimeAsync(1000)
  expect(store.snapshot).toMatchObject({ id: 'save_other', version: 2 })
  expect(TestSocket.instances).toHaveLength(3)
  TestSocket.instances.at(-1)!.end()
  fetch.mockResolvedValueOnce(new Response(null, { status: 204 }))
  await useIdentityStore().logout()
  await vi.advanceTimersByTimeAsync(30000)
  expect(TestSocket.instances).toHaveLength(3)
  expect(store.snapshot).toBeNull()
})

it.each([4403, 4404])(
  'stops retries and hides private data on explicit denial %s',
  async (code) => {
    const { socket, fetch, store } = await open()
    socket.snapshot(game())
    socket.end(code)
    await vi.advanceTimersByTimeAsync(60000)
    expect(store.realtime).toBe('blocked')
    expect(store.snapshot).toBeNull()
    expect(store.canAct).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(TestSocket.instances).toHaveLength(1)
  },
)

it('stops on a denied HTTP compensation after an opaque browser close', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  const { socket, fetch, store } = await open()
  socket.snapshot(game())
  socket.end()
  fetch.mockResolvedValueOnce(fail(404))
  await vi.advanceTimersByTimeAsync(60000)
  expect(store.realtime).toBe('blocked')
  expect(store.snapshot).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(TestSocket.instances).toHaveLength(2)
})

it('does not restore private state from a command response after access was denied', async () => {
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  const reply = deferred<Response>()
  fetch.mockReturnValueOnce(reply.promise)
  const writing = store.submit('adjust', { angle: 90, pattern: 'pulse' })
  await vi.waitFor(() => expect(store.pendingState).toBe('sending'))
  const requestId = store.pending!.request_id
  socket.end(4404)
  reply.resolve(
    json({
      receipt: { status: 'accepted', request_id: requestId, accepted_version: 8, duplicate: false },
      save: { ...game(), version: 8 },
    }),
  )
  await writing
  expect(store.realtime).toBe('blocked')
  expect(store.snapshot).toBeNull()
  expect(store.pending).toBeNull()
})

const pendingCommand = {
  request_id: '18826d64-68ca-4327-8dbe-604b9a7fee3e' as const,
  expected_version: 7,
  kind: 'set_emitter',
  args: { angle: 90, pattern: 'pulse' },
}
const scope = pendingScope(me.account.id, parseGame(game()))
const receiptPath = '/api/saves/save_one/receipts/' + pendingCommand.request_id
const accepted = {
  accepted: true,
  accepted_version: 8,
  request_id: pendingCommand.request_id,
}

it.each([503, 'timeout'])(
  'persists before dispatch and keeps the UUID after %s',
  async (outcome) => {
    const { store, socket, fetch } = await open()
    socket.snapshot(game())
    const uuid = vi.spyOn(crypto, 'randomUUID').mockReturnValue(pendingCommand.request_id)
    let savedAtDispatch: Awaited<ReturnType<typeof readPending>> | undefined
    let sent: unknown
    fetch.mockImplementationOnce(async (_url, request: RequestInit) => {
      sent = JSON.parse(String(request.body))
      savedAtDispatch = await readPending(scope)
      if (outcome === 503) return fail(503, 'SERVICE_UNAVAILABLE')
      return new Promise<Response>((_resolve, reject) => {
        request.signal?.addEventListener('abort', () => reject(Error('timed out')), { once: true })
      })
    })
    const sending = store.submit('adjust', pendingCommand.args)
    if (outcome === 'timeout') {
      await vi.waitFor(() => expect(savedAtDispatch).toBeDefined())
      await vi.advanceTimersByTimeAsync(15000)
    }
    await sending
    expect(sent).toEqual(pendingCommand)
    expect(savedAtDispatch).toMatchObject({
      status: 'ready',
      record: { schema: 1, phase: 'sent', command: pendingCommand },
    })
    expect(uuid).toHaveBeenCalledOnce()
    expect(store.pendingState).toBe('unknown')
    expect(await readPending(scope)).toMatchObject({ record: { command: pendingCommand } })
    expect(store.pending).toEqual(pendingCommand)
  },
)

it('reloads the same UUID, coalesces checks and settles only on its matching receipt', async () => {
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  const uuid = vi.spyOn(crypto, 'randomUUID').mockReturnValue(pendingCommand.request_id)
  fetch.mockRejectedValueOnce(Error('lost command response'))
  await store.submit('adjust', pendingCommand.args)
  const reloaded = deferred<Response>()
  disposePinia(pinia)
  pinia = createPinia()
  setActivePinia(pinia)
  const identity = useIdentityStore()
  identity.account = me.account
  identity.initialized = true
  const next = useGameStore()
  fetch.mockResolvedValueOnce(json(game())).mockReturnValueOnce(reloaded.promise)
  await next.open('save_one')
  const newSocket = TestSocket.instances.at(-1)!
  newSocket.snapshot({ ...game(), version: 9 })
  await next.submit('adjust', { angle: 0, pattern: 'steady' })
  await next.retry()
  expect(next.pending).toEqual(pendingCommand)
  expect(next.pendingState).toBe('checking')
  expect(fetch.mock.calls.filter(([url]) => url === receiptPath)).toHaveLength(1)
  reloaded.resolve(json(accepted))
  await vi.waitFor(() => expect(next.pendingState).toBe('accepted'))
  expect(next.pending).toBeNull()
  expect(next.pendingState).toBe('accepted')
  expect(next.snapshot).toMatchObject({ version: 9, restored: true })
  expect(next.snapshot).not.toHaveProperty('audio_events')
  expect(await readPending(scope)).toEqual({ status: 'empty' })
  newSocket.snapshot({ ...game(), version: 9 })
  await next.retry()
  expect(next.snapshot).not.toHaveProperty('audio_events')
  expect(uuid).toHaveBeenCalledOnce()
  expect(fetch.mock.calls.filter(([, r]) => r.method === 'POST')).toHaveLength(1)
})

it('blocks new commands after a receipt until its version is visible, then uses a static baseline', async () => {
  expect(await savePending(scope, pendingCommand)).toBe('saved')
  const confirm = deferred<Response>()
  const latest = deferred<Response>()
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(game()))
    .mockReturnValueOnce(confirm.promise)
    .mockReturnValueOnce(latest.promise)
  vi.stubGlobal('fetch', fetch)
  const store = useGameStore()
  await store.open('save_one')
  TestSocket.instances[0]!.snapshot(game())
  confirm.resolve(json(accepted))
  await vi.waitFor(() => expect(store.pendingState).toBe('accepted'))
  expect(store.pending).toBeNull()
  expect(store.canAct).toBe(false)
  expect(store.snapshot?.version).toBe(7)
  await store.submit('adjust', pendingCommand.args)
  expect(fetch.mock.calls.filter(([, r]) => r.method === 'POST')).toHaveLength(0)
  latest.resolve(json({ ...game(), version: 8, audio_events: [{ asset_id: 'foreign' }] }))
  await vi.advanceTimersByTimeAsync(0)
  expect(store.canAct).toBe(true)
  expect(store.snapshot).toMatchObject({ version: 8, restored: true })
  expect(store.snapshot).not.toHaveProperty('audio_events')
})

it('keeps absent or malformed receipts unresolved even when WS has a higher version', async () => {
  expect(await savePending(scope, pendingCommand)).toBe('saved')
  const receipt = deferred<Response>()
  const fetch = vi.fn().mockResolvedValueOnce(json(game())).mockReturnValueOnce(receipt.promise)
  vi.stubGlobal('fetch', fetch)
  const store = useGameStore()
  await store.open('save_one')
  TestSocket.instances[0]!.snapshot({ ...game(), version: 10 })
  receipt.resolve(json({ accepted: false }))
  await vi.advanceTimersByTimeAsync(0)
  expect(store.pendingState).toBe('missing')
  expect(store.canResubmit).toBe(false)
  fetch.mockResolvedValueOnce(json({ ...accepted, accepted_version: 10 }))
  await store.retry()
  expect(store.pendingState).toBe('unknown')
  expect(store.pending?.request_id).toBe(pendingCommand.request_id)
  expect((await readPending(scope)).status).toBe('ready')
  expect(fetch.mock.calls.every(([, r]) => r.method === 'GET')).toBe(true)
})

it('only retries a restored command after explicit confirmation, with the exact original payload', async () => {
  expect(await savePending(scope, pendingCommand)).toBe('saved')
  const receipt = deferred<Response>()
  const fetch = vi.fn().mockResolvedValueOnce(json(game())).mockReturnValueOnce(receipt.promise)
  vi.stubGlobal('fetch', fetch)
  const store = useGameStore()
  await store.open('save_one')
  TestSocket.instances[0]!.snapshot(game())
  receipt.resolve(json({ accepted: false }))
  await vi.advanceTimersByTimeAsync(0)
  expect(store.canResubmit).toBe(true)
  expect(fetch.mock.calls.filter(([, r]) => r.method === 'POST')).toHaveLength(0)
  const uuid = vi.spyOn(crypto, 'randomUUID')
  fetch.mockResolvedValueOnce(fail(409, 'VERSION_CONFLICT'))
  await store.resubmit()
  expect(JSON.parse(String(fetch.mock.calls[2]![1].body))).toEqual(pendingCommand)
  expect(uuid).not.toHaveBeenCalled()
  expect(store.pendingState).toBe('rejected')
  expect(store.pendingNotice).not.toContain('PRIVATE_TEST_RESPONSE')
  expect(await readPending(scope)).toEqual({ status: 'empty' })
})

it('ignores old receipts and socket frames after switching save or account', async () => {
  expect(await savePending(scope, pendingCommand)).toBe('saved')
  const receipt = deferred<Response>()
  const fetch = vi.fn().mockResolvedValueOnce(json(game())).mockReturnValueOnce(receipt.promise)
  vi.stubGlobal('fetch', fetch)
  const store = useGameStore()
  await store.open('save_one')
  const late = TestSocket.instances[0]!.onmessage!
  fetch.mockResolvedValueOnce(json({ ...game(), id: 'save_other', version: 1 }))
  await store.open('save_other')
  expect(fetch.mock.calls[1]![1].signal.aborted).toBe(true)
  late(new MessageEvent('message', { data: JSON.stringify({ type: 'snapshot', save: game() }) }))
  receipt.resolve(json(accepted))
  await vi.advanceTimersByTimeAsync(0)
  expect(store.snapshot).toMatchObject({ id: 'save_other', version: 1 })
  expect(store.pending).toBeNull()
  const identity = useIdentityStore()
  identity.account = other.account
  identity.sessionGeneration++
  fetch.mockResolvedValueOnce(json({ ...game(), role: 'b' }))
  await store.open('save_one')
  expect(store.snapshot?.role).toBe('b')
  expect(store.pending).toBeNull()
  expect(fetch.mock.calls.filter(([url]) => url === receiptPath)).toHaveLength(1)
  expect((await readPending(scope)).status).toBe('ready')
})

it('does not persist NPC dialogue and discloses that it cannot survive a refresh', async () => {
  const privateGame = {
    ...game(),
    available_actions: [
      {
        id: 'ask',
        kind: 'talk',
        parameters: [{ id: 'question', value_type: 'string', choices: [], max_length: 120 }],
      },
    ],
  }
  const fetch = vi.fn().mockResolvedValueOnce(json(privateGame)).mockRejectedValueOnce(Error())
  vi.stubGlobal('fetch', fetch)
  const store = useGameStore()
  await store.open('save_one')
  TestSocket.instances[0]!.snapshot(privateGame)
  await store.submit('ask', { question: 'PRIVATE_NPC_TEXT' })
  expect(JSON.parse(fetch.mock.calls[1]![1].body).args.question).toBe('PRIVATE_NPC_TEXT')
  expect(await readPending(scope)).toEqual({ status: 'empty' })
  expect(JSON.stringify(localStorage)).not.toContain('PRIVATE_NPC_TEXT')
  expect(JSON.stringify(sessionStorage)).not.toContain('PRIVATE_NPC_TEXT')
  expect(store.pendingNotice).toContain('仅可在本页')
})

it('does not send a persistable operation when durable storage fails', async () => {
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  vi.spyOn(indexedDB, 'open').mockImplementation(() => {
    throw Error('quota exceeded')
  })
  await store.submit('adjust', pendingCommand.args)
  expect(fetch).toHaveBeenCalledOnce()
  expect(store.pendingState).toBe('unavailable')
  expect(store.pendingNotice).toContain('本次操作未发送')
  expect(store.pending).toBeNull()
})

it('refreshes the losing device after a CAS conflict without replaying its operation', async () => {
  const { store, socket, fetch } = await open()
  socket.snapshot(game())
  const latest = deferred<Response>()
  fetch.mockResolvedValueOnce(fail(409, 'VERSION_CONFLICT')).mockReturnValueOnce(latest.promise)
  await store.submit('adjust', pendingCommand.args)
  expect(store.pendingState).toBe('rejected')
  expect(store.pendingNotice).toContain('原操作未执行')
  expect(store.snapshot?.version).toBe(7)
  expect(store.canAct).toBe(false)
  expect(fetch.mock.calls.map(([, request]) => request.method)).toEqual(['GET', 'POST', 'GET'])

  await store.submit('adjust', { angle: 0, pattern: 'steady' })
  await store.retry()
  expect(fetch.mock.calls.filter(([, request]) => request.method === 'POST')).toHaveLength(1)
  const requestId = JSON.parse(fetch.mock.calls[1]![1].body).request_id
  expect(requestId).toMatch(/^[0-9a-f-]{36}$/)

  socket.snapshot({ ...game(), version: 10 })
  latest.resolve(json({ ...game(), version: 8 }))
  await vi.advanceTimersByTimeAsync(0)
  expect(store.snapshot).toMatchObject({ version: 10, from_realtime: true })
  expect(store.snapshot).not.toHaveProperty('audio_events')
  expect(store.canAct).toBe(true)
  expect(store.pending).toBeNull()
  expect((await readPending(scope)).status).toBe('empty')
  expect(fetch.mock.calls.filter(([, request]) => request.method === 'POST')).toHaveLength(1)
})
