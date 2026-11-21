import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useIdentityStore } from './identity'
import { gameApi, type Command } from '../services/game'
import { ApiError } from '../services/http'
import { privateSessionLease } from '../services/session-sync'
import { createSaveRecovery, type SyncStatus } from '../services/save-recovery'
import {
  canPersistCommand,
  forgetPending,
  markPendingSent,
  pendingScope,
  readPending,
  savePending,
  type PendingScope,
} from '../services/pending'
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
    pendingState = ref<
      | 'idle'
      | 'prepared'
      | 'sending'
      | 'unknown'
      | 'checking'
      | 'missing'
      | 'accepted'
      | 'rejected'
      | 'unavailable'
    >('idle'),
    pendingNotice = ref(''),
    persisted = ref<PendingScope | null>(null),
    recovered = ref(false),
    requiredVersion = ref(-1),
    realtime = ref<SyncStatus>('idle'),
    confirmed = ref(false),
    canAct = computed(
      () =>
        (realtime.value === 'idle' || confirmed.value) &&
        (snapshot.value?.version ?? -1) >= requiredVersion.value,
    ),
    canResubmit = computed(() => {
      const command = pending.value,
        save = snapshot.value
      return !!(
        recovered.value &&
        command &&
        save &&
        pendingState.value === 'missing' &&
        save.version === command.expected_version &&
        save.available_actions.some(
          (action) =>
            action.kind === command.kind && validArgs(action.parameters, command.args, true),
        )
      )
    })
  let generation = 0,
    readNumber = 0
  let openedSave: string | null = null
  let recovery: ReturnType<typeof createSaveRecovery> | undefined
  let restoredJournal = false
  let receiptController: AbortController | undefined
  let nextReceiptCheck = 0
  let remainingReceiptChecks = 0
  function reset() {
    generation++
    readNumber++
    recovery?.stop()
    recovery = undefined
    openedSave = null
    restoredJournal = false
    receiptController?.abort()
    receiptController = undefined
    nextReceiptCheck = 0
    remainingReceiptChecks = 0
    realtime.value = 'idle'
    confirmed.value = false
    snapshot.value = null
    pending.value = null
    persisted.value = null
    recovered.value = false
    pendingState.value = 'idle'
    pendingNotice.value = ''
    requiredVersion.value = -1
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
        if (state === 'paused' && receiptController) {
          receiptController.abort()
          receiptController = undefined
          pendingState.value = 'unknown'
          pendingNotice.value = '核对已暂停，回到游戏后可继续。'
        }
        if (ready) checkRestored()
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
  async function restoreJournal(scope: PendingScope) {
    const g = generation
    const found = await readPending(scope)
    if (g !== generation || !identity.authenticated || !snapshot.value) return
    if (found.status === 'ready') {
      pending.value = found.record.command
      persisted.value = scope
      recovered.value = true
      pendingState.value = found.record.phase === 'prepared' ? 'prepared' : 'unknown'
      pendingNotice.value =
        found.record.phase === 'prepared'
          ? '原操作已在本机保存，尚未标记发送。'
          : '已恢复本机待确认操作，正在等待服务器回执。'
      nextReceiptCheck = 0
      remainingReceiptChecks = 3
      checkRestored()
    } else if (found.status !== 'empty') {
      pendingState.value = 'unavailable'
      pendingNotice.value =
        found.status === 'unavailable'
          ? '无法读取本机待确认记录。请检查存储权限并核对当前进度。'
          : '本机待确认记录已损坏或过期，无法据此确认原操作。请核对当前进度。'
    }
  }
  function checkRestored() {
    if (
      recovered.value &&
      remainingReceiptChecks > 0 &&
      ['unknown', 'prepared', 'missing'].includes(pendingState.value) &&
      Date.now() >= nextReceiptCheck &&
      canQueryPending()
    ) {
      remainingReceiptChecks--
      void queryPending()
    }
  }
  async function clearPending(state: 'accepted' | 'rejected' | 'unavailable', message: string) {
    const command = pending.value
    const g = generation
    const cleared =
      !persisted.value || !command || (await forgetPending(persisted.value, command.request_id))
    if (g !== generation) return
    pendingNotice.value = cleared ? message : message + ' 本机记录未能清除。'
    pending.value = null
    persisted.value = null
    recovered.value = false
    pendingState.value = state
  }
  function canQueryPending() {
    return (
      persisted.value &&
      identity.authenticated &&
      !busy.value &&
      !receiptController &&
      !document.hidden &&
      navigator.onLine
    )
  }
  async function queryPending() {
    const s = snapshot.value,
      command = pending.value
    if (!s || !command || !canQueryPending()) return
    const g = generation
    const controller = new AbortController()
    receiptController = controller
    nextReceiptCheck = Date.now() + 15000
    pendingState.value = 'checking'
    pendingNotice.value = '正在向服务器核对原操作回执。'
    try {
      const version = await gameApi.receipt(s.id, command, controller.signal)
      if (g !== generation || controller.signal.aborted) return
      if (version === null) {
        pendingState.value = 'missing'
        pendingNotice.value = '暂未查到回执，原操作可能仍在处理。可继续核对原 UUID。'
        return
      }
      requiredVersion.value = version
      await clearPending('accepted', '服务器已确认原操作。')
      if (g !== generation) return
      if ((snapshot.value?.version ?? -1) < version) {
        if (recovery) void recovery.open()
        else void load(s.id)
      }
    } catch (e) {
      if (g !== generation || controller.signal.aborted) return
      if (e instanceof ApiError && e.status === 401) {
        identity.expireSession()
        return
      }
      if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
        blockAccess()
        return
      }
      pendingState.value = 'unknown'
      pendingNotice.value = '暂时无法核对回执，已保留原 UUID。'
    } finally {
      if (receiptController === controller) receiptController = undefined
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
      const current = accept(next, signal ? { restored: true } : {})
      if (openedSave === id && current && identity.account) {
        if (!restoredJournal) {
          restoredJournal = true
          await restoreJournal(pendingScope(identity.account.id, next))
        } else checkRestored()
      }
      return current
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
  function validArgs(
    parameters: GameSnapshot['available_actions'][number]['parameters'],
    args: Record<string, unknown>,
    choices = false,
  ) {
    return (
      Object.keys(args).length === parameters.length &&
      parameters.every((p) => (!choices || p.choices.length > 0) && validParameter(p, args[p.id]))
    )
  }
  async function submit(actionId: string, args: Record<string, unknown>) {
    const s = snapshot.value,
      account = identity.account
    if (
      !s ||
      !account ||
      !identity.authenticated ||
      !canAct.value ||
      busy.value ||
      loading.value ||
      pending.value
    )
      return
    const action = s.available_actions.find((a) => a.id === actionId)
    if (!action || !validArgs(action.parameters, args)) {
      error.value = '请使用当前可用行动并填写合法参数。'
      return
    }
    const command: Command = {
      request_id: crypto.randomUUID(),
      expected_version: s.version,
      kind: action.kind,
      args: structuredClone(args),
    }
    const scope = pendingScope(account.id, s)
    const eligible = canPersistCommand(command) && validArgs(action.parameters, args, true)
    if (eligible) {
      const g = generation
      busy.value = true
      const outcome = await savePending(scope, command)
      if (g !== generation) return
      if (outcome === 'existing') {
        await restoreJournal(scope)
        if (g !== generation) return
        busy.value = false
        checkRestored()
        return
      }
      busy.value = false
      if (outcome !== 'saved') {
        pendingState.value = 'unavailable'
        pendingNotice.value =
          outcome === 'full'
            ? '本机待确认记录已达上限，本次操作未发送。请先处理已有记录。'
            : '本机无法保存待确认记录，本次操作未发送。请检查存储权限或空间。'
        return
      }
      persisted.value = scope
    }
    pending.value = command
    pendingState.value = 'prepared'
    pendingNotice.value = eligible
      ? '操作已保存，尚未发送。'
      : '此操作仅在本页保留，刷新后无法自动确认。'
    await send()
  }
  async function send(reconciliation = false) {
    const s = snapshot.value,
      command = pending.value
    if (
      !s ||
      !command ||
      !identity.authenticated ||
      !canAct.value ||
      busy.value ||
      loading.value ||
      receiptController
    )
      return
    const g = generation
    busy.value = true
    try {
      if (persisted.value) {
        const marked = await markPendingSent(persisted.value, command)
        if (g !== generation) return
        if (!marked) {
          pendingNotice.value = '本机记录已变化或无法标记，本次未发送。可核对原操作或清除本机记录。'
          return
        }
        if (!canAct.value || !identity.authenticated || (reconciliation && !canResubmit.value)) {
          pendingNotice.value = '同步或可用操作已变化，本次未发送。原 UUID 已保留。'
          return
        }
      }
      error.value = ''
      pendingState.value = 'sending'
      pendingNotice.value = persisted.value
        ? '正在等待服务器回执。'
        : '此操作仅在本页保留，刷新后无法自动确认。'
      const next = await gameApi.submit(s.id, command)
      if (g !== generation) return
      if (!sameSave(s, next) || next.version < s.version)
        throw new ApiError(200, 'INVALID_RESPONSE', false)
      if (reconciliation) accept(next, { restored: true })
      else if (!snapshot.value || next.version >= snapshot.value.version) snapshot.value = next
      await clearPending('accepted', '服务器已确认原操作。')
    } catch (e) {
      if (g === generation) {
        const p = failure(e)
        if (g !== generation) return
        if ([400, 409, 422].includes(p.status) && p.code !== 'INVALID_RESPONSE') {
          await clearPending('rejected', '服务器明确拒绝了这次操作。')
        } else {
          pendingState.value = 'unknown'
          pendingNotice.value = persisted.value
            ? '操作结果未知，原 UUID 已保留。'
            : '操作结果未知，仅可在本页确认。'
          error.value += ' 操作结果未知；可手动确认同一请求，勿重新提交其他操作。'
        }
      }
    } finally {
      if (g === generation) busy.value = false
    }
  }
  function retry() {
    return recovered.value ? queryPending() : send()
  }
  function resubmit() {
    if (canResubmit.value) return send(true)
  }
  async function discardPending() {
    if (!pending.value || busy.value || receiptController) return
    const g = generation
    busy.value = true
    await clearPending('unavailable', '已停止本机核对。服务器操作结果仍未确认，请核对当前进度。')
    if (g === generation) busy.value = false
  }
  return {
    snapshot,
    busy,
    loading,
    error,
    pending,
    pendingState,
    pendingNotice,
    persisted,
    recovered,
    canResubmit,
    realtime,
    canAct,
    open,
    load,
    submit,
    retry,
    resubmit,
    discardPending,
    reset,
  }
})
