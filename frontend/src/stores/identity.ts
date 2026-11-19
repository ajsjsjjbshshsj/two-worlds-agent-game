import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'
import { ApiError } from '../services/http'
import { identityApi } from '../services/identity'
import {
  createSessionSync,
  registerPrivateSessionGuard,
  withCookieWriteLock,
} from '../services/session-sync'
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
  const sessionSuspended = ref(false)
  const authenticated = computed(() => account.value !== null && !sessionSuspended.value)
  const initialized = ref(false)
  const initializing = ref(false)
  const verificationUnavailable = ref(false)
  const busy = ref(false)
  const error = ref<Problem | null>(null)
  const sessionGeneration = ref(0)
  let verifying: { epoch: number; promise: Promise<void> } | null = null
  let sync: ReturnType<typeof createSessionSync> | undefined
  let observed: ReturnType<ReturnType<typeof createSessionSync>['snapshot']> | undefined
  let verificationEpoch = 0
  let expiryTimer: number | undefined

  function suspend() {
    if (sessionSuspended.value) return
    sessionSuspended.value = true
    sessionGeneration.value++
  }

  function observe() {
    if (!sync) return false
    const next = sync.snapshot()
    const changed = next.key !== observed?.key
    if (next.nextExpiry !== observed?.nextExpiry) scheduleLeaseExpiry(next.nextExpiry)
    observed = next
    if (changed) {
      verificationEpoch++
      verificationUnavailable.value = false
      suspend()
    }
    return changed
  }

  function scheduleLeaseExpiry(until: number | undefined) {
    window.clearTimeout(expiryTimer)
    if (until !== undefined)
      expiryTimer = window.setTimeout(peerChanged, Math.max(0, until - Date.now()) + 1)
  }

  function peerChanged() {
    if (observe() && !observed?.changing && !busy.value) void verifySession()
  }

  let disposeSync: (() => void) | undefined
  onScopeDispose(() => disposeSync?.())

  function enableSessionSync() {
    if (sync) return
    sync = createSessionSync(peerChanged)
    observed = sync.snapshot()
    if (observed.changing) {
      suspend()
      scheduleLeaseExpiry(observed.nextExpiry)
    }
    const unbind = registerPrivateSessionGuard(() => {
      peerChanged()
      return authenticated.value ? sessionGeneration.value : null
    })
    const resume = () => {
      if (!document.hidden) void verifySession()
    }
    const pageShown = (event: PageTransitionEvent) => {
      if (event.persisted) resume()
    }
    const pageHidden = (event: PageTransitionEvent) => {
      if (!event.persisted) return
      verificationEpoch++
      suspend()
    }
    window.addEventListener('focus', resume)
    window.addEventListener('pageshow', pageShown)
    window.addEventListener('pagehide', pageHidden)
    document.addEventListener('visibilitychange', resume)
    disposeSync = () => {
      unbind()
      sync?.close()
      window.clearTimeout(expiryTimer)
      window.removeEventListener('focus', resume)
      window.removeEventListener('pageshow', pageShown)
      window.removeEventListener('pagehide', pageHidden)
      document.removeEventListener('visibilitychange', resume)
    }
  }

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

  async function readSession(generation: number, valid = () => true) {
    try {
      const result = await identityApi.me()
      if (!valid() || generation !== sessionGeneration.value) return
      setSession(result, result.account.id !== account.value?.id)
      verificationUnavailable.value = false
      return result
    } catch (cause) {
      if (!valid() || generation !== sessionGeneration.value) return
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

  function verifySession(keepError = false) {
    observe()
    if (verifying?.epoch === verificationEpoch) return verifying.promise
    if (busy.value || observed?.changing) return Promise.resolve()
    if (sync) suspend()
    if (!keepError) error.value = null
    const epoch = verificationEpoch
    const current = () => {
      observe()
      return epoch === verificationEpoch
    }
    initializing.value = true
    const promise = readSession(sessionGeneration.value, current).then((result) => {
      if (verifying?.epoch !== epoch) return
      verifying = null
      initializing.value = false
      if (!current()) {
        if (!observed?.changing) void verifySession(keepError)
        return
      }
      initialized.value = true
      if (result !== undefined) sessionSuspended.value = false
    })
    verifying = { epoch, promise }
    return promise
  }

  function initialize() {
    peerChanged()
    return initialized.value && !sessionSuspended.value ? Promise.resolve() : verifySession()
  }

  async function run(action: (generation: number) => Promise<boolean>, changesSession = false) {
    peerChanged()
    if (busy.value || initializing.value || observed?.changing) return false
    busy.value = true
    error.value = null
    const finish = changesSession ? sync?.begin() : undefined
    observe()
    const generation = sessionGeneration.value
    try {
      const execute = () => action(generation)
      return await (finish ? withCookieWriteLock(execute) : execute())
    } catch (cause) {
      if (generation === sessionGeneration.value) error.value = problem(cause)
      return false
    } finally {
      finish?.()
      observe()
      busy.value = false
      if (sync && sessionSuspended.value && !observed?.changing) await verifySession(true)
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
    const requestedEmail = normalizeEmail(email)
    return run(async (generation) => {
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
    }, true).then(
      (ok) => ok && (!sync || (authenticated.value && account.value?.email === requestedEmail)),
    )
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
          // A lost response leaves the browser's current session unconfirmed.
          if (account.value) suspend()
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
    }, true)
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
    }, true)
  }

  return {
    account,
    expiresAt,
    authenticated,
    sessionSuspended,
    enableSessionSync,
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
