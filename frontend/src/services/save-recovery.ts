import type { GameSnapshot } from '../types/game'
import { connectSaveSocket } from './websocket'

const RETRY_MS = [500, 1000, 2000, 4000, 8000, 15000]
const HTTP_INTERVAL = 15000
const SOCKET_DEADLINE = 25000

export function retryDelay(attempt: number) {
  return Math.round(RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)]! * (0.8 + Math.random() * 0.4))
}

export type SyncStatus = 'idle' | 'connecting' | 'live' | 'http' | 'offline' | 'paused' | 'blocked'

interface RecoveryOptions {
  current: () => boolean
  verify: () => Promise<boolean>
  read: (signal: AbortSignal) => Promise<boolean>
  hasSnapshot: () => boolean
  accept: (snapshot: GameSnapshot, initial: boolean) => boolean
  status: (status: SyncStatus, confirmed: boolean) => void
  denied: (code: number) => void
}

export function createSaveRecovery(id: string, options: RecoveryOptions) {
  let stopped = false
  let paused = true
  let pageHidden = false
  let needsVerification = false
  let live = false
  let state: SyncStatus = 'connecting'
  let confirmationGeneration = 0
  let activityGeneration = 0
  let failures = 0
  let closeSocket: (() => void) | undefined
  let request: { controller: AbortController; done: Promise<void> } | undefined
  let retryTimer: number | undefined
  let pollTimer: number | undefined
  let watchdog: number | undefined

  const available = () => !document.hidden && !pageHidden && navigator.onLine
  const active = () => !stopped && !paused && available() && options.current()

  function publish(next: SyncStatus, confirmed: boolean) {
    state = next
    options.status(next, confirmed)
  }

  function disconnect() {
    window.clearTimeout(watchdog)
    closeSocket?.()
    closeSocket = undefined
    live = false
  }

  function cancelWork() {
    activityGeneration++
    window.clearTimeout(retryTimer)
    retryTimer = undefined
    window.clearTimeout(pollTimer)
    disconnect()
    request?.controller.abort()
    request = undefined
  }

  function scheduleRetry() {
    if (retryTimer !== undefined || !active()) return
    retryTimer = window.setTimeout(() => {
      retryTimer = undefined
      void cycle()
    }, retryDelay(failures++))
  }

  function lostSocket(code: number) {
    const invalidate = live || state === 'connecting'
    disconnect()
    if (code === 4401 || code === 4403 || code === 4404) {
      stop()
      publish('blocked', false)
      options.denied(code)
      return
    }
    if (invalidate) confirmationGeneration++
    if (invalidate || state !== 'http') publish('offline', false)
    scheduleRetry()
  }

  function expectActivity() {
    window.clearTimeout(watchdog)
    watchdog = window.setTimeout(() => {
      if (active()) lostSocket(1006)
    }, SOCKET_DEADLINE)
  }

  function connect() {
    if (
      !active() ||
      needsVerification ||
      closeSocket ||
      retryTimer !== undefined ||
      !options.hasSnapshot()
    )
      return
    let close: () => void
    const current = () => active() && closeSocket === close
    try {
      close = connectSaveSocket(
        id,
        current,
        (next) => {
          if (!options.accept(next, !live)) return
          live = true
          failures = 0
          publish('live', true)
          expectActivity()
        },
        lostSocket,
        () => {
          if (live) expectActivity()
        },
      )
      closeSocket = close
      expectActivity()
    } catch {
      lostSocket(1006)
    }
  }

  function refresh() {
    if (request) return request.done
    window.clearTimeout(pollTimer)
    const controller = new AbortController()
    const generation = confirmationGeneration
    const done = options
      .read(controller.signal)
      .then((confirmed) => {
        if (!active() || controller.signal.aborted || live || generation !== confirmationGeneration)
          return
        if (confirmed && state === 'offline') publish('http', true)
        else if (!confirmed && state === 'http') publish('offline', false)
        else publish(state, confirmed)
      })
      .finally(() => {
        if (request?.controller !== controller) return
        request = undefined
        if (active()) pollTimer = window.setTimeout(() => void refresh(), HTTP_INTERVAL)
      })
    request = { controller, done }
    return done
  }

  async function cycle() {
    if (!active()) return
    const generation = activityGeneration
    if (needsVerification) {
      const verified = await options.verify()
      if (!active() || generation !== activityGeneration) return
      if (!verified) {
        scheduleRetry()
        return
      }
      needsVerification = false
    }
    const reading = refresh()
    connect()
    await reading
    if (generation !== activityGeneration) return
    connect()
    if (!closeSocket) scheduleRetry()
  }

  function suspend() {
    paused = true
    needsVerification = true // Online is a hint; every gap must recheck the session.
    cancelWork()
    publish(document.hidden || pageHidden ? 'paused' : 'offline', false)
  }

  function resume() {
    if (!available()) suspend()
    else if (paused && !stopped && options.current()) {
      paused = false
      publish('connecting', false)
      void cycle()
    }
  }

  function onPageHide() {
    pageHidden = true
    suspend()
  }
  function onPageShow() {
    pageHidden = false
    resume()
  }
  document.addEventListener('visibilitychange', resume)
  window.addEventListener('offline', suspend)
  window.addEventListener('online', resume)
  window.addEventListener('pagehide', onPageHide)
  window.addEventListener('pageshow', onPageShow)

  function stop() {
    stopped = true
    cancelWork()
    document.removeEventListener('visibilitychange', resume)
    window.removeEventListener('offline', suspend)
    window.removeEventListener('online', resume)
    window.removeEventListener('pagehide', onPageHide)
    window.removeEventListener('pageshow', onPageShow)
  }

  async function open() {
    if (stopped) return
    if (!available()) {
      suspend()
      return
    }
    paused = false
    window.clearTimeout(retryTimer)
    retryTimer = undefined
    await cycle()
  }

  return { open, stop }
}
