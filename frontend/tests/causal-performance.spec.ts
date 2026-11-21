import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { CausalPerformance, type PerformanceState } from '../src/services/causal-performance'
import { performanceSnapshot as snapshot } from './performance-fixture'
let coordinator: CausalPerformance | undefined
afterEach(() => coordinator?.reset())
function setup() {
  const pending: { resolve: () => void; reject: () => void; signal: AbortSignal }[] = []
  const states: PerformanceState[] = []
  const play = vi.fn(
    (_effect, signal: AbortSignal) =>
      new Promise<void>((resolve, reject) =>
        pending.push({ resolve, reject: () => reject(Error('failed')), signal }),
      ),
  )
  coordinator = new CausalPerformance(play, (s) => states.push(s))
  return { c: coordinator, play, pending, states }
}
it('initial already-powered save restores without historical performance', () => {
  const { c, play } = setup()
  c.update(snapshot('lighthouse', 'a', 20, true))
  expect(play).not.toHaveBeenCalled()
})
it('recovery establishes a new static baseline even when exactly one version was missed', () => {
  const { c, play } = setup()
  c.update(snapshot())
  c.update({ ...snapshot('lighthouse', 'a', 11, true), restored: true })
  c.update(snapshot('lighthouse', 'a', 11, true))
  expect(play).not.toHaveBeenCalled()
  c.update(snapshot('lighthouse', 'a', 12, false))
  c.update(snapshot('lighthouse', 'a', 13, true))
  expect(play).toHaveBeenCalledOnce()
})
it.each([
  ['lighthouse', 'a', 'clock-power-on'],
  ['starline', 'b', 'echo-ready'],
])('new adjacent %s snapshot starts the authorized performance', async (story, role, id) => {
  const { c, play, pending, states } = setup()
  c.update(snapshot(story, role))
  c.update(snapshot(story, role, 11, true))
  expect(play).toHaveBeenCalledTimes(1)
  expect(play.mock.calls[0]![0]).toMatchObject({
    id,
    save_id: 'save_one',
    accepted_version: 11,
    generation: expect.any(Number),
    key: expect.any(String),
  })
  pending[0]!.resolve()
  await flushPromises()
  expect(states.at(-1)).toEqual({ active: null, failed: false })
})
it('duplicate reads and inconsistent same-version snapshots cannot replay or cancel active animation', () => {
  const { c, play, pending } = setup()
  c.update(snapshot())
  c.update(snapshot('lighthouse', 'a', 11, true))
  c.update(snapshot('lighthouse', 'a', 11, true))
  c.update(snapshot('lighthouse', 'a', 11, false))
  expect(play).toHaveBeenCalledTimes(1)
  expect(pending[0]!.signal.aborted).toBe(false)
})
it('version gaps render final state and establish the next baseline without reconstructing history', () => {
  const { c, play } = setup()
  c.update(snapshot())
  c.update(snapshot('lighthouse', 'a', 13, true))
  expect(play).not.toHaveBeenCalled()
  c.update(snapshot('lighthouse', 'a', 14, false))
  c.update(snapshot('lighthouse', 'a', 15, true))
  expect(play).toHaveBeenCalledTimes(1)
})
it.each(['save', 'role', 'script', 'script-version', 'credential', 'scene'])(
  '%s switch cancels prior work and does not animate a new scope baseline',
  async (change) => {
    const { c, play, pending, states } = setup()
    c.update(snapshot(), 1)
    c.update(snapshot('lighthouse', 'a', 11, true), 1)
    const next = {
      ...snapshot('lighthouse', 'a', 12, true),
      ...(change === 'save' ? { id: 'other_save' } : {}),
      ...(change === 'role' ? { role: 'b' as const } : {}),
      ...(change === 'script' ? { script_id: 'starline' } : {}),
      ...(change === 'script-version' ? { script_version: '2.0.0' } : {}),
      ...(change === 'scene' ? { scene_id: 'decision' } : {}),
    }
    c.update(next, change === 'credential' ? 2 : 1)
    expect(pending[0]!.signal.aborted).toBe(true)
    pending[0]!.resolve()
    await flushPromises()
    expect(states.at(-1)?.active).toBeNull()
    expect(play).toHaveBeenCalledTimes(1)
  },
)
it('late older snapshot and completion cannot overwrite a newer performance', async () => {
  const { c, play, pending, states } = setup()
  c.update(snapshot())
  c.update(snapshot('lighthouse', 'a', 11, true))
  c.update(snapshot('lighthouse', 'a', 12, false))
  c.update(snapshot('lighthouse', 'a', 13, true))
  const current = states.at(-1)?.active
  c.update(snapshot('lighthouse', 'a', 11, true))
  pending[0]!.resolve()
  await flushPromises()
  expect(states.at(-1)?.active).toEqual(current)
  expect(play).toHaveBeenCalledTimes(2)
  expect(pending[1]!.signal.aborted).toBe(false)
})
it('reduced motion/background cancels immediately and does not replay on reenable', () => {
  const { c, play, pending } = setup()
  c.update(snapshot())
  c.update(snapshot('lighthouse', 'a', 11, true))
  c.setMotionAllowed(false)
  expect(pending[0]!.signal.aborted).toBe(true)
  c.update(snapshot('lighthouse', 'a', 12, false))
  c.update(snapshot('lighthouse', 'a', 13, true))
  c.setMotionAllowed(true)
  c.update(snapshot('lighthouse', 'a', 13, true))
  expect(play).toHaveBeenCalledTimes(1)
})
it('reset isolates page generation; late rejection does not report an error on the new page', async () => {
  const { c, play, pending, states } = setup()
  c.update(snapshot())
  c.update(snapshot('lighthouse', 'a', 11, true))
  const generation = states.at(-1)!.active!.generation
  c.reset()
  c.update(snapshot())
  c.update(snapshot('lighthouse', 'a', 11, true))
  pending[0]!.reject()
  await flushPromises()
  expect(states.at(-1)?.active?.generation).toBeGreaterThan(generation)
  expect(states.at(-1)?.failed).toBe(false)
  expect(play).toHaveBeenCalledTimes(2)
})
it('animation failure never mutates accepted snapshot or prevents future work', async () => {
  const { c, pending, states } = setup()
  const confirmed = snapshot('lighthouse', 'a', 11, true),
    before = JSON.stringify(confirmed)
  c.update(snapshot())
  c.update(confirmed)
  pending[0]!.reject()
  await flushPromises()
  expect(states.at(-1)).toEqual({ active: null, failed: true })
  expect(JSON.stringify(confirmed)).toBe(before)
})
it.each([
  ['lighthouse', 'b'],
  ['starline', 'a'],
])('ignores unauthorized %s role even if an extra flag is supplied', (story, role) => {
  const { c, play } = setup()
  c.update(snapshot(story, role))
  c.update(snapshot(story, role, 11, true))
  expect(play).not.toHaveBeenCalled()
})
it('does not infer readiness from prose, other devices, missing or truthy string flags', () => {
  const { c, play } = setup()
  const first = snapshot()
  first.presentation.visual_state = []
  c.update(first)
  const next = snapshot('lighthouse', 'a', 11, true)
  next.personal.observations = [{ topic: 'scene', text: '时钟箱已通电' }]
  next.personal.devices.power_router = { target: 'tower' }
  c.update(next)
  expect(play).not.toHaveBeenCalled()
})
it('first snapshot after time spent hidden is a baseline even if exactly one operation occurred', () => {
  const { c, play } = setup()
  c.update(snapshot())
  c.setMotionAllowed(false)
  c.setMotionAllowed(true)
  c.update(snapshot('lighthouse', 'a', 11, true))
  expect(play).not.toHaveBeenCalled()
})
