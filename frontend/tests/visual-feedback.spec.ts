import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { computed, defineComponent } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import SceneRenderer from '../src/components/game/SceneRenderer.vue'
import ActionPanel from '../src/components/game/ActionPanel.vue'
import { parseGame, type Scalar } from '../src/types/game'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { game } from './game-fixture'
import { json, me } from './fixtures'

afterEach(() => vi.unstubAllGlobals())
function scene(
  script = 'lighthouse',
  stage = 'calibration',
  role = 'a',
  effects: Record<string, Scalar> = {},
) {
  return parseGame({
    ...game(),
    script_id: script,
    scene_id: stage,
    role,
    completed: stage === 'completed',
    presentation: {
      background: null,
      cues: [],
      visual_state: Object.entries(effects).map(([id, value]) => ({ id, value })),
    },
  })
}
it('B receives destination and filter effects without emitter parameters', async () => {
  const w = mount(SceneRenderer, {
    props: {
      snapshot: scene('lighthouse', 'calibration', 'b', {
        beam_quality: 'blurred',
        filter_tint: 'clear',
      }),
    },
  })
  expect(w.get('[data-visual=received-beam]').attributes('data-destination')).toBeUndefined()
  await w.setProps({
    snapshot: scene('lighthouse', 'calibration', 'b', {
      beam_quality: 'clear',
      beam_destination: 'reef',
      filter_tint: 'amber',
    }),
  })
  expect(w.get('[data-visual=received-beam]').attributes()).toMatchObject({
    'data-destination': 'reef',
    'data-filter': 'amber',
    'data-quality': 'clear',
  })
  const oldLine = w.get('[data-visual=received-beam] line').attributes('x2')
  await w.setProps({
    snapshot: scene('lighthouse', 'calibration', 'b', {
      beam_quality: 'clear',
      beam_destination: 'inner_bay',
      filter_tint: 'amber',
    }),
  })
  expect(w.get('[data-visual=received-beam] line').attributes('x2')).not.toBe(oldLine)
  expect(w.find('[data-visual=emitter]').exists()).toBe(false)
  w.unmount()
})
it('own emitter rotates and pulses only on a confirmed visual snapshot', async () => {
  const w = mount(SceneRenderer, {
    props: {
      snapshot: scene('lighthouse', 'calibration', 'a', {
        emitter_angle: 0,
        emitter_pattern: 'steady',
      }),
    },
  })
  expect(w.get('.beam').attributes('style')).toContain('rotate(0deg)')
  await w.setProps({
    snapshot: scene('lighthouse', 'calibration', 'a', {
      emitter_angle: 90,
      emitter_pattern: 'pulse',
    }),
  })
  expect(w.get('.beam').attributes('style')).toContain('rotate(90deg)')
  expect(w.get('.beam').classes()).toContain('pulsed')
  w.unmount()
})
it('clock has separate powered and repaired feedback; arbitrary device booleans do not light it', async () => {
  const snapshot = scene('lighthouse', 'repair', 'a', {
    clock_powered: false,
    clock_repaired: false,
  })
  snapshot.personal.devices.unrelated = { enabled: true }
  const w = mount(SceneRenderer, { props: { snapshot } })
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('false')
  expect(w.classes()).not.toContain('energized')
  await w.setProps({
    snapshot: scene('lighthouse', 'repair', 'a', { clock_powered: true, clock_repaired: true }),
  })
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('true')
  expect(w.get('.clock-hands').classes()).toContain('running')
  await w.setProps({
    snapshot: scene('lighthouse', 'repair', 'a', { clock_powered: false, clock_repaired: true }),
  })
  expect(w.get('.clock-hands').classes()).toContain('running')
  w.unmount()
})
it('B routing and lock indicators use explicit authorized effects', () => {
  const w = mount(SceneRenderer, {
    props: {
      snapshot: scene('lighthouse', 'repair', 'b', {
        power_target: 'shore',
        route_ready: false,
        signal_locked: true,
      }),
    },
  })
  expect(w.get('[data-visual=power-router]').attributes('data-target')).toBe('shore')
  expect(w.find('[data-visual=stable-signal]').exists()).toBe(true)
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBeUndefined()
  w.unmount()
})
it('starline echo, actual scan and connected rail use separate server effects', async () => {
  const w = mount(SceneRenderer, {
    props: { snapshot: scene('starline', 'survey', 'b', { echo_available: false }) },
  })
  expect(w.get('[data-visual=sonar]').attributes('data-available')).toBe('false')
  expect(w.find('[data-visual=scan-result]').exists()).toBe(false)
  await w.setProps({ snapshot: scene('starline', 'survey', 'b', { echo_available: true }) })
  expect(w.get('[data-visual=sonar]').attributes('data-available')).toBe('true')
  expect(w.find('[data-visual=gate]').exists()).toBe(false)
  await w.setProps({
    snapshot: scene('starline', 'survey', 'a', {
      scanned_segment: 'bridge_2',
      gate_position: 'east',
    }),
  })
  expect(w.get('[data-visual=scan-result]').text()).toContain('bridge_2')
  expect(w.get('[data-visual=gate]').attributes('x')).toBe('610')
  await w.setProps({
    snapshot: scene('starline', 'boarding', 'b', { rail_connected: true, signal_confirmed: true }),
  })
  expect(w.find('[data-visual=connected-rail]').exists()).toBe(true)
  expect(w.get('[data-visual=confirmed-signal]').attributes('data-confirmed')).toBe('true')
  w.unmount()
})
it('engine sonar and lamp never light one another', async () => {
  const w = mount(SceneRenderer, {
    props: {
      snapshot: scene('starline', 'survey', 'b', {
        engine_on: false,
        sonar_on: true,
        lamp_on: false,
      }),
    },
  })
  expect(w.get('[data-device=engine]').attributes('data-on')).toBe('false')
  expect(w.get('[data-device=sonar]').attributes('data-on')).toBe('true')
  expect(w.get('[data-device=lamp]').attributes('data-on')).toBe('false')
  await w.setProps({
    snapshot: scene('starline', 'boarding', 'b', {
      engine_on: true,
      sonar_on: false,
      lamp_on: true,
    }),
  })
  expect(w.get('[data-device=engine]').attributes('data-on')).toBe('true')
  expect(w.get('[data-device=sonar]').attributes('data-on')).toBe('false')
  expect(w.get('[data-device=lamp]').attributes('data-on')).toBe('true')
  w.unmount()
})
it.each([
  ['lighthouse', 'calibration', 'calibration-station'],
  ['lighthouse', 'repair', 'repair-workshop'],
  ['lighthouse', 'decision', 'joint-choice'],
  ['lighthouse', 'completed', 'ending'],
  ['starline', 'survey', 'survey-gap'],
  ['starline', 'boarding', 'boarding-signal'],
  ['starline', 'decision', 'joint-choice'],
  ['starline', 'completed', 'ending'],
])('%s %s renders actual stage geometry %s', (script, stage, geometry) => {
  const w = mount(SceneRenderer, { props: { snapshot: scene(script, stage) } })
  expect(w.find(`[data-visual=${geometry}]`).exists()).toBe(true)
  if (stage === 'completed') expect(w.find('button').exists()).toBe(false)
  if (stage !== 'calibration')
    expect(w.find('[data-visual=calibration-station]').exists()).toBe(false)
  if (stage !== 'repair') expect(w.find('[data-visual=repair-workshop]').exists()).toBe(false)
  if (stage !== 'survey') expect(w.find('[data-visual=survey-gap]').exists()).toBe(false)
  w.unmount()
})
it('background and cue images occupy separate layers; image decode errors preserve SVG and controls', async () => {
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = vi.fn(() => 'blob:TEST')
      static revokeObjectURL = vi.fn()
    },
  )
  const fetch = vi
    .fn()
    .mockImplementation(
      async () => new Response('test', { headers: { 'Content-Type': 'image/png' } }),
    )
  vi.stubGlobal('fetch', fetch)
  const image = {
    asset_id: 'background_one',
    kind: 'image',
    alt_text: 'TEST-ONLY',
    transcript: null,
  }
  const snapshot = parseGame({
    ...game(),
    script_id: 'lighthouse',
    scene_id: 'calibration',
    presentation: {
      background: image,
      cues: [
        {
          id: 'cue_one',
          alt_text: 'TEST-ONLY',
          assets: [
            { ...image, asset_id: 'overlay_one' },
            { ...image, kind: 'sfx', asset_id: 'sound_one' },
          ],
        },
      ],
    },
  })
  const w = mount(SceneRenderer, { props: { snapshot, sessionGeneration: 1 } })
  await flushPromises()
  expect(w.find('.scene-stage > .scene-background').exists()).toBe(true)
  expect(w.get('.scene-stage > .scene-overlay').attributes('data-cue')).toBe('cue_one')
  expect(w.find('figure').exists()).toBe(false)
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(new Headers(fetch.mock.calls[0]![1].headers).get('Authorization')).toBeNull()
  await w.get('.scene-background').trigger('error')
  expect(w.find('.scene-background').exists()).toBe(false)
  expect(w.find('svg').exists()).toBe(true)
  await w.get('.device-hotspot').trigger('click')
  expect(w.emitted('focusDevice')).toEqual([['emitter']])
  await w.setProps({ sessionGeneration: undefined })
  expect(w.find('img').exists()).toBe(false)
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  w.unmount()
})
it('observation prose and private device guesses never generate visual effects', () => {
  const snapshot = scene('lighthouse', 'calibration', 'b')
  snapshot.personal.observations = [{ topic: 'beam', text: '光束稳定，当前落向内湾航道。' }]
  snapshot.personal.devices = { filter: { filter: 'amber' } }
  const w = mount(SceneRenderer, { props: { snapshot } })
  expect(w.get('[data-visual=received-beam]').attributes('data-destination')).toBeUndefined()
  expect(w.find('[data-visual=received-beam] line').exists()).toBe(false)
  w.unmount()
})
it('visual parser rejects nested state and copies scalars without extra fields', () => {
  const raw = {
    ...game(),
    presentation: {
      background: null,
      cues: [],
      visual_state: [{ id: 'clock_powered', value: true, private_device: 'HIDDEN' }],
    },
  }
  expect(JSON.stringify(parseGame(raw))).not.toContain('HIDDEN')
  expect(() =>
    parseGame({
      ...raw,
      presentation: {
        ...raw.presentation,
        visual_state: [{ id: 'secret', value: { raw: 'HIDDEN' } }],
      },
    }),
  ).toThrow()
})
it('a rejected HTTP command keeps the rendered confirmed snapshot and device effects', async () => {
  setActivePinia(createPinia())
  const identity = useIdentityStore()
  identity.account = me.account
  identity.sessionGeneration = 1
  identity.initialized = true
  const initial = scene('lighthouse', 'calibration', 'a', {
    emitter_angle: 0,
    emitter_pattern: 'steady',
  })
  initial.presentation.background = {
    asset_id: 'missing_image',
    kind: 'image',
    alt_text: 'TEST-ONLY',
    transcript: null,
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(initial)))
  const store = useGameStore()
  await store.load('save_one')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })))
  const Host = defineComponent({
    components: { SceneRenderer, ActionPanel },
    setup() {
      return { snapshot: computed(() => store.snapshot), store }
    },
    template:
      '<SceneRenderer v-if="snapshot" :snapshot="snapshot" :session-generation="1"/><ActionPanel v-if="snapshot" :actions="snapshot.available_actions" :disabled="false" @command="store.submit" />',
  })
  const w = mount(Host)
  await flushPromises()
  expect(w.text()).toContain('图片暂不可用')
  let resolve!: (r: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => new Promise<Response>((r) => (resolve = r))),
  )
  await w.get('select[name=angle]').setValue('1')
  await w.get('select[name=pattern]').setValue('1')
  await w.get('form').trigger('submit')
  expect(w.get('.beam').attributes('style')).toContain('rotate(0deg)')
  await vi.waitFor(() => expect(resolve).toBeTypeOf('function'))
  resolve(
    json({ error: { code: 'INVALID_ARGUMENTS', message: 'rejected', retryable: false } }, 422),
  )
  await flushPromises()
  expect(w.get('.beam').attributes('style')).toContain('rotate(0deg)')
  expect(store.snapshot?.version).toBe(initial.version)
  expect(w.get('.beam').classes()).not.toContain('pulsed')
  w.unmount()
  store.reset()
})
