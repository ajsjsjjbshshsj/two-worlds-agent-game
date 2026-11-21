import { isRecord } from './http'
import type { Command } from './game'
import type { SaveEntry } from '../types/resources'

export const PENDING_PREFIX = 'twoworlds.pending-command.v1.'
const LIFETIME = 24 * 60 * 60 * 1000
const MAX_RECORDS = 32
const MAX_LENGTH = 2048
const ID = /^[a-z][a-z0-9_]{0,63}$/
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

export interface PendingScope {
  account_id: string
  save_id: string
  pair_id: string
  script_id: string
  script_version: string
  role: 'a' | 'b'
}

export interface PendingRecord {
  schema: 1
  scope: PendingScope
  created_at: number
  phase: 'prepared' | 'sent'
  command: Command
}

type ReadResult =
  | { status: 'ready'; record: PendingRecord }
  | { status: 'empty' | 'expired' | 'invalid' | 'unavailable' }

function matches(value: unknown, pattern: RegExp) {
  return typeof value === 'string' && pattern.exec(value)?.[0] === value
}

function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  )
}

export function isRequestId(value: unknown): value is string {
  return matches(value, UUID)
}

// Only bounded mechanics, literal enums and structured references may reach disk.
// The server's current action choices also gate creation and manual replay.
const mechanicalArgs = {
  inspect: { target: ID },
  set_emitter: { angle: [0, 90, 180, 270], pattern: ['steady', 'pulse'] },
  set_filter: { filter: ['clear', 'blue', 'amber'] },
  lock_signal: {},
  route_power: { target: ['tower', 'shore', 'observatory'] },
  repair_clock: { mode: ['steady'] },
  confirm_route: {},
  vote_ending: { choice: ['guide_now', 'wait_tide', 'rescue_detour', 'return_station'] },
  set_echo_gate: { position: ['west', 'east', 'closed'] },
  allocate_power: { engine: [false, true], sonar: [false, true], lamp: [false, true] },
  scan_track: {},
  install_rail: { segment: ['bridge_2'] },
  confirm_signal: {},
  set_platform: { track: ['track_1', 'track_2', 'track_3'] },
  dispatch_train: {},
} satisfies Record<string, Record<string, RegExp | readonly (string | number | boolean)[]>>

export function canPersistCommand(command: Pick<Command, 'kind' | 'args'>) {
  const { kind, args } = command
  if (!Object.hasOwn(mechanicalArgs, kind)) return false
  const schema: Record<string, RegExp | readonly unknown[]> =
    mechanicalArgs[kind as keyof typeof mechanicalArgs]
  return (
    exact(args, Object.keys(schema)) &&
    Object.entries(schema).every(([key, rule]) =>
      rule instanceof RegExp ? matches(args[key], rule) : rule.includes(args[key]),
    )
  )
}

export function pendingScope(accountId: string, save: SaveEntry): PendingScope {
  return {
    account_id: accountId,
    save_id: save.id,
    pair_id: save.pair_id,
    script_id: save.script_id,
    script_version: save.script_version,
    role: save.role,
  }
}

function keyFor(scope: PendingScope) {
  return PENDING_PREFIX + scope.account_id + '.' + scope.save_id
}

function validScope(value: unknown): value is PendingScope {
  return (
    exact(value, ['account_id', 'save_id', 'pair_id', 'script_id', 'script_version', 'role']) &&
    [value.account_id, value.save_id, value.pair_id, value.script_id].every((id) =>
      matches(id, ID),
    ) &&
    typeof value.script_version === 'string' &&
    value.script_version.length <= 32 &&
    matches(value.script_version, VERSION) &&
    (value.role === 'a' || value.role === 'b')
  )
}

function validCommand(value: unknown): value is Command {
  return (
    exact(value, ['request_id', 'expected_version', 'kind', 'args']) &&
    isRequestId(value.request_id) &&
    typeof value.expected_version === 'number' &&
    Number.isInteger(value.expected_version) &&
    value.expected_version >= 0 &&
    value.expected_version <= 512 &&
    typeof value.kind === 'string' &&
    isRecord(value.args) &&
    canPersistCommand({ kind: value.kind, args: value.args })
  )
}

function parse(raw: string | null, key: string, now: number): ReadResult {
  if (raw === null) return { status: 'empty' }
  if (raw.length > MAX_LENGTH) return { status: 'invalid' }
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return { status: 'invalid' }
  }
  if (
    !exact(value, ['schema', 'scope', 'created_at', 'phase', 'command']) ||
    value.schema !== 1 ||
    !validScope(value.scope) ||
    keyFor(value.scope) !== key ||
    typeof value.created_at !== 'number' ||
    !Number.isSafeInteger(value.created_at) ||
    value.created_at <= 0 ||
    value.created_at > now ||
    (value.phase !== 'prepared' && value.phase !== 'sent') ||
    !validCommand(value.command)
  )
    return { status: 'invalid' }
  if (now - value.created_at >= LIFETIME) return { status: 'expired' }
  return {
    status: 'ready',
    record: {
      schema: 1,
      scope: value.scope,
      created_at: value.created_at,
      phase: value.phase,
      command: value.command,
    },
  }
}

function read(storage: Storage, key: string, now: number) {
  const result = parse(storage.getItem(key), key, now)
  if (result.status === 'invalid' || result.status === 'expired') storage.removeItem(key)
  return result
}

export function readPending(scope: PendingScope): ReadResult {
  if (!validScope(scope)) return { status: 'invalid' }
  try {
    const storage = window.localStorage
    const key = keyFor(scope)
    const result = read(storage, key, Date.now())
    if (
      result.status === 'ready' &&
      (Object.keys(scope) as Array<keyof PendingScope>).some(
        (key) => scope[key] !== result.record.scope[key],
      )
    ) {
      storage.removeItem(key)
      return { status: 'invalid' }
    }
    return result
  } catch {
    return { status: 'unavailable' }
  }
}

export function savePending(
  scope: PendingScope,
  command: Command,
): 'saved' | 'existing' | 'full' | 'unavailable' {
  if (!validScope(scope) || !validCommand(command)) return 'unavailable'
  try {
    const storage = window.localStorage
    const now = Date.now()
    const key = keyFor(scope)
    if (read(storage, key, now).status === 'ready') return 'existing'
    // Snapshot keys before deleting bad/expired records so adjacent entries are not skipped.
    const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i))
    const count = keys.filter(
      (entry) => entry?.startsWith(PENDING_PREFIX) && read(storage, entry, now).status === 'ready',
    ).length
    if (count >= MAX_RECORDS) return 'full'
    const record: PendingRecord = { schema: 1, scope, created_at: now, phase: 'prepared', command }
    storage.setItem(key, JSON.stringify(record))
    return 'saved'
  } catch {
    return 'unavailable'
  }
}

export function markPendingSent(scope: PendingScope, command: Command) {
  const current = readPending(scope)
  if (
    current.status !== 'ready' ||
    current.record.command.request_id !== command.request_id ||
    current.record.command.expected_version !== command.expected_version ||
    current.record.command.kind !== command.kind ||
    JSON.stringify(current.record.command.args, Object.keys(command.args).sort()) !==
      JSON.stringify(command.args, Object.keys(command.args).sort())
  )
    return false
  if (current.record.phase === 'sent') return true
  try {
    window.localStorage.setItem(keyFor(scope), JSON.stringify({ ...current.record, phase: 'sent' }))
    return true
  } catch {
    return false
  }
}

export function forgetPending(scope: PendingScope, requestId: string) {
  const current = readPending(scope)
  if (current.status === 'unavailable') return false
  if (current.status !== 'ready' || current.record.command.request_id !== requestId) return true
  try {
    window.localStorage.removeItem(keyFor(scope))
    return true
  } catch {
    return false
  }
}
