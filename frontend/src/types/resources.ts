import { ApiError, isRecord } from '../services/http'

export type Role = 'a' | 'b'
export interface PairSummary {
  readonly id: string
  readonly role: Role
  readonly member_count: 1 | 2
}
export interface Invitation {
  readonly id: string
  readonly role: 'a'
  readonly invite_token: string
  readonly invite_expires_at: string
}
export interface ScriptMetadata {
  readonly id: string
  readonly content_version: string
  readonly title: string
  readonly summary: string
  readonly roles: readonly { id: Role; name: string; description: string }[]
  readonly difficulty: 'easy' | 'medium' | 'hard'
  readonly estimated_minutes: number
}
export interface SaveEntry {
  readonly id: string
  readonly pair_id: string
  readonly script_id: string
  readonly script_version: string
  readonly version: number
  readonly scene_id: string
  readonly completed: boolean
  readonly role: Role
}
export interface SaveSummary extends SaveEntry {
  readonly created_at: string
  readonly updated_at: string
}
export function invalidResponse(): never {
  throw new ApiError(200, 'INVALID_RESPONSE', false)
}
function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : invalidResponse()
}
function text(value: unknown, max = 2000): string {
  return typeof value === 'string' && value.trim().length > 0 && Array.from(value).length <= max
    ? value
    : invalidResponse()
}
export function identifier(value: unknown): string {
  return typeof value === 'string' && /^[a-z][a-z0-9_]{0,63}$/.exec(value)?.[0] === value
    ? value
    : invalidResponse()
}
function version(value: unknown): string {
  return typeof value === 'string' &&
    value.length <= 32 &&
    /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.exec(value)?.[0] === value
    ? value
    : invalidResponse()
}
function role(value: unknown): Role {
  return value === 'a' || value === 'b' ? value : invalidResponse()
}
export function date(value: unknown): string {
  const s = text(value, 40)
  return /(Z|[+-]\d{2}:\d{2})$/.test(s) && Number.isFinite(Date.parse(s)) ? s : invalidResponse()
}
export function list<T>(value: unknown, parse: (value: unknown) => T): T[] {
  return Array.isArray(value) ? value.map(parse) : invalidResponse()
}
export function parsePair(value: unknown): PairSummary {
  const v = record(value)
  return {
    id: identifier(v.id),
    role: role(v.role),
    member_count: v.member_count === 1 || v.member_count === 2 ? v.member_count : invalidResponse(),
  }
}
export function parseInvitation(value: unknown): Invitation {
  const v = record(value),
    token = text(v.invite_token, 128)
  if (v.role !== 'a' || !/^tw_invite_[A-Za-z0-9_-]+$/.test(token)) return invalidResponse()
  return {
    id: identifier(v.id),
    role: 'a',
    invite_token: token,
    invite_expires_at: date(v.invite_expires_at),
  }
}
export function parseJoined(value: unknown): { id: string; role: 'b' } {
  const v = record(value)
  return v.role === 'b' ? { id: identifier(v.id), role: 'b' } : invalidResponse()
}
export function parseScript(value: unknown): ScriptMetadata {
  const v = record(value),
    roles = list(v.roles, (item) => {
      const r = record(item)
      return { id: role(r.id), name: text(r.name), description: text(r.description) }
    })
  if (
    roles.length !== 2 ||
    new Set(roles.map((r) => r.id)).size !== 2 ||
    !['easy', 'medium', 'hard'].includes(String(v.difficulty)) ||
    !Number.isSafeInteger(v.estimated_minutes) ||
    Number(v.estimated_minutes) <= 0
  )
    return invalidResponse()
  return {
    id: identifier(v.id),
    content_version: version(v.content_version),
    title: text(v.title),
    summary: text(v.summary),
    roles,
    difficulty: v.difficulty as ScriptMetadata['difficulty'],
    estimated_minutes: Number(v.estimated_minutes),
  }
}
export function parseEntry(value: unknown): SaveEntry {
  const v = record(value)
  if (!Number.isSafeInteger(v.version) || Number(v.version) < 0 || typeof v.completed !== 'boolean')
    return invalidResponse()
  return {
    id: identifier(v.id),
    pair_id: identifier(v.pair_id),
    script_id: identifier(v.script_id),
    script_version: version(v.script_version),
    version: Number(v.version),
    scene_id: identifier(v.scene_id),
    completed: v.completed,
    role: role(v.role),
  }
}
export function parseSaveSummary(value: unknown): SaveSummary {
  const v = record(value)
  return { ...parseEntry(v), created_at: date(v.created_at), updated_at: date(v.updated_at) }
}
export function parseSnapshotEntry(value: unknown): SaveEntry {
  const v = record(value)
  // T10.2 consumes only progress from the existing personal projection; rules,
  // device controls, clues, media and dialogue belong to T11, not this entry.
  if (
    !isRecord(v.public) ||
    !isRecord(v.personal) ||
    !isRecord(v.presentation) ||
    !Array.isArray(v.available_actions)
  )
    return invalidResponse()
  return parseEntry(v)
}
