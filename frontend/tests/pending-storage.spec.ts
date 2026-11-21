import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import {
  PENDING_PREFIX,
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
const key = PENDING_PREFIX + scope.account_id + '.' + scope.save_id
let time: number

beforeEach(() => {
  localStorage.clear()
  time = Date.now()
})
afterEach(() => vi.restoreAllMocks())

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

it('preserves exact command through prepared and sent phases, then deletes only the matching UUID', () => {
  expect(savePending(scope, command)).toBe('saved')
  expect(savePending(scope, { ...command, request_id: crypto.randomUUID() })).toBe('existing')
  expect(readPending(scope)).toMatchObject({ record: { phase: 'prepared', command } })
  expect(markPendingSent(scope, { ...command, args: { target: 'clock_gears' } })).toBe(false)
  expect(markPendingSent(scope, command)).toBe(true)
  expect(readPending(scope)).toMatchObject({ record: { phase: 'sent', command } })
  expect(forgetPending(scope, crypto.randomUUID())).toBe(true)
  expect(readPending(scope).status).toBe('ready')
  expect(forgetPending(scope, command.request_id)).toBe(true)
  expect(readPending(scope).status).toBe('empty')
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
])('rejects and removes a record with invalid metadata or unsafe payload (%o)', (overrides) => {
  localStorage.setItem(key, JSON.stringify(raw(overrides)))
  expect(readPending(scope)).toEqual({ status: 'invalid' })
  expect(localStorage.getItem(key)).toBeNull()
})

it('rejects corrupt JSON and expires records at 24 hours while preserving other application data', () => {
  localStorage.setItem('twoworlds.audio-keep', '0.5')
  localStorage.setItem(key, '{invalid')
  expect(readPending(scope).status).toBe('invalid')
  localStorage.setItem(key, JSON.stringify(raw({ created_at: time - 86_400_000 })))
  expect(readPending(scope).status).toBe('expired')
  expect(localStorage.getItem(key)).toBeNull()
  expect(localStorage.getItem('twoworlds.audio-keep')).toBe('0.5')
})

it('refuses a 33rd record without evicting any live command, then reclaims expired slots', () => {
  for (let n = 0; n < 32; n++) {
    expect(savePending({ ...scope, save_id: 'save_' + n }, command)).toBe('saved')
  }
  expect(savePending(scope, command)).toBe('full')
  expect(readPending({ ...scope, save_id: 'save_0' }).status).toBe('ready')
  vi.spyOn(Date, 'now').mockReturnValue(time + 86_500_000)
  expect(savePending(scope, command)).toBe('saved')
  expect(localStorage.length).toBe(1)
})
