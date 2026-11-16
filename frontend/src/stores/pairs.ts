import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useIdentityStore } from './identity'
import { pairApi } from '../services/pairs'
import { ApiError } from '../services/http'
import type { PairSummary, Invitation } from '../types/resources'

export const usePairsStore = defineStore('pairs', () => {
  const identity = useIdentityStore(),
    pairs = ref<PairSummary[]>([]),
    invitation = ref<Invitation | null>(null)
  // Invitation secrets live only in this instance. Never use storage or logs.
  const incoming = ref(''),
    inviteHint = ref(
      '打开搭档发来的原邀请链接后，可在这里确认加入。刷新页面会丢失尚未使用的邀请，请重新打开原链接。',
    )
  const error = ref<{ code: string; message: string } | null>(null),
    notice = ref(''),
    loading = ref(false),
    busy = ref(false)
  let epoch = 0,
    listRequest = 0
  watch(
    () => identity.token,
    (next, previous) => {
      epoch++
      listRequest++
      pairs.value = []
      invitation.value = null
      error.value = null
      notice.value = ''
      loading.value = false
      busy.value = false
      if (!next && previous) incoming.value = ''
    },
    { flush: 'sync' },
  )
  function captureInvite(fragment = window.location.hash) {
    if (!fragment.startsWith('#invite=')) return
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search,
    )
    const value = fragment.slice(8)
    if (/^tw_invite_[A-Za-z0-9_-]{1,118}$/.exec(value)?.[0] === value) {
      incoming.value = value
      inviteHint.value = '邀请已读取并从地址栏移除。请确认使用当前身份加入，加入后固定为角色 B。'
    } else {
      incoming.value = ''
      inviteHint.value = '邀请格式无法识别，请重新打开搭档发来的原链接。'
    }
  }
  function fail(cause: unknown) {
    const problem = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', true)
    if (problem.status === 401) identity.expireSession()
    error.value = { code: problem.code, message: problem.message }
  }
  async function load() {
    const token = identity.token
    if (!token || !identity.authenticated) return
    const current = epoch,
      request = ++listRequest
    loading.value = true
    error.value = null
    try {
      const result = await pairApi.list(token)
      if (current === epoch && request === listRequest) {
        pairs.value = result
        if (
          invitation.value &&
          !result.some(
            (pair) =>
              pair.id === invitation.value?.id && pair.role === 'a' && pair.member_count === 1,
          )
        )
          invitation.value = null
      }
    } catch (cause) {
      if (current === epoch && request === listRequest) fail(cause)
    } finally {
      if (current === epoch && request === listRequest) loading.value = false
    }
  }
  async function issue(id?: string) {
    const token = identity.token
    if (!token || !identity.authenticated || busy.value) return null
    const current = epoch
    busy.value = true
    error.value = null
    notice.value = ''
    // A refresh result may be unknown; discard the old displayed capability now.
    if (id) invitation.value = null
    try {
      const result = id ? await pairApi.refresh(token, id) : await pairApi.create(token)
      if (current !== epoch) return null
      invitation.value = result
      notice.value = id ? '新邀请已生成，旧链接已失效。' : '房间已创建，请把邀请链接交给搭档。'
      await load()
      return current === epoch ? result.id : null
    } catch (cause) {
      if (current === epoch) {
        fail(cause)
        if (!(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500)
          notice.value =
            '操作结果尚未确认。请先刷新房间列表，避免重复创建；邀请刷新结果不明时请重新生成。'
      }
      return null
    } finally {
      if (current === epoch) busy.value = false
    }
  }
  async function join() {
    if (!identity.authenticated || !identity.token || busy.value || !incoming.value) return null
    if (identity.currentRecoveryKeyPending) {
      fail(new ApiError(0, 'KEY_NOT_CONFIRMED', false))
      return null
    }
    const current = epoch
    busy.value = true
    error.value = null
    try {
      const result = await pairApi.join(identity.token, incoming.value)
      if (current !== epoch) return null
      incoming.value = ''
      await load()
      return current === epoch ? result.id : null
    } catch (cause) {
      if (current === epoch) fail(cause)
      return null
    } finally {
      if (current === epoch) busy.value = false
    }
  }
  return {
    pairs,
    invitation,
    inviteHint,
    error,
    notice,
    loading,
    busy,
    hasIncomingInvite: computed(() => !!incoming.value),
    captureInvite,
    load,
    create: () => issue(),
    refresh: (id: string) => issue(id),
    join,
  }
})
