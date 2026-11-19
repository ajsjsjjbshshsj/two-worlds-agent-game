// Coordination metadata contains only random operation IDs and times. Cookie
// contents and account information never enter this channel or its storage fence.
export const SESSION_REVISION = 'twoworlds.auth-context.revision'
const ACTIVE_PREFIX = 'twoworlds.auth-context.active.'
const CHANNEL = 'twoworlds.auth-context'
const LEASE_MS = 60000

type Signal = { id: string; phase: 'start' | 'finish'; until: number }
type Snapshot = { key: string; changing: boolean; nextExpiry: number | undefined }

export function createSessionSync(onChange: () => void) {
  let channel: BroadcastChannel | undefined
  try {
    if (typeof window.BroadcastChannel === 'function') channel = new BroadcastChannel(CHANNEL)
  } catch {
    // A restricted browser can still verify on focus, visibility and pageshow.
  }

  const seen = new Map<string, number>()
  let latest = ''

  function snapshot(): Snapshot {
    const now = Date.now()
    let revision = latest
    const active = new Map<string, number>()
    try {
      const storage = window.localStorage
      revision = storage.getItem(SESSION_REVISION) ?? latest
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i)
        if (key?.startsWith(ACTIVE_PREFIX)) {
          active.set(key.slice(ACTIVE_PREFIX.length), Number(storage.getItem(key)))
        }
      }
    } catch {
      // Broadcast notices still fence work if storage access is denied.
      for (const [id, until] of seen) active.set(id, until)
    }
    const deadlines = [...active.values()].filter((until) => until > now && until <= now + LEASE_MS)
    const changing = deadlines.length > 0
    return {
      key: JSON.stringify([revision, changing]),
      changing,
      nextExpiry: changing ? Math.min(...deadlines) : undefined,
    }
  }

  function receive(event: MessageEvent<unknown>) {
    const data = event.data as Partial<Signal> | null
    if (
      !data ||
      typeof data.id !== 'string' ||
      !/^[a-f0-9-]{32,36}$/.test(data.id) ||
      (data.phase !== 'start' && data.phase !== 'finish') ||
      typeof data.until !== 'number'
    )
      return
    if (data.phase === 'start') seen.set(data.id, data.until)
    else seen.delete(data.id)
    latest = `${data.id}:${data.phase}`
    onChange()
  }

  function storageChanged(event: StorageEvent) {
    if (event.key === null || event.key === SESSION_REVISION || event.key.startsWith(ACTIVE_PREFIX))
      onChange()
  }
  channel?.addEventListener('message', receive)
  window.addEventListener('storage', storageChanged)

  function begin() {
    const id =
      crypto.randomUUID?.() ??
      Array.from(crypto.getRandomValues(new Uint8Array(16)), (part) =>
        part.toString(16).padStart(2, '0'),
      ).join('')
    const until = Date.now() + LEASE_MS
    write({ id, phase: 'start', until })
    return () => write({ id, phase: 'finish', until })
  }

  function write(signal: Signal) {
    const activeKey = ACTIVE_PREFIX + signal.id
    latest = `${signal.id}:${signal.phase}`
    if (signal.phase === 'start') seen.set(signal.id, signal.until)
    else seen.delete(signal.id)
    try {
      const storage = window.localStorage
      // The pending marker exists before the write starts. Mark the new revision
      // before releasing it, so no reader can mistake settlement for the old state.
      if (signal.phase === 'start') storage.setItem(activeKey, String(signal.until))
      storage.setItem(SESSION_REVISION, latest)
      if (signal.phase === 'finish') storage.removeItem(activeKey)
    } catch {
      // Coordination still works through the channel.
    }
    try {
      channel?.postMessage(signal)
    } catch {
      /* Storage and lifecycle events can still verify. */
    }
  }

  function close() {
    channel?.close()
    window.removeEventListener('storage', storageChanged)
  }

  return { snapshot, begin, close }
}

let captureGeneration: (() => number | null) | undefined

export function registerPrivateSessionGuard(capture: () => number | null) {
  captureGeneration = capture
  return () => {
    if (captureGeneration === capture) captureGeneration = undefined
  }
}

export function privateSessionLease() {
  const capture = captureGeneration
  if (!capture) return () => true
  const generation = capture()
  return () => generation !== null && capture() === generation
}

export async function withCookieWriteLock<T>(action: () => Promise<T>): Promise<T> {
  const locks = navigator.locks
  return locks
    ? await locks.request('twoworlds-cookie-write', { mode: 'exclusive' }, action)
    : action()
}
