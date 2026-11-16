import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Account, CreateAccount, RecoverSession } from '../types/api'
import { createdIdentity, currentIdentity, recoveredIdentity } from '../types/api'
import { ApiError, createHttpClient } from '../services/http'

export const SESSION_KEY = 'twoworlds.session.token'
export const useIdentityStore = defineStore('identity', () => {
  const account = ref<Account | null>(null)
  const token = ref<string | null>(null)
  const expiresAt = ref<string | null>(null)
  const initializing = ref(false)
  const initialized = ref(false)
  const busy = ref(false)
  const error = ref<{ message: string; code: string } | null>(null)
  const storageWarning = ref<string | null>(null)
  const http = createHttpClient()
  function storageWarningMessage() {
    storageWarning.value = '当前浏览器无法保存会话，刷新后可能需要恢复密钥。请妥善保存密钥。'
  }
  function clear() {
    token.value = null
    account.value = null
    expiresAt.value = null
    try {
      sessionStorage.removeItem(SESSION_KEY)
    } catch {
      storageWarningMessage()
    }
  }
  function accept(value: ReturnType<typeof recoveredIdentity>) {
    token.value = value.session.token
    account.value = value.account
    expiresAt.value = value.session.expires_at
    try {
      sessionStorage.setItem(SESSION_KEY, value.session.token)
    } catch {
      storageWarningMessage()
    }
  }
  function failure(value: unknown): ApiError {
    return value instanceof ApiError ? value : new ApiError(0, 'NETWORK_ERROR', true)
  }
  async function create(name: string): Promise<string | null> {
    if (busy.value || initializing.value) return null
    busy.value = true
    error.value = null
    try {
      const response = createdIdentity(
        await http.request<unknown>('/api/accounts', {
          method: 'POST',
          body: { display_name: name } satisfies CreateAccount,
        }),
      )
      accept(response)
      // The key is returned to the page only; never part of Pinia state or storage.
      return response.recovery_key
    } catch (cause) {
      const problem = failure(cause)
      error.value = {
        code: problem.code,
        message:
          problem.status === 0 || problem.status >= 500 || problem.code === 'INVALID_RESPONSE'
            ? '创建结果尚未确认，服务端可能已创建身份。请勿连续重试；未收到密钥的身份无法找回。'
            : problem.message,
      }
      return null
    } finally {
      busy.value = false
    }
  }
  async function recover(key: string): Promise<void> {
    if (busy.value || initializing.value) return
    busy.value = true
    error.value = null
    try {
      accept(
        recoveredIdentity(
          await http.request<unknown>('/api/sessions/recover', {
            method: 'POST',
            body: { recovery_key: key } satisfies RecoverSession,
          }),
        ),
      )
    } catch (cause) {
      const problem = failure(cause)
      if (problem.status === 401) clear()
      error.value = { code: problem.code, message: problem.message }
    } finally {
      busy.value = false
    }
  }
  async function initialize(): Promise<void> {
    if (initialized.value || initializing.value) return
    try {
      token.value = sessionStorage.getItem(SESSION_KEY)
    } catch {
      storageWarningMessage()
    }
    if (token.value && (token.value.length > 128 || /\s/.test(token.value))) clear()
    await verifySession()
  }
  async function verifySession(): Promise<void> {
    if (initializing.value || busy.value) return
    initializing.value = true
    error.value = null
    try {
      if (token.value) {
        const response = currentIdentity(
          await http.request<unknown>('/api/me', { token: token.value }),
        )
        account.value = response.account
        expiresAt.value = response.session.expires_at
      }
    } catch (cause) {
      const problem = failure(cause)
      if (problem.status === 401) clear()
      error.value = { code: problem.code, message: problem.message }
    } finally {
      initializing.value = false
      initialized.value = true
    }
  }
  async function logout(): Promise<void> {
    if (busy.value || initializing.value || !token.value) return
    busy.value = true
    error.value = null
    try {
      await http.request<void>('/api/sessions/current', { method: 'DELETE', token: token.value })
      clear()
    } catch (cause) {
      const problem = failure(cause)
      if (problem.status === 401) clear()
      error.value = {
        code: problem.code,
        message:
          problem.status === 401
            ? problem.message
            : '服务端会话撤销尚未确认，当前身份仍保留。请检查连接后再次登出。',
      }
    } finally {
      busy.value = false
    }
  }
  return {
    account,
    token,
    expiresAt,
    initializing,
    initialized,
    busy,
    error,
    storageWarning,
    authenticated: computed(() => !!account.value && !!token.value),
    create,
    recover,
    initialize,
    verifySession,
    logout,
  }
})
