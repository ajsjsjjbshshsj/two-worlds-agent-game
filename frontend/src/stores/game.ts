import { defineStore } from 'pinia'
import { onScopeDispose, ref, watch } from 'vue'
import { useIdentityStore } from './identity'
import { gameApi, type Command } from '../services/game'
import { ApiError } from '../services/http'
import { privateSessionLease } from '../services/session-sync'
import { connectSaveSocket } from '../services/websocket'
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
    realtime = ref<'idle' | 'connecting' | 'live' | 'offline'>('idle')
  let generation = 0,
    readNumber = 0
  let openedSave: string | null = null
  let disconnect: (() => void) | undefined
  function reset() {
    generation++
    readNumber++
    disconnect?.()
    disconnect = undefined
    openedSave = null
    realtime.value = 'idle'
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
    if (openedSave !== id) {
      reset()
      openedSave = id
    }
    const g = generation
    await load(id)
    const initial = snapshot.value
    if (
      g !== generation ||
      !identity.authenticated ||
      loading.value ||
      disconnect ||
      !initial ||
      initial.id !== id
    )
      return

    const accountId = identity.account?.id
    const session = privateSessionLease()
    let close: () => void
    const current = () =>
      close === disconnect &&
      g === generation &&
      identity.authenticated &&
      identity.account?.id === accountId &&
      session()
    if (g !== generation || !session()) return
    realtime.value = 'connecting'
    try {
      close = connectSaveSocket(
        id,
        current,
        (next) => {
          if (!sameSave(initial, next)) return
          realtime.value = 'live'
          if (snapshot.value && next.version > snapshot.value.version)
            snapshot.value = { ...next, from_realtime: true }
        },
        (code) => {
          disconnect = undefined
          realtime.value = 'offline'
          if (code === 4401) void identity.verifySession()
        },
      )
      disconnect = close
    } catch {
      realtime.value = 'offline'
    }
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
  async function load(id: string) {
    if (!identity.authenticated) return
    const old = snapshot.value
    if (old && old.id !== id) reset()
    else if (busy.value) return
    const g = generation,
      n = ++readNumber
    loading.value = true
    error.value = ''
    try {
      const next = await gameApi.read(id)
      if (g !== generation || n !== readNumber) return
      if (
        next.id !== id ||
        (old && old.id === id && (next.version < old.version || !sameSave(old, next)))
      )
        throw new ApiError(200, 'INVALID_RESPONSE', false)
      if (!snapshot.value || next.version > snapshot.value.version) snapshot.value = next
    } catch (e) {
      if (g === generation && n === readNumber) failure(e)
    } finally {
      if (g === generation && n === readNumber) loading.value = false
    }
  }
  async function submit(actionId: string, args: Record<string, unknown>) {
    const s = snapshot.value
    if (!s || !identity.authenticated || busy.value || loading.value || pending.value) return
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
    if (!s || !command || !identity.authenticated || busy.value || loading.value) return
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
    open,
    load,
    submit,
    retry: send,
    reset,
  }
})
