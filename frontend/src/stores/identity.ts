import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ApiError } from '../services/http'
import { identityApi } from '../services/identity'
import {
  normalizeEmail,
  type Account,
  type CurrentIdentity,
  type LoginInput,
  type RegisterInput,
  type ResetPasswordInput,
  type VerificationPurpose,
} from '../types/api'

type Problem = { code: string; message: string; retryAfter?: number }

function problem(cause: unknown) {
  return cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', true)
}
function uncertain(error: ApiError) {
  return (
    error.status === 0 ||
    error.status >= 500 ||
    (error.status < 300 && error.code === 'INVALID_RESPONSE')
  )
}

export const useIdentityStore = defineStore('identity', () => {
  const account = ref<Account | null>(null)
  const expiresAt = ref<string | null>(null)
  const authenticated = computed(() => account.value !== null)
  const initialized = ref(false)
  const initializing = ref(false)
  const verificationUnavailable = ref(false)
  const busy = ref(false)
  const error = ref<Problem | null>(null)
  const sessionGeneration = ref(0)
  let verifying: Promise<void> | null = null

  function setSession(next: CurrentIdentity | null, rotate = false) {
    account.value = next?.account ?? null
    expiresAt.value = next?.session.expires_at ?? null
    if (rotate) sessionGeneration.value++
  }

  function expireSession(expectedGeneration = sessionGeneration.value) {
    if (expectedGeneration !== sessionGeneration.value || !account.value) return
    setSession(null, true)
    error.value = { code: 'UNAUTHENTICATED', message: '会话已失效，请重新登录。' }
  }

  async function readSession(generation: number) {
    try {
      const result = await identityApi.me()
      if (generation !== sessionGeneration.value) return
      setSession(result, result.account.id !== account.value?.id)
      verificationUnavailable.value = false
      return result
    } catch (cause) {
      if (generation !== sessionGeneration.value) return
      const issue = problem(cause)
      if (issue.status === 401) {
        if (account.value) expireSession(generation)
        verificationUnavailable.value = false
        return null
      }
      verificationUnavailable.value = true
      error.value = {
        code: issue.code,
        message: '暂时无法验证身份，请检查连接后重试。',
      }
    }
  }

  function verifySession() {
    if (verifying) return verifying
    if (busy.value) return Promise.resolve()
    error.value = null
    initializing.value = true
    verifying = readSession(sessionGeneration.value).then(() => {
      initialized.value = true
      initializing.value = false
      verifying = null
    })
    return verifying
  }

  function initialize() {
    return initialized.value ? Promise.resolve() : verifySession()
  }

  async function run(action: (generation: number) => Promise<boolean>) {
    if (busy.value || initializing.value) return false
    const generation = sessionGeneration.value
    busy.value = true
    error.value = null
    try {
      return await action(generation)
    } catch (cause) {
      if (generation === sessionGeneration.value) error.value = problem(cause)
      return false
    } finally {
      busy.value = false
    }
  }

  function requestVerificationCode(email: string, purpose: VerificationPurpose) {
    return run(async (generation) => {
      try {
        await identityApi.requestCode(email, purpose)
        return generation === sessionGeneration.value
      } catch (cause) {
        const issue = problem(cause)
        if (!uncertain(issue)) throw issue
        if (generation === sessionGeneration.value)
          error.value = { code: issue.code, message: '申请结果尚未确认。请先检查邮箱，稍后再试。' }
        return false
      }
    })
  }

  function signIn(email: string, submit: () => Promise<CurrentIdentity>, operation: string) {
    return run(async (generation) => {
      const requestedEmail = normalizeEmail(email)
      const formerAccountId = account.value?.id
      try {
        const result = await submit()
        if (generation !== sessionGeneration.value) return false
        if (result.account.email !== requestedEmail)
          throw new ApiError(200, 'INVALID_RESPONSE', false)
        setSession(result, true)
        initialized.value = true
        verificationUnavailable.value = false
        return true
      } catch (cause) {
        const issue = problem(cause)
        if (!uncertain(issue) || generation !== sessionGeneration.value) throw issue
        // The browser might already have received Set-Cookie. Reconcile once by GET.
        const confirmed = await readSession(generation)
        if (confirmed?.account.email === requestedEmail && confirmed.account.id !== formerAccountId)
          return true
        if (generation === sessionGeneration.value)
          error.value = {
            code: issue.code,
            message: `${operation}结果尚未确认。请先检查当前会话，再决定是否重试。`,
          }
        return false
      }
    })
  }

  function register(input: RegisterInput) {
    return signIn(input.email, () => identityApi.register(input), '注册')
  }
  function login(input: LoginInput) {
    return signIn(input.email, () => identityApi.login(input), '登录')
  }
  function resetPassword(input: ResetPasswordInput) {
    return run(async (generation) => {
      try {
        await identityApi.resetPassword(input)
      } catch (cause) {
        const issue = problem(cause)
        if (!uncertain(issue)) throw issue
        if (generation === sessionGeneration.value) {
          // The old session may have been revoked. Require a verified session for private data.
          setSession(null, true)
          error.value = {
            code: issue.code,
            message: '密码重置结果尚未确认。请尝试用新密码登录，必要时重新申请验证码。',
          }
        }
        return false
      }
      if (generation !== sessionGeneration.value) return false
      setSession(null, true)
      initialized.value = true
      verificationUnavailable.value = false
      return true
    })
  }
  function logout() {
    return run(async (generation) => {
      try {
        await identityApi.logout()
      } catch (cause) {
        const issue = problem(cause)
        if (issue.status !== 401) {
          if (generation === sessionGeneration.value)
            error.value = {
              code: issue.code,
              message: `${issue.message} 服务端会话撤销尚未确认，请再次登出。`,
            }
          return false
        }
      }
      if (generation !== sessionGeneration.value) return false
      setSession(null, true)
      return true
    })
  }

  return {
    account,
    expiresAt,
    authenticated,
    initialized,
    initializing,
    verificationUnavailable,
    busy,
    error,
    sessionGeneration,
    initialize,
    verifySession,
    requestVerificationCode,
    register,
    login,
    resetPassword,
    logout,
    expireSession,
  }
})
