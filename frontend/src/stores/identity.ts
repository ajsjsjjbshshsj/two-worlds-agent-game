import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Account, CreateAccount, PendingRecovery, RecoverSession } from '../types/api'
import { createdIdentity, currentIdentity, recoveredIdentity } from '../types/api'
import { ApiError, createHttpClient, isRecord } from '../services/http'

export const SESSION_KEY = 'twoworlds.session.token'
export const PENDING_RECOVERY_PREFIX = 'twoworlds.recovery.pending.v1.'
function validAccountId(value: unknown): value is string {
  return typeof value === 'string' && /^[a-z][a-z0-9_]{0,63}$/.exec(value)?.[0] === value
}
function parsePending(key: string, raw: string | null): PendingRecovery | null {
  if (!raw || raw.length > 2048) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (
      !isRecord(value) ||
      Object.keys(value).sort().join(',') !== 'account_id,created_at,display_name,pending' ||
      !validAccountId(value.account_id) ||
      key !== PENDING_RECOVERY_PREFIX + value.account_id ||
      typeof value.display_name !== 'string' ||
      !value.display_name.trim() ||
      Array.from(value.display_name).length > 40 ||
      typeof value.created_at !== 'string' ||
      value.created_at.length > 40 ||
      !/(Z|[+-]\d{2}:\d{2})$/.test(value.created_at) ||
      !Number.isFinite(Date.parse(value.created_at)) ||
      value.pending !== true
    )
      return null
    return {
      account_id: value.account_id,
      display_name: value.display_name,
      created_at: value.created_at,
      pending: true,
    }
  } catch {
    return null
  }
}
export const useIdentityStore = defineStore('identity', () => {
  const account = ref<Account | null>(null)
  const token = ref<string | null>(null)
  const expiresAt = ref<string | null>(null)
  const initializing = ref(false)
  const initialized = ref(false)
  const busy = ref(false)
  const error = ref<{ message: string; code: string } | null>(null)
  const storageWarning = ref<string | null>(null)
  const pendingRecoveries = ref<PendingRecovery[]>([])
  const pendingStorageWarning = ref<string | null>(null)
  const legacyPendingWarning = ref<string | null>(null)
  const http = createHttpClient()
  function storageWarningMessage() {
    storageWarning.value = '当前浏览器无法保存会话，刷新后可能需要恢复密钥。请妥善保存密钥。'
  }
  function loadPendingRecoveries() {
    const records = new Map(pendingRecoveries.value.map((record) => [record.account_id, record]))
    try {
      for (let index = 0; index < localStorage.length; index++) {
        const key = localStorage.key(index)
        if (!key?.startsWith(PENDING_RECOVERY_PREFIX)) continue
        const raw = localStorage.getItem(key)
        if (raw === null) continue
        const record = parsePending(key, raw)
        if (record) records.set(record.account_id, record)
        else
          pendingStorageWarning.value =
            '部分恢复提醒格式无效，已保留原记录但未读取。请核对自行保存的密钥。'
      }
    } catch {
      pendingStorageWarning.value =
        '无法读取本机恢复提醒；本页仍保留内存提醒，但不能保证重开后可见。请妥善保存密钥。'
    }
    pendingRecoveries.value = [...records.values()].sort(
      (a, b) =>
        a.created_at.localeCompare(b.created_at) || a.account_id.localeCompare(b.account_id),
    )
  }
  function addPendingRecovery(account: Account) {
    loadPendingRecoveries()
    const record = pendingRecoveries.value.find((record) => record.account_id === account.id) ?? {
      account_id: account.id,
      display_name: account.display_name,
      created_at: new Date().toISOString(),
      pending: true as const,
    }
    if (!validAccountId(record.account_id)) throw new ApiError(200, 'INVALID_RESPONSE', false)
    if (!pendingRecoveries.value.some((item) => item.account_id === record.account_id))
      pendingRecoveries.value.push(record)
    try {
      localStorage.setItem(PENDING_RECOVERY_PREFIX + record.account_id, JSON.stringify(record))
    } catch {
      pendingStorageWarning.value =
        '无法保存恢复提醒；本页仍保留内存提醒，刷新或关闭后可能丢失。请现在妥善保存密钥。'
    }
  }
  function confirmRecoveryKeySaved(accountId: string) {
    if (!validAccountId(accountId)) return
    loadPendingRecoveries()
    if (!pendingRecoveries.value.some((record) => record.account_id === accountId)) return
    pendingRecoveries.value = pendingRecoveries.value.filter(
      (record) => record.account_id !== accountId,
    )
    try {
      localStorage.removeItem(PENDING_RECOVERY_PREFIX + accountId)
    } catch {
      pendingStorageWarning.value =
        '本次确认只在本页生效，旧提醒后续读取或重开后可能再次出现。请检查浏览器存储设置。'
    }
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
      addPendingRecovery(response.account)
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
      // Possession proves recovery only for this account, not other reminders.
      if (account.value) confirmRecoveryKeySaved(account.value.id)
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
    loadPendingRecoveries()
    try {
      if (sessionStorage.getItem('twoworlds.recovery.pending') === '1') {
        legacyPendingWarning.value =
          '检测到旧版未关联身份的未确认提醒，无法确定所属身份。请核对曾保存的恢复密钥；系统无法重建或显示旧密钥。'
      }
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
    pendingRecoveries,
    pendingStorageWarning,
    legacyPendingWarning,
    currentRecoveryKeyPending: computed(
      () =>
        !!account.value &&
        pendingRecoveries.value.some((record) => record.account_id === account.value?.id),
    ),
    confirmRecoveryKeySaved,
    authenticated: computed(() => !!account.value && !!token.value),
    create,
    recover,
    initialize,
    verifySession,
    logout,
  }
})
