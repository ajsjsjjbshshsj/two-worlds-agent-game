import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import SceneRenderer from '../src/components/game/SceneRenderer.vue'
import ActionPanel from '../src/components/game/ActionPanel.vue'
import { parseGame } from '../src/types/game'
import { protectedImage } from '../src/services/media'
import { game } from './game-fixture'
afterEach(() => vi.unstubAllGlobals())
it('failed protected image retains readable alternative and playable controls', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })))
  const s = parseGame({
    ...game(),
    presentation: {
      background: { asset_id: 'asset_one', kind: 'image', alt_text: 'TEST-ONLY', transcript: null },
      cues: [],
    },
  })
  const w = mount(SceneRenderer, { props: { snapshot: s, token: 'SESSION_TEST' } })
  await flushPromises()
  expect(w.text()).toContain('图片暂不可用')
  expect(w.find('svg').exists()).toBe(true)
  w.unmount()
})
it('unmount with an active object URL revokes it', async () => {
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = vi.fn(() => 'blob:ACTIVE')
      static revokeObjectURL = vi.fn()
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response('image', { headers: { 'Content-Type': 'image/png' } })),
  )
  const s = parseGame({
    ...game(),
    presentation: {
      background: { asset_id: 'asset_one', kind: 'image', alt_text: 'TEST-ONLY', transcript: null },
      cues: [],
    },
  })
  const w = mount(SceneRenderer, { props: { snapshot: s, token: 'SESSION_TEST' } })
  await flushPromises()
  w.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:ACTIVE')
})
it('uses visible devices only and changes confirmed beam angle with snapshot', async () => {
  const a = parseGame(game())
  const w = mount(SceneRenderer, { props: { snapshot: a } })
  expect(w.text()).toContain('emitter')
  expect(w.text()).not.toContain('power_panel')
  await w.setProps({
    snapshot: parseGame({
      ...game(),
      role: 'b',
      personal: {
        ...game().personal,
        devices: { power_panel: { engine: true, sonar: false, lamp: true } },
      },
    }),
  })
  expect(w.text()).not.toContain('emitter')
  expect(w.text()).toContain('power_panel')
  expect(w.find('svg').attributes('aria-label')).toContain('原型')
  w.unmount()
})
it('dynamic typed actions submit only user parameters and keyboard-native controls', async () => {
  const w = mount(ActionPanel, {
    props: { actions: parseGame(game()).available_actions, disabled: false },
  })
  await w.get('select[name=angle]').setValue('1')
  await w.get('select[name=pattern]').setValue('1')
  await w.get('form').trigger('submit')
  expect(w.emitted('command')?.[0]).toEqual(['adjust', { angle: 90, pattern: 'pulse' }])
  w.unmount()
})
it('supports booleans, integers and bounded free text without guessed answers', async () => {
  const w = mount(ActionPanel, {
    props: {
      actions: [
        {
          id: 'test',
          kind: 'test',
          parameters: [
            { id: 'enabled', value_type: 'boolean', choices: [], max_length: null },
            { id: 'count', value_type: 'integer', choices: [], max_length: null },
            { id: 'note', value_type: 'string', choices: [], max_length: 3 },
          ],
        },
      ],
      disabled: false,
    },
  })
  await w.get('input[name=enabled]').setValue(true)
  await w.get('input[name=count]').setValue('2')
  await w.get('input[name=note]').setValue('ok')
  await w.get('form').trigger('submit')
  expect(w.emitted('command')?.[0]).toEqual(['test', { enabled: true, count: 2, note: 'ok' }])
  w.unmount()
})
it('fetches image with Bearer and no-store and owns object URL cleanup', async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(new Blob(['image'], { type: 'image/png' }), {
      headers: { 'Content-Type': 'image/png' },
    }),
  )
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = vi.fn(() => 'blob:TEST')
      static revokeObjectURL = vi.fn()
    },
  )
  const result = await protectedImage(
    'SESSION_TEST',
    'save_one',
    'asset_one',
    new AbortController().signal,
  )
  expect(fetch.mock.calls[0]![1]).toMatchObject({ cache: 'no-store', credentials: 'omit' })
  expect(new Headers(fetch.mock.calls[0]![1].headers).get('Authorization')).toBe(
    'Bearer SESSION_TEST',
  )
  result.dispose()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:TEST')
})
it('scene revokes images on snapshot change and unmount; failure leaves readable fallback', async () => {
  const create = vi.fn(() => 'blob:TEST'),
    revoke = vi.fn()
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = create
      static revokeObjectURL = revoke
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(new Blob(['image'], { type: 'image/png' }), {
        headers: { 'Content-Type': 'image/png' },
      }),
    ),
  )
  const s = parseGame({
    ...game(),
    presentation: {
      background: {
        asset_id: 'asset_one',
        kind: 'image',
        alt_text: 'TEST-ONLY 场景替代文字',
        transcript: null,
      },
      cues: [],
    },
  })
  const w = mount(SceneRenderer, { props: { snapshot: s, token: 'SESSION_TEST' } })
  await flushPromises()
  expect(w.find('img').attributes('src')).toBe('blob:TEST')
  await w.setProps({ snapshot: parseGame(game()) })
  expect(revoke).toHaveBeenCalled()
  w.unmount()
})
