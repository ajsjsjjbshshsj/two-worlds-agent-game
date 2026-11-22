export function classifyRequest(request: Request, scope: string, urls: Set<string>) {
  const url = new URL(request.url),
    root = new URL(scope)
  if (
    request.method !== 'GET' ||
    url.origin !== root.origin ||
    !url.pathname.startsWith(root.pathname)
  )
    return 'network'
  let path = url.pathname
  try {
    for (let i = 0; i < 3; i++) path = decodeURIComponent(path)
  } catch {
    return 'network'
  }
  if (path.split('/').some((p) => p === 'api' || p === 'ws')) return 'network'
  if (request.mode === 'navigate') return 'navigation'
  if (url.search || url.hash || url.pathname.includes('%') || request.headers.has('Authorization'))
    return 'network'
  // Browser subresources may carry cookies. Only immutable, preverified public
  // bytes are returned here; the credentialed network response is never stored.
  if (
    urls.has(url.href) &&
    (request.credentials === 'omit' ||
      ['script', 'style', 'image', 'font', 'manifest'].includes(request.destination))
  )
    return 'static'
  return 'network'
}

export interface PublicResource {
  path: string
  integrity: string
}
interface WorkerEvent {
  request: Request
  waitUntil(value: Promise<unknown>): void
  respondWith(value: Promise<Response>): void
}
interface WorkerScope {
  registration: { scope: string }
  caches: CacheStorage
  clients: { claim(): Promise<void> }
  fetch(input: Request): Promise<Response>
  addEventListener(type: string, listener: (event: WorkerEvent) => void): void
}
export interface WorkerConfig {
  prefix: string
  version: string
  resources: PublicResource[]
}

export function attachWorker(scope: WorkerScope, config: WorkerConfig) {
  const root = scope.registration.scope
  const name = config.prefix + config.version
  const entries = new Map(config.resources.map((r) => [new URL(r.path, root).href, r]))
  const urls = new Set(entries.keys())
  const publicRequest = (url: string, integrity?: string) =>
    new Request(url, {
      credentials: 'omit',
      redirect: 'error',
      cache: 'no-store',
      ...(integrity ? { integrity } : {}),
    })
  scope.addEventListener('install', (event) => {
    event.waitUntil(
      (async () => {
        const cache = await scope.caches.open(name)
        try {
          for (const [url, entry] of entries) {
            const response = await scope.fetch(publicRequest(url, entry.integrity))
            if (!response.ok || response.redirected || response.type === 'opaque')
              throw new Error('Public precache unavailable')
            // Persist only verified public bytes and deliberately selected headers.
            // Never persist a server's Set-Cookie or other contextual headers.
            await cache.put(
              publicRequest(url),
              new Response(await response.arrayBuffer(), {
                headers: {
                  'Content-Type':
                    response.headers.get('Content-Type') ?? 'application/octet-stream',
                  'Cache-Control': 'public, max-age=31536000, immutable',
                  'X-Content-Type-Options': 'nosniff',
                },
              }),
            )
          }
        } catch (error) {
          await scope.caches.delete(name)
          throw error
        }
        // No skipWaiting: existing games and unknown UUIDs are never force-reloaded.
      })(),
    )
  })
  scope.addEventListener('activate', (event) => {
    event.waitUntil(
      (async () => {
        for (const key of await scope.caches.keys())
          if (key.startsWith(config.prefix) && key !== name) await scope.caches.delete(key)
        await scope.clients.claim()
      })(),
    )
  })
  scope.addEventListener('fetch', (event) => {
    const kind = classifyRequest(event.request, root, urls)
    if (kind === 'network') return // No response clone, cache write or background queue.
    if (kind === 'static') {
      event.respondWith(
        (async () => {
          const cache = await scope.caches.open(name)
          const cached = await cache.match(publicRequest(event.request.url))
          // No runtime cache writes, even on a cache miss.
          return (
            cached ??
            scope.fetch(publicRequest(event.request.url, entries.get(event.request.url)?.integrity))
          )
        })(),
      )
    } else {
      event.respondWith(
        (async () => {
          try {
            return await scope.fetch(new Request(event.request, { cache: 'no-store' }))
          } catch {
            const cache = await scope.caches.open(name)
            return (
              (await cache.match(publicRequest(new URL('offline.html', root).href))) ??
              new Response('TwoWorlds offline', {
                status: 503,
                headers: { 'Cache-Control': 'no-store' },
              })
            )
          }
        })(),
      )
    }
  })
}
