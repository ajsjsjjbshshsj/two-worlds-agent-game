import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SceneRenderer from '../src/components/game/SceneRenderer.vue'
import AudioControls from '../src/components/game/AudioControls.vue'
import { useAudioStore } from '../src/stores/audio'
import {
  cooperativeSnapshot as snapshot,
  cooperativeCases as cases,
  endings,
} from './cooperative-fixtures'
let wrappers: { unmount: () => void }[]
let tracks: { cancel: ReturnType<typeof vi.fn>; resolve: () => void }[]
let animate: ReturnType<typeof vi.fn>
let reduced = false,
  preference: (() => void) | undefined
beforeEach(() => {
  setActivePinia(createPinia())
  wrappers = []
  tracks = []
  reduced = false
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      get matches() {
        return reduced
      },
      addEventListener: (_e: string, fn: () => void) => (preference = fn),
      removeEventListener: vi.fn(),
    })),
  )
  animate = vi.fn(() => {
    let done!: (a: Animation) => void, fail!: (e: Error) => void
    const finished = new Promise<Animation>((resolve, reject) => {
      done = resolve
      fail = reject
    })
    const track = {
      cancel: vi.fn(() => fail(Error('cancelled'))),
      resolve: () => done({} as Animation),
    }
    tracks.push(track)
    return { finished, cancel: track.cancel }
  })
  Object.defineProperty(Element.prototype, 'animate', {
    configurable: true,
    writable: true,
    value: animate,
  })
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  delete (Element.prototype as Partial<Element>).animate
  vi.unstubAllGlobals()
})
function mountScene(s: ReturnType<typeof snapshot>) {
  const w = mount(SceneRenderer, { props: { snapshot: s } })
  wrappers.push(w)
  return w
}
function finalState(story: string, role: 'a' | 'b', ending: string, version = 11) {
  return snapshot(
    story,
    role,
    version,
    'completed',
    story === 'starline'
      ? { rail_connected: true, train_arrived: true }
      : { clock_repaired: true, signal_locked: true },
    ending,
  )
}
it.each(cases)(
  '$id / $role runs on real SVG targets and preserves the authorized final result',
  async (row) => {
    const w = mountScene(snapshot(row.story, row.role, 10, row.from, row.before))
    await w.setProps({ snapshot: snapshot(row.story, row.role, 11, row.to, row.after) })
    await flushPromises()
    expect(w.get('[data-performance]').attributes('data-performance')).toBe(row.id)
    expect(animate.mock.calls.length).toBeGreaterThan(0)
    const target = w.get(row.target)
    if (row.attr) expect(target.attributes(row.attr)).toBe(row.value)
    else if (row.value) expect(target.text()).toContain(row.value)
    tracks.forEach((t) => t.resolve())
    await flushPromises()
    expect(w.find('[data-performance]').exists()).toBe(false)
    expect(w.find(row.target).exists()).toBe(true)
    expect(tracks.every((t) => t.cancel.mock.calls.length > 0)).toBe(true)
  },
)
it.each(cases)(
  '$id / $role unsupported animation keeps final state and never blocks the game',
  async (row) => {
    const w = mountScene(snapshot(row.story, row.role, 10, row.from, row.before))
    animate.mockImplementation(() => {
      throw Error('unsupported')
    })
    const next = snapshot(row.story, row.role, 11, row.to, row.after),
      before = JSON.stringify(next)
    await w.setProps({ snapshot: next })
    await flushPromises()
    expect(w.text()).toContain('演出暂不可用')
    expect(w.find(row.target).exists()).toBe(true)
    expect(JSON.stringify(next)).toBe(before)
    expect(w.find('button[disabled]').exists()).toBe(false)
  },
)
it.each(endings)(
  '%s / %s is skippable in both roles and never sends a game command',
  async (story, ending, label) => {
    for (const role of ['a', 'b'] as const) {
      const w = mountScene(snapshot(story, role, 10, 'decision')),
        next = finalState(story, role, ending),
        before = JSON.stringify(next)
      await w.setProps({ snapshot: next })
      await flushPromises()
      const skip = w.get('button')
      expect(skip.text()).toBe('跳过演出')
      expect(skip.attributes('type')).toBe('button')
      expect(skip.attributes('disabled')).toBeUndefined()
      expect(w.get('[data-visual=ending-label]').text()).toBe(label)
      const current = [...tracks]
      await skip.trigger('click')
      await flushPromises()
      expect(current.every((t) => t.cancel.mock.calls.length > 0)).toBe(true)
      expect(w.find('.key-performance').exists()).toBe(false)
      expect(fetch).not.toHaveBeenCalled()
      expect(JSON.stringify(next)).toBe(before)
      expect(w.get('[data-visual=ending]').attributes('data-ending')).toBe(ending)
      const count = animate.mock.calls.length
      await w.setProps({ snapshot: { ...next } })
      await flushPromises()
      expect(animate).toHaveBeenCalledTimes(count)
      w.unmount()
      wrappers = wrappers.filter((item) => item !== w)
      const restored = mountScene(next)
      await flushPromises()
      expect(restored.find('.key-performance').exists()).toBe(false)
      expect(animate).toHaveBeenCalledTimes(count)
    }
  },
)
it.each(endings)(
  '%s / %s finishes without a click and keeps distinct final geometry and server text',
  async (story, ending, label) => {
    const w = mountScene(snapshot(story, 'a', 10, 'decision')),
      next = finalState(story, 'a', ending)
    await w.setProps({ snapshot: next })
    await flushPromises()
    tracks.forEach((t) => t.resolve())
    await flushPromises()
    expect(w.find('.key-performance').exists()).toBe(false)
    expect(w.get('[data-visual=ending-label]').text()).toBe(label)
    expect(next.public.recap.summary).toContain(ending)
    if (story === 'lighthouse')
      expect(w.find('[data-visual=waiting-tide]').exists()).toBe(ending === 'wait_tide')
    else {
      expect(w.find('[data-visual=rescue-route]').exists()).toBe(ending === 'rescue_detour')
      expect(
        w
          .get('[data-causal-part=ending-rail]')
          .element.parentElement?.getAttribute('data-causal-part'),
      ).toBe('ending-platform')
      if (ending === 'return_station')
        expect(w.get('[data-visual=train]').attributes('transform')).toBe(
          'translate(220 -40) scale(.8)',
        )
    }
  },
)
it.each(endings)(
  '%s / %s partial failure cancels every started track and preserves final state',
  async (story, ending, label) => {
    const w = mountScene(snapshot(story, 'b', 10, 'decision'))
    const native = animate.getMockImplementation()!
    animate.mockImplementationOnce(native).mockImplementationOnce(() => {
      throw Error('second track failed')
    })
    const next = finalState(story, 'b', ending),
      before = JSON.stringify(next)
    await w.setProps({ snapshot: next })
    await flushPromises()
    expect(tracks).toHaveLength(1)
    expect(tracks[0]!.cancel).toHaveBeenCalled()
    expect(w.text()).toContain('演出暂不可用')
    expect(w.get('[data-visual=ending-label]').text()).toBe(label)
    expect(JSON.stringify(next)).toBe(before)
    expect(w.find('.key-performance').exists()).toBe(false)
  },
)
it.each(['reduce', 'hidden', 'pagehide', 'unmount', 'save', 'role', 'script', 'credential'])(
  'critical %s cancels native tracks with a correct final static fallback',
  async (change) => {
    const w = mountScene(snapshot('starline', 'b', 10, 'decision'))
    const next = finalState('starline', 'b', 'rescue_detour')
    await w.setProps({ snapshot: next })
    await flushPromises()
    expect(tracks.length).toBeGreaterThan(0)
    if (change === 'reduce') {
      reduced = true
      preference?.()
    }
    if (change === 'hidden') {
      vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
      document.dispatchEvent(new Event('visibilitychange'))
    }
    if (change === 'pagehide') window.dispatchEvent(new Event('pagehide'))
    if (change === 'unmount') {
      w.unmount()
      wrappers = []
    }
    if (change === 'save') await w.setProps({ snapshot: { ...next, id: 'other_save' } })
    if (change === 'role') await w.setProps({ snapshot: { ...next, role: 'a' } })
    if (change === 'script')
      await w.setProps({ snapshot: finalState('lighthouse', 'b', 'wait_tide') })
    if (change === 'credential') await w.setProps({ sessionGeneration: 2 })
    await flushPromises()
    expect(tracks.every((t) => t.cancel.mock.calls.length > 0)).toBe(true)
    if (change !== 'unmount') {
      expect(w.find('.key-performance').exists()).toBe(false)
      expect(w.get('[data-visual=ending]').attributes('data-ending')).toBe(
        change === 'script' ? 'wait_tide' : 'rescue_detour',
      )
    }
  },
)
it.each(endings)(
  '%s / %s reduced-motion new ending updates final image without offering a historical skip',
  async (story, ending, label) => {
    reduced = true
    const w = mountScene(snapshot(story, 'a', 10, 'decision'))
    await w.setProps({ snapshot: finalState(story, 'a', ending) })
    await flushPromises()
    expect(animate).not.toHaveBeenCalled()
    expect(w.find('.key-performance').exists()).toBe(false)
    expect(w.get('[data-visual=ending-label]').text()).toBe(label)
  },
)
it.each([false, true])(
  'audio enabled=%s is independent of critical animation and skip',
  async (enabled) => {
    const initial = snapshot('lighthouse', 'a', 10, 'decision'),
      w = mountScene(initial),
      audio = mount(AudioControls, { props: { snapshot: initial, sessionGeneration: 1 } })
    wrappers.push(audio)
    if (enabled) {
      await audio.get('button').trigger('click')
      await flushPromises()
    }
    const stateBefore = { ...useAudioStore().state }
    const next = finalState('lighthouse', 'a', 'guide_now')
    await w.setProps({ snapshot: next })
    await audio.setProps({ snapshot: next })
    await flushPromises()
    expect(animate.mock.calls.length).toBeGreaterThan(0)
    await w.get('.key-performance button').trigger('click')
    expect(useAudioStore().state.enabled).toBe(stateBefore.enabled)
    expect(fetch).not.toHaveBeenCalled()
  },
)
it('opaque/missing media failure is independent of the confirmed ending and local skip', async () => {
  const w = mountScene(snapshot('lighthouse', 'a', 10, 'decision'))
  await w.setProps({ sessionGeneration: 1 })
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(Error('missing media')))
  const next = finalState('lighthouse', 'a', 'wait_tide')
  next.presentation.background = {
    asset_id: 'bg',
    kind: 'image',
    alt_text: 'TEST-ONLY',
    transcript: null,
  }
  await w.setProps({ snapshot: next })
  await flushPromises()
  expect(w.text()).toContain('图片暂不可用')
  expect(w.get('.key-performance button').text()).toBe('跳过演出')
  await w.get('.key-performance button').trigger('click')
  expect(w.get('[data-visual=ending-label]').text()).toContain('等待潮汐')
})
