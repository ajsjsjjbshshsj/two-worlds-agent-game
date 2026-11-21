import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { IDBDatabase } from 'fake-indexeddb'
import {
  PENDING_DATABASE,
  forgetPending,
  markPendingSent,
  pendingScope,
  readPending,
  savePending,
} from '../src/services/pending'
import { parseGame } from '../src/types/game'
import { me } from './fixtures'
import { game } from './game-fixture'

const scope = pendingScope(me.account.id, parseGame(game()))
const command = {
  request_id: '18826d64-68ca-4327-8dbe-604b9a7fee3e',
  expected_version: 7,
  kind: 'inspect',
  args: { target: 'maintenance_log' },
}
const key = scope.account_id + '.' + scope.save_id
let time: number

beforeEach(() => {
  localStorage.clear()
  time = Date.now()
})
afterEach(() => vi.restoreAllMocks())

async function insert(raw: string) {
  const open = indexedDB.open(PENDING_DATABASE, 1)
  open.onupgradeneeded = () => open.result.createObjectStore('records')
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    open.onsuccess = () => resolve(open.result)
    open.onerror = () => reject(open.error)
  })
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction('records', 'readwrite')
      transaction.objectStore('records').put(raw, key)
      transaction.oncomplete = () => resolve()
      transaction.onabort = () => reject(transaction.error)
    })
  } finally {
    database.close()
  }
}

function raw(overrides: Record<string, unknown> = {}) {
  return {
    schema: 1,
    scope,
    phase: 'prepared',
    created_at: time,
    command,
    ...overrides,
  }
}

it('preserves exact command through prepared and sent phases, then deletes only the matching UUID', async () => {
  expect(await savePending(scope, command)).toBe('saved')
  expect(await savePending(scope, { ...command, request_id: crypto.randomUUID() })).toBe('existing')
  expect(await readPending(scope)).toMatchObject({ record: { phase: 'prepared', command } })
  expect(await markPendingSent(scope, { ...command, args: { target: 'clock_gears' } })).toBe(false)
  expect(await markPendingSent(scope, command)).toBe(true)
  expect(await readPending(scope)).toMatchObject({ record: { phase: 'sent', command } })
  expect(await forgetPending(scope, crypto.randomUUID())).toBe(true)
  expect((await readPending(scope)).status).toBe('ready')
  expect(await forgetPending(scope, command.request_id)).toBe(true)
  expect((await readPending(scope)).status).toBe('empty')
})

it('commits only one of two simultaneous preparations for the same scope', async () => {
  const results = await Promise.all([
    savePending(scope, command),
    savePending(scope, { ...command, request_id: crypto.randomUUID() }),
  ])
  expect(results.sort()).toEqual(['existing', 'saved'])
  expect((await readPending(scope)).status).toBe('ready')
})

it('fails closed when the browser cannot provide strict transaction durability', async () => {
  const transaction = IDBDatabase.prototype.transaction
  vi.spyOn(IDBDatabase.prototype, 'transaction').mockImplementation(function (
    this: IDBDatabase,
    store,
    mode,
  ) {
    return transaction.call(this, store, mode)
  })
  expect(await savePending(scope, command)).toBe('unavailable')
})

it.each([
  { schema: 2 },
  { phase: 'accepted' },
  { extra: 'secret' },
  { scope: { ...scope, role: 'b' } },
  { scope: { ...scope, account_id: 'account_else' } },
  { scope: { ...scope, pair_id: 'pair_else' } },
  { scope: { ...scope, script_version: '2.0.0' } },
  { command: { ...command, request_id: command.request_id + '\n' } },
  { command: { ...command, expected_version: -1 } },
  { command: { ...command, args: { target: 'maintenance_log', extra: 'secret' } } },
  { command: { ...command, args: { target: { name: 'maintenance_log' } } } },
  { command: { ...command, args: { target: 'arbitrary prose with spaces' } } },
  { command: { ...command, kind: 'talk', args: { question: 'secret' } } },
  { command: { ...command, kind: 'constructor', args: {} } },
  { command: { ...command, snapshot: game() } },
])(
  'rejects and removes a record with invalid metadata or unsafe payload (%o)',
  async (overrides) => {
    await insert(JSON.stringify(raw(overrides)))
    expect(await readPending(scope)).toEqual({ status: 'invalid' })
    expect(await readPending(scope)).toEqual({ status: 'empty' })
  },
)

it('rejects corrupt JSON and expires records at 24 hours while preserving other application data', async () => {
  localStorage.setItem('twoworlds.audio-keep', '0.5')
  await insert('{invalid')
  expect((await readPending(scope)).status).toBe('invalid')
  await insert(JSON.stringify(raw({ created_at: time - 86_400_000 })))
  expect((await readPending(scope)).status).toBe('expired')
  expect(await readPending(scope)).toEqual({ status: 'empty' })
  expect(localStorage.getItem('twoworlds.audio-keep')).toBe('0.5')
})

it('refuses a 33rd record without evicting any live command, then reclaims expired slots', async () => {
  for (let n = 0; n < 32; n++) {
    expect(await savePending({ ...scope, save_id: 'save_' + n }, command)).toBe('saved')
  }
  expect(await savePending(scope, command)).toBe('full')
  expect((await readPending({ ...scope, save_id: 'save_0' })).status).toBe('ready')
  vi.spyOn(Date, 'now').mockReturnValue(time + 86_500_000)
  expect(await savePending(scope, command)).toBe('saved')
  expect((await readPending({ ...scope, save_id: 'save_0' })).status).toBe('empty')
})
