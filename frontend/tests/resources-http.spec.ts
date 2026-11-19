import { afterEach, expect, it, vi } from 'vitest'
import { createHttpClient } from '../src/services/http'
import { pairApi } from '../src/services/pairs'
import { libraryApi } from '../src/services/library'
import { json } from './fixtures'
import { pairA, invitation, script, summary, snapshot } from './resource-fixtures'
afterEach(() => vi.unstubAllGlobals())
it('uses the eight existing endpoints with exact bodies and Cookie credentials', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(invitation))
    .mockResolvedValueOnce(json([pairA]))
    .mockResolvedValueOnce(json({ id: pairA.id, role: 'b' }))
    .mockResolvedValueOnce(json(invitation))
    .mockResolvedValueOnce(json([script]))
    .mockResolvedValueOnce(json([summary]))
    .mockResolvedValueOnce(json(snapshot))
    .mockResolvedValueOnce(json(snapshot))
  vi.stubGlobal('fetch', fetch)
  await pairApi.create()
  await pairApi.list()
  await pairApi.join(invitation.invite_token)
  await pairApi.refresh(pairA.id)
  await libraryApi.catalog()
  await libraryApi.saves(pairA.id)
  await libraryApi.create(pairA.id, script.id, '2.0.0')
  await libraryApi.read(summary.id)
  expect(fetch.mock.calls.map((call) => call[0])).toEqual([
    '/api/pairs',
    '/api/pairs',
    '/api/pairs/join',
    '/api/pairs/pair_one/invite',
    '/api/scripts',
    '/api/saves?pair_id=pair_one',
    '/api/saves',
    '/api/saves/save_one',
  ])
  expect(JSON.parse(fetch.mock.calls[2]![1].body)).toEqual({
    invite_token: invitation.invite_token,
  })
  expect(JSON.parse(fetch.mock.calls[6]![1].body)).toEqual({
    pair_id: pairA.id,
    script_id: script.id,
    script_version: '2.0.0',
  })
  for (const [url, options] of fetch.mock.calls) {
    expect(url).not.toMatch(/[?&](?:token|session)=/i)
    expect(options.cache).toBe('no-store')
    expect(options.credentials).toBe('include')
    expect(new Headers(options.headers).has('Authorization')).toBe(false)
  }
})
it.each(['../pair', 'pair?token=x', 'pair#secret', 'PAIR', 'pair_one\n'])(
  'rejects unsafe separate query identifier %s',
  async (pair_id) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(
      createHttpClient().request('/api/saves', { query: { pair_id } }),
    ).rejects.toMatchObject({ code: 'INVALID_REQUEST' })
    expect(fetch).not.toHaveBeenCalled()
  },
)
it('does not allow queries on unrelated routes or POST', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await expect(
    createHttpClient().request('/api/me', { query: { pair_id: 'pair_one' } }),
  ).rejects.toMatchObject({ code: 'INVALID_REQUEST' })
  await expect(
    createHttpClient().request('/api/saves', { method: 'POST', query: { pair_id: 'pair_one' } }),
  ).rejects.toMatchObject({ code: 'INVALID_REQUEST' })
  expect(fetch).not.toHaveBeenCalled()
})
it('rejects incomplete responses and drops internal fields from metadata and save entry', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json([{ ...script, clues: ['SECRET'] }]))
      .mockResolvedValueOnce(json({ ...snapshot, state: { private: 'OTHER_SECRET' } }))
      .mockResolvedValueOnce(json([{ id: 'pair_one', role: 'c', member_count: 3 }])),
  )
  expect(JSON.stringify(await libraryApi.catalog())).not.toContain('SECRET')
  expect(JSON.stringify(await libraryApi.read('save_one'))).not.toContain('OTHER_SECRET')
  await expect(pairApi.list()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' })
})
