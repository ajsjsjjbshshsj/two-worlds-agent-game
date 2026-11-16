import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useIdentityStore, SESSION_KEY } from '../src/stores/identity'
import { usePairsStore } from '../src/stores/pairs'
import { useLibraryStore } from '../src/stores/library'
import { json, me } from './fixtures'
import { pairA, pairB, invitation, script, summary, snapshot } from './resource-fixtures'
beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})
afterEach(() => vi.unstubAllGlobals())
async function authenticate() {
  sessionStorage.setItem(SESSION_KEY, 'SESSION_TEST')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(me)))
  await useIdentityStore().initialize()
}
it('captures fragment immediately into memory only, clears it, and does not autojoin', () => {
  window.history.replaceState({}, '', '/#invite=tw_invite_TEST_ONLY')
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const pairs = usePairsStore()
  pairs.captureInvite()
  expect(window.location.hash).toBe('')
  expect(pairs.hasIncomingInvite).toBe(true)
  expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain(
    'tw_invite_TEST_ONLY',
  )
  expect(fetch).not.toHaveBeenCalled()
  setActivePinia(createPinia())
  expect(usePairsStore().hasIncomingInvite).toBe(false)
})
it('create and refresh invitation keep secrets in memory and never invent member counts', async () => {
  await authenticate()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json(invitation))
      .mockResolvedValueOnce(json([pairA]))
      .mockResolvedValueOnce(json({ ...invitation, invite_token: 'tw_invite_NEW_TEST' }))
      .mockResolvedValueOnce(json([pairA])),
  )
  const pairs = usePairsStore()
  expect(await pairs.create()).toBe(pairA.id)
  expect(pairs.pairs).toEqual([pairA])
  expect(pairs.invitation?.invite_token).toBe(invitation.invite_token)
  await pairs.refresh(pairA.id)
  expect(pairs.invitation?.invite_token).toBe('tw_invite_NEW_TEST')
  expect(pairs.notice).toContain('旧')
  expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain('tw_invite')
})
it('explicit join refreshes server room list; pending new key blocks joining', async () => {
  await authenticate()
  window.history.replaceState({}, '', '/#invite=tw_invite_TEST_ONLY')
  const pairs = usePairsStore()
  pairs.captureInvite()
  const identity = useIdentityStore()
  identity.pendingRecoveries = [
    {
      account_id: me.account.id,
      display_name: '旅人',
      created_at: new Date().toISOString(),
      pending: true,
    },
  ]
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json({ id: pairA.id, role: 'b' }))
    .mockResolvedValueOnce(json([pairB]))
  vi.stubGlobal('fetch', fetch)
  expect(await pairs.join()).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
  identity.confirmRecoveryKeySaved(me.account.id)
  expect(await pairs.join()).toBe(pairA.id)
  expect(pairs.pairs).toEqual([pairB])
  expect(pairs.hasIncomingInvite).toBe(false)
})
it.each(['INVITE_INVALID', 'PAIR_FULL', 'DEPENDENCY_UNAVAILABLE'])(
  'safe invitation error %s supports explicit retry without leaking body',
  async (code) => {
    await authenticate()
    window.history.replaceState({}, '', '/#invite=tw_invite_TEST_ONLY')
    const pairs = usePairsStore()
    pairs.captureInvite()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          json(
            { error: { code, message: 'SECRET', retryable: false } },
            code === 'DEPENDENCY_UNAVAILABLE' ? 503 : code === 'PAIR_FULL' ? 409 : 404,
          ),
        ),
    )
    await pairs.join()
    expect(pairs.error?.code).toBe(code)
    expect(pairs.error?.message).not.toContain('SECRET')
    expect(pairs.hasIncomingInvite).toBe(true)
  },
)
it('multi-room list clears on logout and ignores an old-session response', async () => {
  await authenticate()
  let resolve!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(
      () =>
        new Promise<Response>((r) => {
          resolve = r
        }),
    ),
  )
  const pairs = usePairsStore()
  const loading = pairs.load()
  useIdentityStore().expireSession()
  resolve(json([pairA]))
  await loading
  expect(pairs.pairs).toEqual([])
  expect(pairs.invitation).toBeNull()
})
it('library joins saves by pair and script, preserving old version and completed states', async () => {
  await authenticate()
  const pairs = usePairsStore()
  pairs.pairs = [{ ...pairA, member_count: 2 }]
  const saved = { ...summary, completed: true }
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(
        json([script, { ...script, id: 'other_story', title: '另一测试故事' }]),
      )
      .mockResolvedValueOnce(json([saved])),
  )
  const library = useLibraryStore()
  await library.load(pairA.id)
  expect(library.cards.find((c) => c.script.id === script.id)?.save?.script_version).toBe('1.0.0')
  expect(library.cards.find((c) => c.script.id === 'other_story')?.save).toBeNull()
  expect(library.cards.find((c) => c.script.id === script.id)?.save?.completed).toBe(true)
  const fetch = vi.fn().mockResolvedValue(json(snapshot))
  vi.stubGlobal('fetch', fetch)
  expect(await library.open(script.id)).toBe(summary.id)
  expect(fetch.mock.calls[0]?.[0]).toBe('/api/saves/save_one')
  expect(fetch.mock.calls[0]?.[1].method).toBe('GET')
})
it('empty real catalog stays empty; no hardcoded cards', async () => {
  await authenticate()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json([])))
  const library = useLibraryStore()
  await library.load(pairA.id)
  expect(library.cards).toEqual([])
})
it('selects latest numeric catalog version once per story while keeping old save version', async () => {
  await authenticate()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(
        json([
          { ...script, content_version: '9.0.0' },
          { ...script, content_version: '10.0.0' },
          script,
        ]),
      )
      .mockResolvedValueOnce(json([summary])),
  )
  const library = useLibraryStore()
  await library.load(pairA.id)
  expect(library.cards).toHaveLength(1)
  expect(library.cards[0]?.script.content_version).toBe('10.0.0')
  expect(library.cards[0]?.save?.script_version).toBe('1.0.0')
})
it('a catalog network failure can recover on explicit refresh', async () => {
  await authenticate()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockRejectedValueOnce(new TypeError('SECRET'))
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json([script]))
      .mockResolvedValueOnce(json([])),
  )
  const library = useLibraryStore()
  await library.load(pairA.id)
  expect(library.error?.code).toBe('NETWORK_ERROR')
  expect(library.error?.message).not.toContain('SECRET')
  await library.load(pairA.id)
  expect(library.error).toBeNull()
  expect(library.cards).toHaveLength(1)
})
it('new save requires server-confirmed full room and exact catalog version', async () => {
  await authenticate()
  const pairs = usePairsStore()
  pairs.pairs = [pairA]
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json([script]))
      .mockResolvedValueOnce(json([])),
  )
  const library = useLibraryStore()
  await library.load(pairA.id)
  const fetch = vi.fn().mockResolvedValue(json({ ...snapshot, script_version: '2.0.0' }))
  vi.stubGlobal('fetch', fetch)
  expect(await library.open(script.id)).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
  pairs.pairs = [{ ...pairA, member_count: 2 }]
  expect(await library.open(script.id)).toBe(summary.id)
  expect(JSON.parse(fetch.mock.calls[0]?.[1].body)).toEqual({
    pair_id: pairA.id,
    script_id: script.id,
    script_version: '2.0.0',
  })
})
it('switching room rejects late catalog/save responses and clears previous entry', async () => {
  await authenticate()
  let resolve!: (value: Response) => void
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json([script]))
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          resolve = r
        }),
    )
    .mockResolvedValueOnce(json([]))
    .mockResolvedValueOnce(json([]))
  vi.stubGlobal('fetch', fetch)
  const library = useLibraryStore()
  const previous = library.load(pairA.id)
  await library.load('pair_other')
  resolve(json([summary]))
  await previous
  expect(library.pairId).toBe('pair_other')
  expect(library.cards).toEqual([])
  expect(library.entry).toBeNull()
})
it('401 removes session and private lists while preserving recovery reminders', async () => {
  await authenticate()
  const identity = useIdentityStore()
  identity.pendingRecoveries = [
    {
      account_id: 'account_other',
      display_name: '其他',
      created_at: new Date().toISOString(),
      pending: true,
    },
  ]
  const pairs = usePairsStore()
  pairs.pairs = [pairA]
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        json({ error: { code: 'UNAUTHENTICATED', message: 'SECRET', retryable: false } }, 401),
      ),
  )
  await pairs.load()
  expect(identity.authenticated).toBe(false)
  expect(pairs.pairs).toEqual([])
  expect(identity.pendingRecoveries).toHaveLength(1)
})
it('rejects a create response with a different pinned content version', async () => {
  await authenticate()
  usePairsStore().pairs = [{ ...pairA, member_count: 2 }]
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json([script]))
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json(snapshot)),
  )
  const library = useLibraryStore()
  await library.load(pairA.id)
  expect(await library.open(script.id)).toBeNull()
  expect(library.error?.code).toBe('INVALID_RESPONSE')
  expect(library.entry).toBeNull()
})
it('out-of-order save reads and resets cannot repopulate another page', async () => {
  await authenticate()
  let resolve!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((r) => {
            resolve = r
          }),
      )
      .mockResolvedValueOnce(json({ ...snapshot, id: 'save_other', script_id: 'story_other' })),
  )
  const library = useLibraryStore()
  const old = library.read(summary.id)
  await library.read('save_other')
  resolve(json(snapshot))
  await old
  expect(library.entry?.id).toBe('save_other')
  let finish!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(
      () =>
        new Promise<Response>((r) => {
          finish = r
        }),
    ),
  )
  const pending = library.read(summary.id)
  library.reset()
  finish(json(snapshot))
  await pending
  expect(library.entry).toBeNull()
})
it('server-confirmed full membership discards the no-longer-usable issued invitation', async () => {
  await authenticate()
  const pairs = usePairsStore()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json(invitation))
      .mockResolvedValueOnce(json([pairA]))
      .mockResolvedValueOnce(json([{ ...pairA, member_count: 2 }])),
  )
  await pairs.create()
  expect(pairs.invitation).not.toBeNull()
  await pairs.load()
  expect(pairs.invitation).toBeNull()
  expect(pairs.pairs[0]?.member_count).toBe(2)
})
