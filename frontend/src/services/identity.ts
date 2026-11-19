import { ApiError, createHttpClient, isRecord } from './http'
import {
  currentIdentity,
  normalizeEmail,
  type LoginInput,
  type RegisterInput,
  type ResetPasswordInput,
  type VerificationPurpose,
} from '../types/api'

const http = createHttpClient()

export const identityApi = {
  async me() {
    return currentIdentity(await http.request('/api/me', { expectedStatus: 200 }))
  },
  async requestCode(email: string, purpose: VerificationPurpose) {
    const result = await http.request('/api/verification-codes', {
      method: 'POST',
      expectedStatus: 202,
      body: { email: normalizeEmail(email), purpose },
    })
    if (!isRecord(result) || result.status !== 'accepted')
      throw new ApiError(202, 'INVALID_RESPONSE', false)
  },
  async register({ email, password, code, display_name }: RegisterInput) {
    return currentIdentity(
      await http.request('/api/accounts', {
        method: 'POST',
        expectedStatus: 200,
        body: { email: normalizeEmail(email), password, code, display_name: display_name.trim() },
      }),
    )
  },
  async login({ email, password }: LoginInput) {
    return currentIdentity(
      await http.request('/api/sessions', {
        method: 'POST',
        expectedStatus: 200,
        body: { email: normalizeEmail(email), password },
      }),
    )
  },
  async resetPassword({ email, code, new_password }: ResetPasswordInput) {
    await http.request('/api/password-resets', {
      method: 'POST',
      expectedStatus: 204,
      body: { email: normalizeEmail(email), code, new_password },
    })
  },
  async logout() {
    await http.request('/api/sessions/current', { method: 'DELETE', expectedStatus: 204 })
  },
}
