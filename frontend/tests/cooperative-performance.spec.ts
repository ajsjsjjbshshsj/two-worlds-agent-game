import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { CausalPerformance, type PerformanceState } from '../src/services/causal-performance'
import {
  cooperativeSnapshot as snapshot,
  cooperativeCases as cases,
  endings,
} from './cooperative-fixtures'
let coordinator: CausalPerformance | undefined
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
afterEach(() => {
  coordinator?.reset()
  vi.unstubAllGlobals()
})
it.each(cases)(
  '$id / $role triggers from confirmed authorized result and repeats never restart it',
  async (row) => {
    const { c, play, pending, states } = setup()
    const old = snapshot(row.story, row.role, 10, row.from, row.before),
      next = snapshot(row.story, row.role, 11, row.to, row.after),
      before = JSON.stringify(next)
    c.update(old)
    expect(play).not.toHaveBeenCalled()
    c.update(next)
    expect(play).toHaveBeenCalledTimes(1)
    expect(states.at(-1)?.active).toMatchObject({
      id: row.id,
      accepted_version: 11,
      role: row.role,
    })
    c.update({ ...next })
    expect(play).toHaveBeenCalledTimes(1)
    expect(pending[0]!.signal.aborted).toBe(false)
    pending[0]!.resolve()
    await flushPromises()
    expect(states.at(-1)?.active).toBeNull()
    expect(JSON.stringify(next)).toBe(before)
  },
)
it.each(cases)(
  '$id / $role initial state, gaps and reduced motion never replay a historical milestone',
  (row) => {
    const { c, play } = setup()
    c.update(snapshot(row.story, row.role, 11, row.to, row.after))
    expect(play).not.toHaveBeenCalled()
    c.reset()
    c.update(snapshot(row.story, row.role, 10, row.from, row.before))
    c.update(snapshot(row.story, row.role, 12, row.to, row.after))
    expect(play).not.toHaveBeenCalled()
    c.reset()
    c.setMotionAllowed(false)
    c.update(snapshot(row.story, row.role, 10, row.from, row.before))
    c.update(snapshot(row.story, row.role, 11, row.to, row.after))
    c.setMotionAllowed(true)
    c.update(snapshot(row.story, row.role, 11, row.to, row.after))
    expect(play).not.toHaveBeenCalled()
  },
)
it.each(cases.filter((c) => c.story === 'lighthouse'))(
  '$id rejects the other private role',
  (row) => {
    const { c, play } = setup(),
      role = row.role === 'a' ? 'b' : 'a'
    c.update(snapshot(row.story, role, 10, row.from, row.before))
    c.update(snapshot(row.story, role, 11, row.to, row.after))
    expect(play.mock.calls.every(([effect]) => effect.id !== row.id)).toBe(true)
  },
)
it('missing public scan result is not inferred from private devices or observation prose', () => {
  const { c, play } = setup()
  const old = snapshot('starline', 'a', 10, 'survey'),
    next = snapshot('starline', 'a', 11, 'survey')
  next.personal.devices.sonar = { scanned: true }
  next.personal.observations = [{ topic: 'scan', text: '扫描成功，轨道已定位' }]
  c.update(old)
  c.update(next)
  expect(play).not.toHaveBeenCalled()
})
it.each(endings)(
  '%s / %s critical sequence requires adjacent decision-to-completed and can be skipped locally',
  async (story, ending) => {
    for (const role of ['a', 'b'] as const) {
      const { c, play, pending, states } = setup()
      const old = snapshot(story, role, 10, 'decision'),
        next = snapshot(story, role, 11, 'completed', {}, ending),
        before = JSON.stringify(next)
      c.update(old)
      c.update(next)
      expect(states.at(-1)?.active).toMatchObject({
        id: `${story}-ending`,
        skippable: true,
        ending,
        accepted_version: 11,
        role,
      })
      c.skip()
      expect(pending[0]!.signal.aborted).toBe(true)
      expect(states.at(-1)).toEqual({ active: null, failed: false })
      c.update({ ...next })
      expect(play).toHaveBeenCalledTimes(1)
      pending[0]!.reject()
      await flushPromises()
      expect(states.at(-1)?.failed).toBe(false)
      expect(JSON.stringify(next)).toBe(before)
      c.reset()
      c.update(next)
      expect(play).toHaveBeenCalledTimes(1)
    }
  },
)
it.each(endings)(
  '%s / %s initial, skipped versions, arbitrary scene changes and unknown endings do not play',
  (story, ending) => {
    const { c, play } = setup()
    c.update(snapshot(story, 'a', 11, 'completed', {}, ending))
    expect(play).not.toHaveBeenCalled()
    c.reset()
    c.update(snapshot(story, 'a', 10, 'decision'))
    c.update(snapshot(story, 'a', 12, 'completed', {}, ending))
    expect(play).not.toHaveBeenCalled()
    c.reset()
    c.update(snapshot(story, 'a', 10, story === 'lighthouse' ? 'repair' : 'survey'))
    c.update(snapshot(story, 'a', 11, 'completed', {}, ending))
    expect(play).not.toHaveBeenCalled()
    c.reset()
    c.update(snapshot(story, 'a', 10, 'decision'))
    c.update(snapshot(story, 'a', 11, 'completed', {}, 'unknown_ending'))
    expect(play).not.toHaveBeenCalled()
  },
)
it.each(['save', 'pair', 'role', 'script', 'version', 'credential', 'unmount', 'hidden'])(
  'critical %s switch cancels old work and ignores late completion',
  async (change) => {
    const { c, play, pending, states } = setup()
    c.update(snapshot('lighthouse', 'a', 10, 'decision'), 'TEST')
    c.update(snapshot('lighthouse', 'a', 11, 'completed', {}, 'guide_now'), 'TEST')
    const next = {
      ...snapshot('lighthouse', 'a', 12, 'completed', {}, 'guide_now'),
      ...(change === 'save' ? { id: 'save_other' } : {}),
      ...(change === 'pair' ? { pair_id: 'pair_other' } : {}),
      ...(change === 'role' ? { role: 'b' as const } : {}),
      ...(change === 'script' ? { script_id: 'starline' } : {}),
      ...(change === 'version' ? { script_version: '2.0.0' } : {}),
    }
    if (change === 'unmount') c.reset()
    else if (change === 'hidden') c.setMotionAllowed(false)
    else c.update(next, change === 'credential' ? 'OTHER' : 'TEST')
    expect(pending[0]!.signal.aborted).toBe(true)
    pending[0]!.resolve()
    await flushPromises()
    expect(states.at(-1)?.active).toBeNull()
    expect(play).toHaveBeenCalledTimes(1)
  },
)
it('rail scene change requires the exact survey-to-boarding milestone, not just a new scene or unknown flag', () => {
  const { c, play } = setup()
  c.update(snapshot('starline', 'b', 10, 'survey', { rail_connected: false }))
  c.update(snapshot('starline', 'b', 11, 'boarding', { rail_connected: false }))
  expect(play).not.toHaveBeenCalled()
  c.reset()
  c.update(snapshot('starline', 'b', 10, 'boarding', { rail_connected: false }))
  c.update(snapshot('starline', 'b', 11, 'decision', { rail_connected: true }))
  expect(play).not.toHaveBeenCalled()
})
it('skipping a short ordinary feedback is a no-op and cannot cancel an unrelated lifecycle', () => {
  const { c, pending } = setup()
  c.update(snapshot('lighthouse', 'a', 10, 'repair', { clock_powered: false }))
  c.update(snapshot('lighthouse', 'a', 11, 'repair', { clock_powered: true }))
  c.skip()
  expect(pending[0]!.signal.aborted).toBe(false)
})
