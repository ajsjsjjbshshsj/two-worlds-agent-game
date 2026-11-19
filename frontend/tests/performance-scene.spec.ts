import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import SceneRenderer from '../src/components/game/SceneRenderer.vue'
import AudioControls from '../src/components/game/AudioControls.vue'
import ActionPanel from '../src/components/game/ActionPanel.vue'
import { animatePerformance } from '../src/services/performance-animation'
import type { Performance } from '../src/services/causal-performance'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { performanceSnapshot as snapshot } from './performance-fixture'
import { json, me } from './fixtures'
let wrappers: { unmount: () => void }[]
let animations: { cancel: ReturnType<typeof vi.fn>; resolve: () => void; reject: () => void }[]
let animate: ReturnType<typeof vi.fn>
let reduced = false
let onPreference: (() => void) | undefined
beforeEach(() => {
  setActivePinia(createPinia())
  wrappers = []
  animations = []
  reduced = false
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      get matches() {
        return reduced
      },
      addEventListener: (_name: string, callback: () => void) => {
        onPreference = callback
      },
      removeEventListener: vi.fn(),
    })),
  )
  animate = vi.fn(() => {
    let resolve!: (v: Animation) => void, reject!: (e: Error) => void
    const finished = new Promise<Animation>((a, b) => {
      resolve = a
      reject = b
    })
    const item = {
      cancel: vi.fn(() => reject(new Error('cancelled'))),
      resolve: () => resolve({} as Animation),
      reject: () => reject(new Error('animation failed')),
    }
    animations.push(item)
    return { finished, cancel: item.cancel }
  })
  vi.stubGlobal('fetch', vi.fn())
  Object.defineProperty(Element.prototype, 'animate', {
    configurable: true,
    writable: true,
    value: animate,
  })
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  delete (Element.prototype as Partial<Element>).animate
  vi.unstubAllGlobals()
})
function mountScene(s = snapshot()) {
  const w = mount(SceneRenderer, { props: { snapshot: s } })
  wrappers.push(w)
  return w
}
it.each([
  ['lighthouse', 'a'],
  ['starline', 'b'],
])('initial %s true state is static, with no historical animation', async (story, role) => {
  const w = mountScene(snapshot(story, role, 10, true))
  await flushPromises()
  expect(animate).not.toHaveBeenCalled()
  expect(
    w
      .get(story === 'lighthouse' ? '[data-visual=clock]' : '[data-visual=sonar]')
      .attributes(story === 'lighthouse' ? 'data-powered' : 'data-available'),
  ).toBe('true')
})
it('Lighthouse circuit lights only on confirmed false-to-true and retains final color after finish', async () => {
  const w = mountScene()
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 11, true) })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(2)
  expect(w.get('[data-performance]').attributes('data-performance')).toBe('clock-power-on')
  expect(w.get('[data-causal-part=clock-circuit]').attributes('stroke')).toBe('#f6cf72')
  animations.forEach((a) => a.resolve())
  await flushPromises()
  expect(w.find('[data-performance]').exists()).toBe(false)
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('true')
  expect(animations.every((a) => a.cancel.mock.calls.length > 0)).toBe(true)
})
it('Starline has three outward wave tracks then keeps the confirmed ready rings', async () => {
  const w = mountScene(snapshot('starline', 'b'))
  await w.setProps({ snapshot: snapshot('starline', 'b', 11, true) })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(4)
  expect(w.findAll('[data-causal-part=sonar-wave]')).toHaveLength(3)
  expect(animate.mock.calls[0]![0]).toEqual([
    { transform: 'scale(.25)', opacity: 0.85 },
    { transform: 'scale(1.35)', opacity: 0 },
  ])
  expect(animate.mock.calls[1]![1]).toMatchObject({ delay: 140, fill: 'none' })
  animations.forEach((a) => a.resolve())
  await flushPromises()
  expect(w.get('[data-visual=sonar]').attributes('data-available')).toBe('true')
})
it('same-version reread does not restart and a version gap goes straight to final state', async () => {
  const w = mountScene()
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 11, true) })
  await flushPromises()
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 11, true) })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(2)
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 14, false) })
  await flushPromises()
  expect(animations.every((a) => a.cancel.mock.calls.length > 0)).toBe(true)
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 16, true) })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(2)
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('true')
})
it.each(['save', 'role', 'script', 'unmount'])(
  '%s switch cancels old DOM animations',
  async (change) => {
    const w = mountScene()
    await w.setProps({ snapshot: snapshot('lighthouse', 'a', 11, true) })
    await flushPromises()
    if (change === 'unmount') {
      w.unmount()
      wrappers = []
    } else
      await w.setProps({
        snapshot:
          change === 'save'
            ? { ...snapshot('lighthouse', 'a', 12, true), id: 'save_other' }
            : change === 'role'
              ? snapshot('lighthouse', 'b', 12, true)
              : snapshot('starline', 'b', 12, true),
      })
    await flushPromises()
    expect(animations.every((a) => a.cancel.mock.calls.length > 0)).toBe(true)
    expect(animate).toHaveBeenCalledTimes(2)
  },
)
it('reduced motion skips playback, and changing the preference cancels active tracks', async () => {
  reduced = true
  const w = mountScene()
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 11, true) })
  await flushPromises()
  expect(animate).not.toHaveBeenCalled()
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('true')
  reduced = false
  onPreference?.()
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 12, false) })
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 13, true) })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(2)
  reduced = true
  onPreference?.()
  await flushPromises()
  expect(animations.every((a) => a.cancel.mock.calls.length > 0)).toBe(true)
})
it('audio off and even a denied image load cannot block animation or synthesize operation SFX', async () => {
  const w = mountScene()
  const audio = mount(AudioControls, { props: { snapshot: snapshot(), sessionGeneration: 1 } })
  wrappers.push(audio)
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(Error('image unavailable')))
  const next = snapshot('lighthouse', 'a', 11, true)
  next.presentation.background = {
    asset_id: 'bg',
    kind: 'image',
    alt_text: 'TEST-ONLY',
    transcript: null,
  }
  await w.setProps({ snapshot: next, sessionGeneration: 1 })
  await flushPromises()
  // Credential change is a new lifecycle, not a transition. Use the next adjacent rise.
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 12, false) })
  await w.setProps({ snapshot: { ...next, version: 13 } })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(2)
  expect(audio.text()).toContain('声音已关闭')
  expect(w.text()).toContain('图片暂不可用')
  expect(fetch).toHaveBeenCalledTimes(2)
})
it('partial animation failure cleans up tracks but preserves accepted state and controls', async () => {
  const w = mountScene()
  animate
    .mockImplementationOnce(() => {
      let reject!: (e: Error) => void
      const finished = new Promise<Animation>((_, r) => (reject = r))
      const cancel = vi.fn(() => reject(Error('cancel')))
      animations.push({ cancel, resolve: () => {}, reject: () => {} })
      return { finished, cancel }
    })
    .mockImplementationOnce(() => {
      throw Error('unsupported')
    })
  const next = snapshot('lighthouse', 'a', 11, true),
    before = JSON.stringify(next)
  await w.setProps({ snapshot: next })
  await flushPromises()
  expect(w.text()).toContain('演出暂不可用')
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('true')
  expect(animations[0]!.cancel).toHaveBeenCalled()
  expect(JSON.stringify(next)).toBe(before)
  const panel = mount(ActionPanel, { props: { actions: next.available_actions, disabled: false } })
  wrappers.push(panel)
  expect(panel.get('button').attributes('disabled')).toBeUndefined()
})
it.each([
  ['lighthouse', 'b', 'power_target'],
  ['starline', 'a', 'gate_position'],
])('%s wrong role cannot animate a private counterpart configuration', async (story, role, own) => {
  const first = snapshot(story, role),
    second = snapshot(story, role, 11, true)
  first.presentation.visual_state = []
  second.presentation.visual_state = [{ id: own, value: 'TEST-ONLY own' }]
  const w = mountScene(first)
  await w.setProps({ snapshot: second })
  await flushPromises()
  expect(animate).not.toHaveBeenCalled()
  expect(w.find('[data-performance]').exists()).toBe(false)
  expect(
    w
      .find(
        story === 'lighthouse'
          ? '[data-causal-part=clock-circuit]'
          : '[data-causal-part=sonar-wave]',
      )
      .exists(),
  ).toBe(false)
})
it('late HTTP read is discarded by the game store before it can overwrite a newer performance', async () => {
  const identity = useIdentityStore()
  identity.sessionGeneration = 1
  identity.account = me.account
  identity.initialized = true
  const store = useGameStore()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(snapshot())))
  await store.load('save_one')
  const w = mountScene(store.snapshot!)
  let older!: (r: Response) => void, newer!: (r: Response) => void
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementationOnce(() => new Promise((r) => (older = r)))
      .mockImplementationOnce(() => new Promise((r) => (newer = r))),
  )
  const oldRead = store.load('save_one'),
    newRead = store.load('save_one')
  newer(json(snapshot('lighthouse', 'a', 11, true)))
  await newRead
  await w.setProps({ snapshot: store.snapshot! })
  await flushPromises()
  const key = w.get('[data-performance]').attributes('data-performance-key')
  older(json(snapshot()))
  await oldRead
  await w.setProps({ snapshot: store.snapshot! })
  await flushPromises()
  expect(store.snapshot!.version).toBe(11)
  expect(w.get('[data-performance]').attributes('data-performance-key')).toBe(key)
  expect(animate).toHaveBeenCalledTimes(2)
})
it('runner immediately ignores an already-cancelled lifecycle', async () => {
  const controller = new AbortController()
  controller.abort()
  await animatePerformance(
    document.createElementNS('http://www.w3.org/2000/svg', 'svg'),
    { id: 'clock-power-on' } as Performance,
    controller.signal,
  )
  expect(animate).not.toHaveBeenCalled()
})
it('confirmed echo readiness animates with audio enabled without inventing an operation sound', async () => {
  const first = snapshot('starline', 'b')
  first.presentation.operation_sfx = ['power_switch']
  first.presentation.cues = [
    {
      id: 'survey_b_power_switch',
      alt_text: 'TEST-ONLY',
      assets: [
        {
          asset_id: 'power_switch',
          kind: 'sfx',
          alt_text: 'TEST-ONLY 本人开关声',
          transcript: null,
        },
      ],
    },
  ]
  const scene = mountScene(first),
    audio = mount(AudioControls, { props: { snapshot: first, sessionGeneration: 1 } })
  wrappers.push(audio)
  await audio.get('button').trigger('click')
  await flushPromises()
  const next = {
    ...first,
    version: 11,
    presentation: { ...first.presentation, visual_state: [{ id: 'echo_available', value: true }] },
  }
  await scene.setProps({ snapshot: next })
  await audio.setProps({ snapshot: next })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(4)
  expect(fetch).not.toHaveBeenCalled()
  await scene.setProps({ snapshot: { ...next } })
  await audio.setProps({ snapshot: { ...next } })
  await flushPromises()
  expect(animate).toHaveBeenCalledTimes(4)
  expect(fetch).not.toHaveBeenCalled()
})
it('return from background does not animate an unseen operation while away', async () => {
  const w = mountScene()
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  document.dispatchEvent(new Event('visibilitychange'))
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  document.dispatchEvent(new Event('visibilitychange'))
  await w.setProps({ snapshot: snapshot('lighthouse', 'a', 11, true) })
  await flushPromises()
  expect(animate).not.toHaveBeenCalled()
  expect(w.get('[data-visual=clock]').attributes('data-powered')).toBe('true')
})
