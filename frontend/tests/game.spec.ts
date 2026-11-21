import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { parseGame } from '../src/types/game'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { json, me } from './fixtures'
import { game } from './game-fixture'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})
it('read-only reload rejects a lower version and preserves current role', async () => {
  const s = await setup()
  const previous = s.snapshot
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ ...game(), version: 1 })))
  await s.load('save_one')
  expect(s.snapshot).toEqual(previous)
})
it('explicitly retries the same unknown request UUID and parameters', async () => {
  const s = await setup()
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(Error('offline'))
    .mockImplementationOnce(async (_url, options) => {
      const c = JSON.parse(options.body)
      return json({
        receipt: {
          request_id: c.request_id,
          status: 'accepted',
          accepted_version: 8,
          duplicate: true,
        },
        save: { ...game(), version: 8 },
      })
    })
  vi.stubGlobal('fetch', fetch)
  await s.submit('adjust', { angle: 90, pattern: 'pulse' })
  await s.retry()
  expect(fetch.mock.calls[0]![1].body).toBe(fetch.mock.calls[1]![1].body)
  expect(s.pending).toBeNull()
  expect(s.snapshot?.version).toBe(8)
})
afterEach(() => vi.unstubAllGlobals())
it('parses only personal projection and typed controls, not complete state', () => {
  const s = parseGame({ ...game(), state: { secret: 'HIDDEN' } })
  expect(JSON.stringify(s)).not.toContain('HIDDEN')
  expect(s.personal.devices.emitter?.angle).toBe(0)
  expect(s.available_actions[0]?.parameters[0]?.choices).toEqual([0, 90])
})
it.each(['version', 'personal', 'public', 'available_actions', 'presentation'])(
  'rejects missing %s',
  (key) => {
    const value: Record<string, unknown> = { ...game() }
    delete value[key]
    expect(() => parseGame(value)).toThrow()
  },
)
it('rejects invalid nested scalar, parameter type and unprojected dialogue', () => {
  for (const value of [
    { ...game(), personal: { ...game().personal, devices: { x: { angle: [] } } } },
    {
      ...game(),
      available_actions: [
        {
          id: 'bad',
          kind: 'bad',
          parameters: [{ id: 'v', value_type: 'float', choices: [], max_length: null }],
        },
      ],
    },
    { ...game(), personal: { ...game().personal, dialogue: ['hidden'] } },
  ])
    expect(() => parseGame(value)).toThrow()
})
async function setup() {
  const id = useIdentityStore()
  id.account = me.account
  id.sessionGeneration = 1
  id.initialized = true
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(game())))
  const store = useGameStore()
  await store.load('save_one')
  return store
}
it('sends UUID and confirmed version; no optimistic mutation before receipt', async () => {
  const s = await setup()
  const previous = s.snapshot
  let resolve!: (r: Response) => void
  const fetch = vi.fn().mockImplementation(() => new Promise<Response>((r) => (resolve = r)))
  vi.stubGlobal('fetch', fetch)
  const pending = s.submit('adjust', { angle: 90, pattern: 'pulse' })
  expect(s.snapshot).toEqual(previous)
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  const body = JSON.parse(fetch.mock.calls[0]![1].body)
  expect(body).toMatchObject({
    expected_version: 7,
    kind: 'set_emitter',
    args: { angle: 90, pattern: 'pulse' },
  })
  expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/)
  resolve(
    json({
      receipt: {
        request_id: body.request_id,
        status: 'accepted',
        accepted_version: 8,
        duplicate: false,
      },
      save: {
        ...game(),
        version: 8,
        personal: { ...game().personal, devices: { emitter: { angle: 90, pattern: 'pulse' } } },
      },
    }),
  )
  await pending
  expect(s.snapshot?.version).toBe(8)
  expect(s.snapshot?.personal.devices.emitter?.angle).toBe(90)
})
it('conflict preserves confirmed snapshot and explicit reload recovers', async () => {
  const s = await setup()
  const previous = s.snapshot
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(
        json({ error: { code: 'VERSION_CONFLICT', message: 'SECRET', retryable: false } }, 409),
      )
      .mockResolvedValueOnce(json({ ...game(), version: 9 })),
  )
  await s.submit('adjust', { angle: 90, pattern: 'pulse' })
  expect(s.snapshot).toEqual(previous)
  expect(s.error).toContain('重新读取')
  await s.load('save_one')
  expect(s.snapshot?.version).toBe(9)
})
it('unknown network outcome retains request and blocks new writes without automatic retry', async () => {
  const s = await setup()
  const fetch = vi.fn().mockRejectedValue(new Error('SECRET'))
  vi.stubGlobal('fetch', fetch)
  await s.submit('adjust', { angle: 90, pattern: 'pulse' })
  expect(s.pending?.request_id).toBeTruthy()
  await s.submit('adjust', { angle: 0, pattern: 'steady' })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(s.snapshot?.version).toBe(7)
  expect(s.error).not.toContain('SECRET')
})
it('rejects unavailable actions and invalid choices before fetch', async () => {
  const s = await setup()
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await s.submit('foreign', {})
  await s.submit('adjust', { angle: 45, pattern: 'steady' })
  expect(fetch).not.toHaveBeenCalled()
})
it('ignores old save reads and clears private state on logout', async () => {
  const s = await setup()
  let resolve!: (r: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => new Promise<Response>((r) => (resolve = r))),
  )
  const read = s.load('save_one')
  s.reset()
  resolve(json(game()))
  await read
  expect(s.snapshot).toBeNull()
  useIdentityStore().expireSession()
  expect(s.snapshot).toBeNull()
})
