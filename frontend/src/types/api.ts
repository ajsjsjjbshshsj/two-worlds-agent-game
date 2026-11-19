import { ApiError, isRecord } from '../services/http'

export interface Account {
  readonly id: string
  readonly email: string
  readonly display_name: string
}
export interface CurrentIdentity {
  readonly account: Account
  readonly session: { readonly expires_at: string }
}

export type VerificationPurpose = 'register' | 'reset'
export interface LoginInput {
  email: string
  password: string
}
export interface RegisterInput extends LoginInput {
  code: string
  display_name: string
}
export interface ResetPasswordInput {
  email: string
  code: string
  new_password: string
}

export function normalizeEmail(value: string) {
  return value.trim().toLowerCase()
}

export function validEmail(value: string) {
  return value.length <= 254 && /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/.exec(value)?.[0] === value
}

function invalid(): never {
  throw new ApiError(200, 'INVALID_RESPONSE', false)
}
function text(value: unknown, max: number): string {
  return typeof value === 'string' && value.length > 0 && Array.from(value).length <= max
    ? value
    : invalid()
}
export function currentIdentity(value: unknown): CurrentIdentity {
  if (!isRecord(value) || !isRecord(value.account) || !isRecord(value.session)) return invalid()
  const expires = text(value.session.expires_at, 64)
  const email = text(value.account.email, 254)
  if (
    !/(Z|[+-]\d{2}:\d{2})$/.test(expires) ||
    !Number.isFinite(Date.parse(expires)) ||
    email !== normalizeEmail(email) ||
    !validEmail(email)
  )
    return invalid()
  return {
    account: {
      id: text(value.account.id, 128),
      email,
      display_name: text(value.account.display_name, 40),
    },
    session: { expires_at: expires },
  }
}
