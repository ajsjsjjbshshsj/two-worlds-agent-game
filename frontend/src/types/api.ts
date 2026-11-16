import { ApiError, isRecord } from '../services/http'

export interface Account {
  readonly id: string
  readonly display_name: string
}
// Local reminder metadata only; account_id is a label, never authentication.
export interface PendingRecovery {
  readonly account_id: string
  readonly display_name: string
  readonly created_at: string
  readonly pending: true
}
export interface Session {
  readonly expires_at: string
}
export interface SessionCredential extends Session {
  readonly token: string
}
export interface CreatedIdentity {
  readonly account: Account
  readonly session: SessionCredential
  readonly recovery_key: string
}
export interface RecoveredIdentity {
  readonly account: Account
  readonly session: SessionCredential
}
export interface CurrentIdentity {
  readonly account: Account
  readonly session: Session
}
export interface CreateAccount {
  readonly display_name: string
}
export interface RecoverSession {
  readonly recovery_key: string
}

function invalid(): never {
  throw new ApiError(200, 'INVALID_RESPONSE', false)
}
function text(value: unknown, max = 128): string {
  return typeof value === 'string' && value.length > 0 && Array.from(value).length <= max
    ? value
    : invalid()
}
export function currentIdentity(value: unknown): CurrentIdentity {
  if (!isRecord(value) || !isRecord(value.account) || !isRecord(value.session)) return invalid()
  const expires = text(value.session.expires_at)
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(expires) || !Number.isFinite(Date.parse(expires)))
    return invalid()
  return {
    account: { id: text(value.account.id), display_name: text(value.account.display_name, 40) },
    session: { expires_at: expires },
  }
}
export function recoveredIdentity(value: unknown): RecoveredIdentity {
  const current = currentIdentity(value)
  if (!isRecord(value) || !isRecord(value.session)) return invalid()
  const token = text(value.session.token)
  if (/\s/.test(token)) return invalid()
  return { ...current, session: { ...current.session, token } }
}
export function createdIdentity(value: unknown): CreatedIdentity {
  const recovered = recoveredIdentity(value)
  if (!isRecord(value)) return invalid()
  return { ...recovered, recovery_key: text(value.recovery_key) }
}
