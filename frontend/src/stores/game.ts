import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useIdentityStore } from './identity'
import { gameApi, type Command } from '../services/game'
import { ApiError } from '../services/http'
import { privateSessionLease } from '../services/session-sync'
import { createSaveRecovery, type SyncStatus } from '../services/save-recovery'
import { validParameter, type GameSnapshot } from '../types/game'

function sameSave(a: GameSnapshot, b: GameSnapshot) {
  return (
    a.id === b.id &&
    a.pair_id === b.pair_id &&
    a.role === b.role &&
    a.script_id === b.script_id &&
    a.script_version === b.script_version
  )
}

export const useGameStore = defineStore('game', () => {
  const identity = useIdentityStore(),
    snapshot = ref<GameSnapshot | null>(null),
    busy = ref(false),
    loading = ref(false),
    error = ref(''),
    pending = ref<Command | null>(null),
    realtime = ref<SyncStatus>('idle'),
    confirmed = ref(false),
    canAct = computed(() => realtime.value === 'idle' || confirmed.value)
  let generation = 0,
    readNumber = 0
  let openedSave: string | null = null
  let recovery: ReturnType<typeof createSaveRecovery> | undefined
  function reset() {
    generation++
    readNumber++
    recovery?.stop()
    recovery = undefined
    openedSave = null
    realtime.value = 'idle'
    confirmed.value = false
    snapshot.value = null
    pending.value = null
    busy.value = false
    loading.value = false
    error.value = ''
  }
  watch(() => identity.sessionGeneration, reset, { flush: 'sync' })
  onScopeDispose(reset)

  async function open(id: string) {
    if (!identity.authenticated) return
    if (openedSave === id && realtime.value === 'blocked') return
    if (openedSave !== id) {
      reset()
      openedSave = id
    }
    if (recovery) return recovery.open()
    const g = generation
    const accountId = identity.account?.id
    const session = privateSessionLease()
    const current = () =>
      g === generation && identity.authenticated && identity.account?.id === accountId && session()
    if (!current()) return
    realtime.value = 'connecting'
    recovery = createSaveRecovery(id, {
      current,
      verify: async () => {
        await identity.verifySession()
        return identity.authenticated && !identity.verificationUnavailable
      },
      read: (signal) => load(id, signal),
      hasSnapshot: () => snapshot.value?.id === id,
      accept: (next, initial) => {
        if (!snapshot.value || !sameSave(snapshot.value, next)) return false
        return accept(next, { from_realtime: true, ...(initial ? { restored: true } : {}) })
      },
      status: (state, ready) => {
        realtime.value = state
        confirmed.value = ready
      },
      denied: (code) => {
        blockAccess()
        if (code === 4401) void identity.verifySession()
      },
    })
    await recovery.open()
  }
  function blockAccess() {
    const id = openedSave
    reset()
    openedSave = id
    realtime.value = 'blocked'
  }
  function accept(
    next: GameSnapshot,
    metadata: Partial<Pick<GameSnapshot, 'from_realtime' | 'restored'>> = {},
  ) {
    const version = snapshot.value?.version ?? -1
    if (next.version > version) snapshot.value = { ...next, ...metadata }
    return next.version >= version
  }
  function failure(cause: unknown) {
    const p = cause instanceof ApiError ? cause : new ApiError(0, 'NETWORK_ERROR', true)
    if (p.status === 401) identity.expireSession()
    error.value =
      p.code === 'VERSION_CONFLICT'
        ? '进度已变化，请重新读取，再确认操作。'
        : ((
            {
              POWER_BUDGET_EXCEEDED: '设备总功率超过预算，请重新分配能源。',
              WRONG_TRACK: '当前轨道与已确认信号不符，请与搭档核对。',
              SIGNAL_UNSTABLE: '信号尚未稳定，请交流当前观察并调整设备。',
              ROLE_FORBIDDEN: '当前角色不能执行这项操作。',
              ACTION_UNAVAILABLE: '当前场景暂不可执行此行动。',
            } as Record<string, string>
          )[p.code] ??
          (p.status === 422
            ? '操作未被接受，请检查当前条件和参数；已确认的状态保持不变。'
            : p.message))
    return p
  }
  async function load(id: string, signal?: AbortSignal): Promise<boolean> {
    if (!identity.authenticated) return false
    const old = snapshot.value
    if (old && old.id !== id) reset()
    else if (busy.value && !signal) return false
    const g = generation,
      n = ++readNumber
    if (!signal || !snapshot.value) loading.value = true
    if (!signal || !pending.value) error.value = ''
    try {
      const next = await gameApi.read(id, signal)
      if (signal?.aborted || g !== generation || n !== readNumber) return false
      if (
        next.id !== id ||
        (old && old.id === id && (next.version < old.version || !sameSave(old, next)))
      )
        throw new ApiError(200, 'INVALID_RESPONSE', false)
      return accept(next, signal ? { restored: true } : {})
    } catch (e) {
      if (!signal?.aborted && g === generation && n === readNumber) {
        const denied = e instanceof ApiError && [401, 403, 404].includes(e.status)
        if (!signal || !pending.value || denied) failure(e)
        if (signal && denied && e.status !== 401) blockAccess()
      }
      return false
    } finally {
      if (g === generation && n === readNumber) loading.value = false
    }
  }
  async function submit(actionId: string, args: Record<string, unknown>) {
    const s = snapshot.value
    if (
      !s ||
      !identity.authenticated ||
      !canAct.value ||
      busy.value ||
      loading.value ||
      pending.value
    )
      return
    const action = s.available_actions.find((a) => a.id === actionId)
    if (
      !action ||
      Object.keys(args).length !== action.parameters.length ||
      action.parameters.some((p) => !validParameter(p, args[p.id]))
    ) {
      error.value = '请使用当前可用行动并填写合法参数。'
      return
    }
    pending.value = {
      request_id: crypto.randomUUID(),
      expected_version: s.version,
      kind: action.kind,
      args: structuredClone(args),
    }
    await send()
  }
  async function send() {
    const s = snapshot.value,
      command = pending.value
    if (!s || !command || !identity.authenticated || !canAct.value || busy.value || loading.value)
      return
    const g = generation
    busy.value = true
    error.value = ''
    try {
      const next = await gameApi.submit(s.id, command)
      if (g !== generation) return
      if (!sameSave(s, next) || next.version < s.version)
        throw new ApiError(200, 'INVALID_RESPONSE', false)
      if (!snapshot.value || next.version >= snapshot.value.version) snapshot.value = next
      pending.value = null
    } catch (e) {
      if (g === generation) {
        const p = failure(e)
        if (p.status >= 400 && p.status < 500) pending.value = null
        else error.value += ' 操作结果未知；可手动确认同一请求，勿重新提交其他操作。'
      }
    } finally {
      if (g === generation) busy.value = false
    }
  }
  return {
    snapshot,
    busy,
    loading,
    error,
    pending,
    realtime,
    canAct,
    open,
    load,
    submit,
    retry: send,
    reset,
  }
})
