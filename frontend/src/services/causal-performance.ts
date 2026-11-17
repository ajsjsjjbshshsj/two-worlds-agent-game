import type { GameSnapshot } from '../types/game'

export type PerformanceId = 'clock-power-on' | 'echo-ready'
export interface Performance {
  id: PerformanceId
  save_id: string
  accepted_version: number
  generation: number
  key: string
}
export interface PerformanceState {
  active: Performance | null
  failed: boolean
}
export type PerformancePlayer = (effect: Performance, signal: AbortSignal) => Promise<void>
interface Baseline {
  scope: string
  version: number
  scene: string
  clock: boolean | undefined
  echo: boolean | undefined
}
function baseline(s: GameSnapshot): Baseline {
  const visual = Object.fromEntries((s.presentation.visual_state ?? []).map((v) => [v.id, v.value]))
  const flag = (value: unknown) => (typeof value === 'boolean' ? value : undefined)
  return {
    scope: JSON.stringify([s.id, s.pair_id, s.script_id, s.script_version, s.role]),
    version: s.version,
    scene: s.scene_id,
    clock: flag(visual.clock_powered),
    echo: flag(visual.echo_available),
  }
}
// Receives only accepted personal snapshots. It has no rule/command/audio tools.
export class CausalPerformance {
  private previous: Baseline | null = null
  private credential = ''
  private generation = 0
  private seen = new Set<string>()
  private current: AbortController | null = null
  private motionAllowed = true
  constructor(
    private play: PerformancePlayer,
    private changed: (s: PerformanceState) => void = () => {},
  ) {}
  update(snapshot: GameSnapshot, credential = '') {
    const next = baseline(snapshot),
      old = this.previous
    if (!old || next.scope !== old.scope || credential !== this.credential) {
      this.reset()
      this.credential = credential
      this.previous = next
      return // First read restores the final image, including an already-true flag.
    }
    if (next.version <= old.version) return
    this.cancel()
    this.previous = next // Copy primitive facts; later mutations cannot change history.
    if (snapshot.completed || next.version !== old.version + 1 || next.scene !== old.scene) return
    let id: PerformanceId | undefined
    if (
      snapshot.script_id === 'lighthouse' &&
      snapshot.role === 'a' &&
      next.scene === 'repair' &&
      old.clock === false &&
      next.clock === true
    )
      id = 'clock-power-on'
    if (
      snapshot.script_id === 'starline' &&
      snapshot.role === 'b' &&
      next.scene === 'survey' &&
      old.echo === false &&
      next.echo === true
    )
      id = 'echo-ready'
    if (!id) return
    const effect: Performance = {
      id,
      save_id: snapshot.id,
      accepted_version: snapshot.version,
      generation: this.generation,
      key: `${next.scope}:${snapshot.version}:${id}:${this.generation}`,
    }
    if (this.seen.has(effect.key)) return
    this.seen.add(effect.key) // Reduced motion/background changes never build a backlog.
    if (!this.motionAllowed) return
    const controller = new AbortController()
    this.current = controller
    this.changed({ active: effect, failed: false })
    void this.run(effect, controller)
  }
  private async run(effect: Performance, controller: AbortController) {
    let failed = false
    try {
      await this.play(effect, controller.signal)
    } catch {
      failed = !controller.signal.aborted
    }
    if (
      this.current !== controller ||
      controller.signal.aborted ||
      effect.generation !== this.generation
    )
      return
    this.current = null
    this.changed({ active: null, failed })
  }
  setMotionAllowed(allowed: boolean) {
    this.motionAllowed = allowed
    if (!allowed) this.reset()
  }
  private cancel() {
    this.current?.abort()
    this.current = null
    this.changed({ active: null, failed: false })
  }
  reset() {
    this.cancel()
    this.generation++
    this.previous = null
    this.credential = ''
    this.seen.clear()
  }
}
