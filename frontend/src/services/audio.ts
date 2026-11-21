import type { AudioCue, AudioPreferences, AudioState } from '../types/audio'
import { audioCues, operationAudioCues } from './audio-assets'
import { ApiError } from './http'
import { protectedAudio } from './media'
import type { GameSnapshot } from '../types/game'
interface Track {
  cue: AudioCue
  element: HTMLAudioElement
  dispose: () => void
  gain: number
  timer?: ReturnType<typeof setInterval>
}
interface Dependencies {
  element: () => HTMLAudioElement
  load: typeof protectedAudio
}
const defaults: Dependencies = { element: () => new Audio(), load: protectedAudio }
export class AudioManager {
  readonly state: AudioState = {
    enabled: false,
    paused: false,
    status: 'off',
    message: '',
    voiceKey: null,
    time: 0,
  }
  private scope = ''
  private sessionGeneration: number | undefined
  private saveId = ''
  private version = -1
  private scene = ''
  private epoch = 0
  private seen = new Set<string>()
  private failed = new Set<string>()
  private cues: AudioCue[] = []
  private tracks = new Map<string, Track>()
  private pending = new Map<string, AbortController>()
  private retired = new Set<Track>()
  private preferences: AudioPreferences = {
    volumes: { ambient: 0.5, sfx: 0.7, voice: 1 },
    muted: false,
  }
  constructor(
    private changed: (state: AudioState) => void = () => {},
    private deps: Dependencies = defaults,
    private sessionExpired: (generation: number) => void = () => {},
  ) {}
  private notify() {
    this.changed({ ...this.state })
  }
  update(snapshot: GameSnapshot, sessionGeneration: number) {
    const scope = [snapshot.id, snapshot.script_id, snapshot.script_version, snapshot.role].join(
      ':',
    )
    const initial = scope !== this.scope || sessionGeneration !== this.sessionGeneration
    if (initial) {
      this.reset()
      this.scope = scope
      this.sessionGeneration = sessionGeneration
      this.saveId = snapshot.id
    }
    if (snapshot.version < this.version) return
    const next = [...audioCues(snapshot), ...operationAudioCues(snapshot)]
    const sceneChanged = this.scene !== snapshot.scene_id
    this.version = snapshot.version
    this.scene = snapshot.scene_id
    this.cues = next
    const keys = new Set(next.map((c) => c.key))
    for (const [key, controller] of this.pending) {
      if (!keys.has(key) || sceneChanged) {
        controller.abort()
        this.pending.delete(key)
      }
    }
    for (const [key, track] of this.tracks) {
      if (!keys.has(key) || sceneChanged) {
        this.tracks.delete(key)
        // Only an ambient transition fades; obsolete speech/effects stop now.
        if (sceneChanged && track.cue.channel === 'ambient' && !this.state.paused)
          this.fade(track, 0, true)
        else this.release(track)
      }
    }
    for (const cue of next) {
      const fresh = !this.seen.has(cue.key)
      this.seen.add(cue.key) // Consume while muted, disabled or hidden as well.
      if (!this.state.enabled || this.state.paused || this.preferences.muted) continue
      if (
        cue.channel === 'ambient' ||
        (!snapshot.from_realtime && !initial && fresh && !cue.operation)
      )
        void this.start(cue)
    }
    this.notify()
  }
  enable() {
    this.failed.clear()
    this.state.enabled = true
    this.state.paused = false
    this.state.message = ''
    this.state.status = 'ready'
    // Invoked only by a user gesture. Historical effects/voices are never replayed.
    for (const cue of this.cues.filter((c) => c.channel === 'ambient')) void this.start(cue)
    this.notify()
  }
  disable(message = '') {
    this.stopAll()
    this.state.enabled = false
    this.state.paused = false
    this.state.status = 'off'
    this.state.message = message
    this.notify()
  }
  background() {
    this.disable('页面进入后台，声音已停止；返回后请主动启用。')
  }
  pause() {
    this.state.paused = true
    this.state.status = 'paused'
    for (const t of this.tracks.values()) t.element.pause()
    for (const t of [...this.retired]) this.release(t)
    // A pending load cannot start after pause.
    for (const c of this.pending.values()) c.abort()
    this.pending.clear()
    this.notify()
  }
  resume() {
    this.failed.clear()
    if (!this.state.enabled) return
    this.state.paused = false
    this.state.message = ''
    this.state.status = 'ready'
    for (const t of this.tracks.values()) void this.play(t)
    for (const c of this.cues.filter((c) => c.channel === 'ambient')) void this.start(c)
    this.notify()
  }
  replay(key: string) {
    const cue = this.cues.find((c) => c.key === key && c.channel === 'voice')
    if (!cue || !this.state.enabled || this.state.paused || this.preferences.muted) return
    this.stopVoice()
    this.failed.delete(cue.key)
    this.state.status = 'ready'
    this.state.message = ''
    void this.start(cue)
  }
  skip() {
    this.stopVoice()
    this.notify()
  }
  private stopVoice(loadingKey?: string) {
    for (const cue of this.cues.filter((c) => c.channel === 'voice')) {
      if (cue.key === loadingKey) continue
      this.pending.get(cue.key)?.abort()
      this.pending.delete(cue.key)
    }
    for (const [key, t] of this.tracks)
      if (t.cue.channel === 'voice') {
        this.tracks.delete(key)
        this.release(t)
      }
    this.state.voiceKey = null
    this.state.time = 0
    this.volumes()
  }
  settings(p: AudioPreferences) {
    const wasMuted = this.preferences.muted
    this.preferences = { muted: p.muted, volumes: { ...p.volumes } }
    this.volumes()
    if (p.muted) {
      // Cancel one-shots/loading; preserve enable preference, never replay backlog.
      this.stopAll()
      this.state.status = this.state.enabled ? 'ready' : 'off'
    } else if (wasMuted && this.state.enabled && !this.state.paused) {
      for (const c of this.cues.filter((c) => c.channel === 'ambient')) void this.start(c)
    }
    this.notify()
  }
  private async start(cue: AudioCue) {
    if (
      this.failed.has(cue.key) ||
      this.tracks.has(cue.key) ||
      this.pending.has(cue.key) ||
      !this.state.enabled ||
      this.state.paused ||
      this.preferences.muted
    )
      return
    const controller = new AbortController(),
      epoch = this.epoch
    this.pending.set(cue.key, controller)
    let resource: Awaited<ReturnType<typeof protectedAudio>> | undefined
    try {
      resource = await this.deps.load(this.saveId, cue.asset_id, controller.signal)
      if (controller.signal.aborted || epoch !== this.epoch) {
        resource.dispose()
        return
      }
      if (cue.channel === 'voice') this.stopVoice(cue.key)
      const element = this.deps.element()
      const track: Track = {
        cue,
        element,
        dispose: resource.dispose,
        gain: cue.channel === 'ambient' ? 0 : 1,
      }
      element.src = resource.url
      element.loop = cue.channel === 'ambient'
      element.preload = 'none'
      element.onended = () => {
        if (this.tracks.get(cue.key) === track) this.tracks.delete(cue.key)
        this.release(track)
        this.notify()
      }
      element.onerror = () => {
        this.failed.add(cue.key)
        this.state.status = 'error'
        this.state.message = '音频无法解码或格式不受支持；字幕与操作仍可使用。'
        this.tracks.delete(cue.key)
        this.release(track)
        this.notify()
      }
      element.ontimeupdate = () => {
        if (this.state.voiceKey === cue.key) {
          this.state.time = element.currentTime
          this.notify()
        }
      }
      this.tracks.set(cue.key, track)
      if (cue.channel === 'voice') {
        this.state.voiceKey = cue.key
        this.state.time = 0
      }
      this.volumes()
      await this.play(track)
      if (this.tracks.get(cue.key) === track && cue.channel === 'ambient') this.fade(track, 1)
    } catch (cause) {
      resource?.dispose()
      if (!controller.signal.aborted && epoch === this.epoch) {
        if (
          cause instanceof ApiError &&
          cause.status === 401 &&
          this.sessionGeneration !== undefined
        )
          this.sessionExpired(this.sessionGeneration)
        this.failed.add(cue.key)
        this.state.status = 'error'
        this.state.message = '音频资源暂不可用或尚未配置；请继续阅读字幕与操作。'
        this.notify()
      }
    } finally {
      if (this.pending.get(cue.key) === controller) this.pending.delete(cue.key)
    }
  }
  private async play(track: Track) {
    try {
      await track.element.play()
      if (this.tracks.get(track.cue.key) !== track) return
      if (!this.state.enabled || this.state.paused) {
        track.element.pause()
        return
      }
      if (this.state.status !== 'blocked' && this.state.status !== 'error')
        this.state.status = 'playing'
    } catch {
      if (this.tracks.get(track.cue.key) !== track) return
      this.failed.add(track.cue.key)
      this.state.status = 'blocked'
      this.state.message = '浏览器拒绝播放，请主动启用声音或继续阅读字幕。'
      this.tracks.delete(track.cue.key)
      this.release(track)
    }
    this.notify()
  }
  private volume(t: Track) {
    const duck = t.cue.channel === 'ambient' && this.state.voiceKey ? 0.35 : 1
    t.element.volume = Math.max(
      0,
      Math.min(1, this.preferences.volumes[t.cue.channel] * t.gain * duck),
    )
    t.element.muted = this.preferences.muted
  }
  private volumes() {
    for (const t of [...this.tracks.values(), ...this.retired]) this.volume(t)
  }
  private fade(t: Track, target: number, release = false) {
    if (t.timer) clearInterval(t.timer)
    if (release) this.retired.add(t)
    const from = t.gain
    let tick = 0
    t.timer = setInterval(() => {
      t.gain = from + (target - from) * (++tick / 10)
      this.volume(t)
      if (tick >= 10) {
        clearInterval(t.timer)
        t.timer = undefined
        if (release) this.release(t)
      }
    }, 40)
  }
  private release(t: Track) {
    if (t.timer) clearInterval(t.timer)
    this.retired.delete(t)
    t.element.onended = t.element.onerror = t.element.ontimeupdate = null
    t.element.pause()
    t.element.removeAttribute('src')
    t.element.load()
    t.dispose()
    if (this.tracks.size === 0 && this.state.status === 'playing')
      this.state.status = this.state.paused ? 'paused' : this.state.enabled ? 'ready' : 'off'
    if (this.state.voiceKey === t.cue.key) {
      this.state.voiceKey = null
      this.state.time = 0
      this.volumes()
    }
  }
  private stopAll() {
    this.epoch++
    for (const c of this.pending.values()) c.abort()
    this.pending.clear()
    for (const t of [...this.tracks.values(), ...this.retired]) this.release(t)
    this.tracks.clear()
    this.retired.clear()
    this.state.voiceKey = null
    this.state.time = 0
  }
  reset() {
    this.disable()
    this.scope = ''
    this.sessionGeneration = undefined
    this.saveId = ''
    this.version = -1
    this.scene = ''
    this.failed.clear()
    this.seen.clear()
    this.cues = []
  }
}
