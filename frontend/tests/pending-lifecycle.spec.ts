import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useIdentityStore } from '../src/stores/identity'
import { useGameStore } from '../src/stores/game'
import { usePairsStore } from '../src/stores/pairs'
import { useLibraryStore } from '../src/stores/library'
import { deferred, fail, json, loginInput, me, noContent, other, resetInput } from './fixtures'
import { pairA, invitation, summary, script } from './resource-fixtures'
import { game as gameSnapshot } from './game-fixture'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

async function setup() {
  const fetch = vi.fn().mockResolvedValueOnce(json(me))
  vi.stubGlobal('fetch', fetch)
  const identity = useIdentityStore()
  const game = useGameStore()
  const pairs = usePairsStore()
  const library = useLibraryStore()
  await identity.initialize()
  return { fetch, identity, game, pairs, library }
}
const gameResult = gameSnapshot()

it.each(['logout', 'reset', 'expire'] as const)(
  '%s clears private state and discards late results from every store',
  async (event) => {
    const { fetch, identity, game, pairs, library } = await setup()
    fetch
      .mockResolvedValueOnce(json(gameResult))
      .mockResolvedValueOnce(json(invitation))
      .mockResolvedValueOnce(json([pairA]))
      .mockResolvedValueOnce(json([script]))
      .mockResolvedValueOnce(json([summary]))
    await game.load('save_one')
    await pairs.create()
    await library.load(pairA.id)
    expect(game.snapshot).toBeTruthy()
    expect(pairs.invitation).toBeTruthy()
    expect(library.saves).toHaveLength(1)
    const staleGame = deferred<Response>()
    const stalePairs = deferred<Response>()
    const staleLibrary = deferred<Response>()
    fetch
      .mockReturnValueOnce(staleGame.promise)
      .mockReturnValueOnce(stalePairs.promise)
      .mockReturnValueOnce(staleLibrary.promise)
    const inflight = [game.load('save_one'), pairs.load(), library.read('save_one')]
    if (event === 'expire') identity.expireSession()
    else {
      fetch.mockResolvedValueOnce(noContent())
      expect(
        await (event === 'logout' ? identity.logout() : identity.resetPassword(resetInput)),
      ).toBe(true)
    }
    staleGame.resolve(json(gameResult))
    stalePairs.resolve(json([pairA]))
    staleLibrary.resolve(json(gameResult))
    await Promise.all(inflight)
    expect(identity.authenticated).toBe(false)
    expect(game.snapshot).toBeNull()
    expect(library.entry).toBeNull()
    expect(library.saves).toEqual([])
    expect(pairs.pairs).toEqual([])
    expect(pairs.invitation).toBeNull()
  },
)

it.each([200, 401] as const)(
  'late game response %i cannot replace or expire a new account',
  async (status) => {
    const { fetch, identity, game } = await setup()
    const response = deferred<Response>()
    fetch.mockReturnValueOnce(response.promise).mockResolvedValueOnce(json(other))
    const old = game.load('save_one')
    expect(await identity.login({ ...loginInput, email: other.account.email })).toBe(true)
    fetch.mockResolvedValueOnce(json({ ...gameResult, role: 'b' }))
    await game.load('save_one')
    response.resolve(status === 200 ? json(gameResult) : fail(401))
    await old
    expect(game.snapshot?.role).toBe('b')
    expect(identity.account).toEqual(other.account)
  },
)

it.each([503, 0] as const)(
  'private resource failure %i preserves the verified account and snapshot',
  async (status) => {
    const { fetch, identity, game } = await setup()
    fetch.mockResolvedValueOnce(json(gameResult))
    await game.load('save_one')
    if (status) fetch.mockResolvedValueOnce(fail(status))
    else fetch.mockRejectedValueOnce(new TypeError('PRIVATE'))
    await game.load('save_one')
    expect(identity.account).toEqual(me.account)
    expect(game.snapshot?.id).toBe('save_one')
    expect(game.error).not.toContain('PRIVATE')
  },
)

it('a current game 401 clears the authenticated snapshot', async () => {
  const { fetch, identity, game } = await setup()
  fetch.mockResolvedValueOnce(json(gameResult)).mockResolvedValueOnce(fail(401))
  await game.load('save_one')
  await game.load('save_one')
  expect(identity.authenticated).toBe(false)
  expect(game.snapshot).toBeNull()
})
