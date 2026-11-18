import type { GameSnapshot } from '../types/game'

export type PerformanceId =
  | 'clock-power-on'
  | 'echo-ready'
  | 'beam-focus'
  | 'clock-repaired'
  | 'route-ready'
  | 'track-scan'
  | 'rail-connected'
  | 'lighthouse-ending'
  | 'starline-ending'
export interface Performance {
  id: PerformanceId
  save_id: string
  accepted_version: number
  generation: number
  key: string
  role?: GameSnapshot['role']
  skippable?: boolean
  ending?: string
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
  repaired: boolean | undefined
  route: boolean | undefined
  rail: boolean | undefined
  quality: string | undefined
  destination: string | undefined
  segment: string | undefined
  completed: boolean
  ending: string | null
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
    repaired: flag(visual.clock_repaired),
    route: flag(visual.route_ready),
    rail: flag(visual.rail_connected),
    quality: typeof visual.beam_quality === 'string' ? visual.beam_quality : undefined,
    destination: typeof visual.beam_destination === 'string' ? visual.beam_destination : undefined,
    segment:
      typeof visual.scanned_segment === 'string' && visual.scanned_segment
        ? visual.scanned_segment
        : undefined,
    completed: s.completed,
    ending: s.public.ending,
  }
}
// Receives only accepted personal snapshots. It has no rule/command/audio tools.
export class CausalPerformance {
  private previous: Baseline | null = null
  private credential = ''
  private generation = 0
  private seen = new Set<string>()
  private current: AbortController | null = null
  private active: Performance | null = null
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
    if (next.version !== old.version + 1) return
    let id: PerformanceId | undefined
    const lighthouse = snapshot.script_id === 'lighthouse'
    const starline = snapshot.script_id === 'starline'
    // The only ending transition accepted by the player: a newly confirmed
    // completed save from decision, with a public ending supported by this story.
    if (
      old.scene === 'decision' &&
      next.scene === 'completed' &&
      !old.completed &&
      next.completed &&
      old.ending === null
    ) {
      if (lighthouse && (next.ending === 'guide_now' || next.ending === 'wait_tide'))
        id = 'lighthouse-ending'
      if (starline && (next.ending === 'rescue_detour' || next.ending === 'return_station'))
        id = 'starline-ending'
    } else if (!next.completed) {
      // Rail installation is a specifically authorized cross-scene milestone;
      // arbitrary scene changes do not create a transition or replay history.
      if (
        starline &&
        old.scene === 'survey' &&
        next.scene === 'boarding' &&
        old.rail === false &&
        next.rail === true
      )
        id = 'rail-connected'
      if (next.scene === old.scene) {
        if (lighthouse && next.scene === 'repair') {
          if (snapshot.role === 'a' && old.clock === false && next.clock === true)
            id = 'clock-power-on'
          if (snapshot.role === 'a' && old.repaired === false && next.repaired === true)
            id = 'clock-repaired'
          if (snapshot.role === 'b' && old.route === false && next.route === true)
            id = 'route-ready'
        }
        if (
          lighthouse &&
          snapshot.role === 'b' &&
          next.scene === 'calibration' &&
          old.quality === 'blurred' &&
          next.quality === 'clear' &&
          next.destination
        )
          id = 'beam-focus'
        if (starline && next.scene === 'survey') {
          if (snapshot.role === 'b' && old.echo === false && next.echo === true) id = 'echo-ready'
          if (old.segment === undefined && next.segment !== undefined) id = 'track-scan'
        }
      }
    }
    if (!id) return
    const effect: Performance = {
      id,
      save_id: snapshot.id,
      accepted_version: snapshot.version,
      generation: this.generation,
      key: `${next.scope}:${snapshot.version}:${id}:${this.generation}`,
      role: snapshot.role,
      ...(id === 'lighthouse-ending' || id === 'starline-ending'
        ? { skippable: true, ending: next.ending! }
        : {}),
    }
    if (this.seen.has(effect.key)) return
    this.seen.add(effect.key) // Reduced motion/background changes never build a backlog.
    if (!this.motionAllowed) return
    const controller = new AbortController()
    this.current = controller
    this.active = effect
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
    this.active = null
    this.changed({ active: null, failed })
  }
  skip() {
    if (this.active?.skippable) this.cancel()
  }
  setMotionAllowed(allowed: boolean) {
    this.motionAllowed = allowed
    if (!allowed) this.reset()
  }
  private cancel() {
    this.current?.abort()
    this.current = null
    this.active = null
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
