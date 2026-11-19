import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { AudioManager } from '../src/services/audio'
import { parseGame } from '../src/types/game'
import { gameApi } from '../src/services/game'
import { game } from './game-fixture'
import { json } from './fixtures'
function snapshot(version: number) {
  return parseGame({
    ...game(),
    version,
    presentation: {
      background: null,
      operation_sfx: ['emitter_click'],
      cues: [
        {
          id: 'emitter',
          alt_text: 'TEST-ONLY',
          assets: [
            {
              asset_id: 'emitter_click',
              kind: 'sfx',
              alt_text: 'TEST-ONLY rotation',
              transcript: null,
            },
          ],
        },
      ],
    },
  })
}
const event = (version: number) => ({
  accepted_version: version,
  cue_id: 'emitter',
  asset_id: 'emitter_click',
})
let manager: AudioManager | undefined
afterEach(() => {
  manager?.reset()
  vi.unstubAllGlobals()
})
function setup() {
  const played = vi.fn(async () => {}),
    disposed = vi.fn()
  manager = new AudioManager(() => {}, {
    load: vi.fn(async () => ({ url: 'blob:test', dispose: disposed })),
    element: () =>
      ({
        play: played,
        pause: vi.fn(),
        load: vi.fn(),
        removeAttribute: vi.fn(),
      }) as unknown as HTMLAudioElement,
  })
  return { audio: manager, played, disposed }
}
it('inspect only authorizes media; consecutive confirmed device changes play and retries do not', async () => {
  const { audio, played } = setup()
  const initial = snapshot(0)
  initial.presentation.cues = []
  audio.update(initial, 1)
  audio.enable()
  audio.update(snapshot(1), 1)
  await flushPromises()
  expect(played).not.toHaveBeenCalled()
  const first = { ...snapshot(2), audio_events: [event(2)] }
  audio.update(first, 1)
  await flushPromises()
  expect(played).toHaveBeenCalledTimes(1)
  audio.update(first, 1)
  await flushPromises()
  expect(played).toHaveBeenCalledTimes(1)
  audio.update({ ...snapshot(3), audio_events: [event(3)] }, 1)
  await flushPromises()
  expect(played).toHaveBeenCalledTimes(2)
  audio.update(snapshot(4), 1)
  await flushPromises()
  expect(played).toHaveBeenCalledTimes(2)
})
it('initial restoration consumes any historical events without playing', async () => {
  const { audio, played } = setup()
  audio.update({ ...snapshot(8), audio_events: [event(8)] }, 1)
  audio.enable()
  await flushPromises()
  expect(played).not.toHaveBeenCalled()
})
it('disabled operation events are consumed without delayed playback', async () => {
  const { audio, played } = setup()
  audio.update(snapshot(1), 1)
  audio.update({ ...snapshot(2), audio_events: [event(2)] }, 1)
  audio.enable()
  audio.update({ ...snapshot(2), audio_events: [event(2)] }, 1)
  await flushPromises()
  expect(played).not.toHaveBeenCalled()
})
it('read response cannot smuggle historical command events', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(json({ ...snapshot(2), audio_events: [event(2)] })),
  )
  expect(await gameApi.read('save_one')).not.toHaveProperty('audio_events')
})
it.each(['outside-cue', 'unauthorized-asset', 'wrong-version', 'duplicate', 'repeated-event'])(
  'rejects %s operation metadata before updating game state',
  async (invalid) => {
    const e = event(2),
      save = snapshot(2)
    if (invalid === 'outside-cue') e.cue_id = 'private_cue'
    if (invalid === 'unauthorized-asset') save.presentation.operation_sfx = []
    if (invalid === 'wrong-version') e.accepted_version = 1
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        json({
          save,
          receipt: {
            request_id: 'TEST',
            accepted_version: 2,
            status: 'accepted',
            duplicate: invalid === 'duplicate',
          },
          audio_events: invalid === 'repeated-event' ? [e, e] : [e],
        }),
      ),
    )
    await expect(
      gameApi.submit('save_one', {
        request_id: 'TEST',
        expected_version: 1,
        kind: 'set_emitter',
        args: { angle: 90 },
      }),
    ).rejects.toThrow()
  },
)
it('successful envelope retains authorized events while an idempotent retry has none', async () => {
  const envelope = {
    save: snapshot(2),
    receipt: { request_id: 'TEST', accepted_version: 2, status: 'accepted', duplicate: false },
    audio_events: [event(2)],
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(envelope)))
  const command = {
    request_id: 'TEST',
    expected_version: 1,
    kind: 'set_emitter',
    args: { angle: 90 },
  }
  expect((await gameApi.submit('save_one', command)).audio_events).toEqual([event(2)])
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        json({ ...envelope, receipt: { ...envelope.receipt, duplicate: true }, audio_events: [] }),
      ),
  )
  expect((await gameApi.submit('save_one', command)).audio_events ?? []).toEqual([])
})
it('rejected requests cannot produce a success event', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        json({ error: { code: 'ROLE_FORBIDDEN', message: '拒绝', retryable: false } }, 422),
      ),
  )
  await expect(
    gameApi.submit('save_one', {
      request_id: 'TEST',
      expected_version: 1,
      kind: 'set_emitter',
      args: {},
    }),
  ).rejects.toThrow()
})
