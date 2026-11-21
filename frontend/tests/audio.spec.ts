import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { AudioManager } from '../src/services/audio'
import { audioCues } from '../src/services/audio-assets'
import { protectedAudio } from '../src/services/media'
import { parseGame } from '../src/types/game'
import type { AudioState } from '../src/types/audio'
import { game } from './game-fixture'
const asset = (id: string, kind: 'ambience' | 'sfx' | 'narration') => ({
  id,
  alt_text: 'TEST-ONLY ' + id,
  assets: [
    {
      asset_id: id,
      kind,
      alt_text: 'TEST-ONLY ' + id,
      transcript: kind === 'narration' ? 'TEST-ONLY 本人旁白' : null,
    },
  ],
})
export function soundSnapshot(
  version = 1,
  kinds: ('ambience' | 'sfx' | 'narration')[] = ['ambience'],
) {
  return parseGame({
    ...game(),
    version,
    presentation: { background: null, cues: kinds.map((k) => asset(k, k)) },
  })
}
class Sound {
  src = ''
  loop = false
  volume = 1
  muted = false
  currentTime = 0
  preload = ''
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  ontimeupdate: (() => void) | null = null
  play = vi.fn(async () => {})
  pause = vi.fn()
  load = vi.fn()
  removeAttribute = vi.fn()
}
let manager: AudioManager,
  elements: Sound[],
  dispose: ReturnType<typeof vi.fn<() => void>>,
  load: ReturnType<typeof vi.fn<typeof protectedAudio>>,
  states: AudioState[]
beforeEach(() => {
  vi.useFakeTimers()
  elements = []
  dispose = vi.fn()
  states = []
  load = vi.fn(async () => ({ url: 'blob:test', dispose }))
  manager = new AudioManager((s) => states.push(s), {
    element: () => {
      const e = new Sound()
      elements.push(e)
      return e as unknown as HTMLAudioElement
    },
    load,
  })
})
afterEach(() => {
  manager.reset()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('does not fetch or autoplay on first load, enabling starts looping ambience only', async () => {
  manager.update(soundSnapshot(1, ['ambience', 'sfx', 'narration']), 1)
  expect(load).not.toHaveBeenCalled()
  manager.enable()
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(1)
  expect(elements[0]?.loop).toBe(true)
  expect(elements[0]?.play).toHaveBeenCalledTimes(1)
})
it('new confirmed cues play once; same-version reads, retries and newer identical snapshots do not replay', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  manager.update(soundSnapshot(2, ['ambience', 'sfx']), 1)
  await flushPromises()
  expect(elements[1]?.loop).toBe(false)
  elements[1]?.onended?.()
  manager.update(soundSnapshot(2, ['ambience', 'sfx']), 1)
  manager.update(soundSnapshot(3, ['ambience', 'sfx']), 1)
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(2)
})
it('updates audio authorization from a socket without playing unconfirmed one-shots', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  const pushed = soundSnapshot(2, ['ambience', 'sfx', 'narration'])
  manager.update({ ...pushed, from_realtime: true }, 1)
  await flushPromises()
  expect(load.mock.calls.map(([, asset]) => asset)).toEqual(['ambience'])

  manager.update(pushed, 1)
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(1)
  manager.replay('narration:narration')
  await flushPromises()
  expect(load.mock.calls.map(([, asset]) => asset)).toEqual(['ambience', 'narration'])
})
it('restores HTTP media authorization without replaying recovered one-shots', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  const recovered = soundSnapshot(2, ['ambience', 'sfx', 'narration'])
  manager.update({ ...recovered, restored: true }, 1)
  manager.update(recovered, 1)
  await flushPromises()
  expect(load.mock.calls.map(([, asset]) => asset)).toEqual(['ambience'])
  manager.replay('narration:narration')
  await flushPromises()
  expect(load.mock.calls.map(([, asset]) => asset)).toEqual(['ambience', 'narration'])
})
it('reconstructed page baselines current effects rather than replaying history', async () => {
  manager.update(soundSnapshot(8, ['sfx']), 1)
  manager.enable()
  await flushPromises()
  expect(load).not.toHaveBeenCalled()
})
it('rejects late lower versions without disclosing their cues', async () => {
  manager.update(soundSnapshot(8), 1)
  manager.enable()
  await flushPromises()
  manager.update(soundSnapshot(7, ['sfx']), 1)
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(1)
})
it('voice playback pauses/resumes, tracks time, skips and explicitly replays authorized narration', async () => {
  manager.update(soundSnapshot(1, ['narration']), 1)
  manager.enable()
  manager.replay('narration:narration')
  await flushPromises()
  const e = elements[0]!
  manager.pause()
  expect(e.pause).toHaveBeenCalled()
  manager.resume()
  await flushPromises()
  expect(e.play).toHaveBeenCalledTimes(2)
  e.currentTime = 2
  e.ontimeupdate?.()
  expect(manager.state.time).toBe(2)
  manager.skip()
  expect(dispose).toHaveBeenCalledTimes(1)
  manager.replay('narration:narration')
  await flushPromises()
  expect(elements).toHaveLength(2)
  manager.replay('other:secret')
  await flushPromises()
  expect(elements).toHaveLength(2)
})
it('independent channel levels and voice ducking preserve other channels', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  vi.advanceTimersByTime(400)
  manager.update(soundSnapshot(2, ['ambience', 'sfx', 'narration']), 1)
  await flushPromises()
  manager.settings({ volumes: { ambient: 0.8, sfx: 0.2, voice: 0.6 }, muted: false })
  expect(elements[0]?.volume).toBeCloseTo(0.8 * 0.35)
  expect(elements[1]?.volume).toBe(0.2)
  expect(elements[2]?.volume).toBe(0.6)
  manager.skip()
  expect(elements[0]?.volume).toBe(0.8)
})
it('global mute cancels tracks, consumes new effects and restores only ambience', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  manager.settings({ volumes: { ambient: 0.5, sfx: 0.5, voice: 1 }, muted: true })
  manager.update(soundSnapshot(2, ['ambience', 'sfx']), 1)
  await flushPromises()
  expect(dispose).toHaveBeenCalledTimes(1)
  expect(load).toHaveBeenCalledTimes(1)
  manager.settings({ volumes: { ambient: 0.5, sfx: 0.5, voice: 1 }, muted: false })
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(2)
})
it('crossfades old ambient and releases it after scene change', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  vi.advanceTimersByTime(200)
  expect(elements[0]?.volume).toBeCloseTo(0.25)
  vi.advanceTimersByTime(200)
  const s = soundSnapshot(2)
  const repair = { ...s, scene_id: 'repair' }
  s.presentation.cues[0]!.id = 'repair_ambient'
  manager.update(repair, 1)
  await flushPromises()
  expect(elements).toHaveLength(2)
  vi.advanceTimersByTime(200)
  expect(elements[0]?.volume).toBeCloseTo(0.25)
  vi.advanceTimersByTime(200)
  expect(dispose).toHaveBeenCalledTimes(1)
  expect(elements[1]?.volume).toBeCloseTo(0.5)
})
it.each(['session', 'save', 'role'])(
  'changing %s stops and releases old private audio and requires a new gesture',
  async (change) => {
    manager.update(soundSnapshot(), 1)
    manager.enable()
    await flushPromises()
    const next = {
      ...soundSnapshot(2),
      ...(change === 'save' ? { id: 'save_other' } : {}),
      ...(change === 'role' ? { role: 'b' as const } : {}),
    }
    manager.update(next, change === 'session' ? 2 : 1)
    expect(dispose).toHaveBeenCalledTimes(1)
    expect(manager.state.enabled).toBe(false)
  },
)
it('reset aborts in-flight loads and disposes late resources even if fetch ignores abort', async () => {
  let resolve!: (v: { url: string; dispose: () => void }) => void
  load.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  manager.update(soundSnapshot(), 1)
  manager.enable()
  manager.reset()
  expect(load.mock.calls[0]![2].aborted).toBe(true)
  resolve({ url: 'blob:late', dispose })
  await flushPromises()
  expect(dispose).toHaveBeenCalledTimes(1)
  expect(elements).toHaveLength(0)
})
it('background/disabling cancels sound, ignores new cues, and never resumes automatically', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  manager.background()
  expect(manager.state.enabled).toBe(false)
  manager.update(soundSnapshot(2, ['ambience', 'sfx']), 1)
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(1)
  manager.enable()
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(2)
  manager.disable()
  manager.update(soundSnapshot(3), 1)
  expect(manager.state.enabled).toBe(false)
})
it('autoplay rejection is caught without retries, and an explicit gesture can retry', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  manager.disable()
  load.mockImplementation(async () => ({ url: 'blob:again', dispose }))
  const blocked = new AudioManager(() => {}, {
    load,
    element: () => {
      const e = new Sound()
      e.play.mockRejectedValue(new DOMException('policy', 'NotAllowedError'))
      elements.push(e)
      return e as unknown as HTMLAudioElement
    },
  })
  blocked.update(soundSnapshot(), 1)
  blocked.enable()
  await flushPromises()
  expect(blocked.state.status).toBe('blocked')
  expect(elements.at(-1)?.play).toHaveBeenCalledTimes(1)
  const attempts = load.mock.calls.length
  blocked.update(soundSnapshot(2), 1)
  await flushPromises()
  // An ordinary read must not retry a blocked ambient load.
  expect(blocked.state.message).toContain('浏览器拒绝')
  expect(load).toHaveBeenCalledTimes(attempts)
  blocked.reset()
})
it('resource failure is reported without losing authorized subtitle text', async () => {
  load.mockRejectedValue(new Error('unavailable'))
  const s = soundSnapshot()
  manager.update(s, 1)
  manager.enable()
  await flushPromises()
  expect(manager.state.status).toBe('error')
  expect(audioCues(s)[0]?.text).toContain('TEST-ONLY')
})
it('media decode error is handled and releases URL', async () => {
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  elements[0]?.onerror?.()
  expect(manager.state.status).toBe('error')
  expect(dispose).toHaveBeenCalledTimes(1)
})
it('current server cues alone determine subtitles, not hidden script or devices', () => {
  const s = soundSnapshot(1, ['narration'])
  expect(audioCues(s)[0]).toMatchObject({
    cue_id: 'narration',
    speaker: null,
    start_time: 0,
    duration: null,
    language: 'zh-CN',
    subtitle_type: 'narration',
    text: 'TEST-ONLY 本人旁白',
  })
  s.presentation.cues = []
  expect(audioCues(s)).toEqual([])
})
it.each(['audio/wav', 'audio/mpeg', 'audio/ogg', 'audio/mp4'])(
  'protected %s uses Cookies, no-store, bounded Blob and explicit disposal',
  async (type) => {
    const create = vi.fn((_blob: Blob) => 'blob:AUDIO'),
      revoke = vi.fn()
    vi.stubGlobal(
      'URL',
      class extends URL {
        static createObjectURL = create
        static revokeObjectURL = revoke
      },
    )
    const fetcher = vi.fn(async () => new Response('audio', { headers: { 'Content-Type': type } }))
    vi.stubGlobal('fetch', fetcher)
    const r = await protectedAudio('save_one', 'audio_one', new AbortController().signal)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/saves/save_one/media/audio_one',
      expect.objectContaining({
        cache: 'no-store',
        credentials: 'include',
        redirect: 'error',
      }),
    )
    expect(create.mock.calls[0]![0].type).toBe(type)
    r.dispose()
    expect(revoke).toHaveBeenCalledWith('blob:AUDIO')
  },
)
it.each(['image/png', 'text/html', 'application/octet-stream'])(
  'rejects non-audio MIME %s',
  async (type) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('data', { headers: { 'Content-Type': type } })),
    )
    await expect(
      protectedAudio('save_one', 'audio_one', new AbortController().signal),
    ).rejects.toThrow()
  },
)
it('aborted and oversized audio is rejected before object URL creation', async () => {
  const create = vi.fn()
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = create
    },
  )
  const controller = new AbortController()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(new Uint8Array(32 * 1024 * 1024 + 1), {
          headers: { 'Content-Type': 'audio/wav' },
        }),
    ),
  )
  await expect(protectedAudio('save_one', 'audio_one', controller.signal)).rejects.toThrow()
  controller.abort()
  await expect(protectedAudio('save_one', 'audio_one', controller.signal)).rejects.toThrow()
  expect(create).not.toHaveBeenCalled()
})
it('paused in-flight fetch never starts later, and new paused effects are not backlogged', async () => {
  let resolve!: (v: { url: string; dispose: () => void }) => void
  load.mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  manager.update(soundSnapshot(), 1)
  manager.enable()
  manager.pause()
  resolve({ url: 'blob:PAUSED', dispose })
  await flushPromises()
  expect(elements).toHaveLength(0)
  expect(dispose).toHaveBeenCalledTimes(1)
  manager.update(soundSnapshot(2, ['ambience', 'sfx']), 1)
  manager.resume()
  await flushPromises()
  expect(elements).toHaveLength(1)
  expect(elements[0]?.loop).toBe(true)
})
it('loading failure is not retried by repeated or newer snapshots', async () => {
  load.mockRejectedValue(Error('unavailable'))
  manager.update(soundSnapshot(), 1)
  manager.enable()
  await flushPromises()
  manager.update(soundSnapshot(2), 1)
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(1)
  manager.enable()
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(2)
})
