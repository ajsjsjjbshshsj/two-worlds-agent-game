import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AudioControls from '../src/components/game/AudioControls.vue'
import SubtitleDisplay from '../src/components/game/SubtitleDisplay.vue'
import ActionPanel from '../src/components/game/ActionPanel.vue'
import { audioCues } from '../src/services/audio-assets'
import { useAudioStore } from '../src/stores/audio'
import { useGameStore } from '../src/stores/game'
import { useIdentityStore } from '../src/stores/identity'
import { parseGame } from '../src/types/game'
import { game } from './game-fixture'
import { json, me } from './fixtures'
const snapshots = (version = 1, extra = false) =>
  parseGame({
    ...game(),
    version,
    presentation: {
      background: null,
      cues: [
        {
          id: 'wind',
          alt_text: 'TEST-ONLY 风声',
          assets: [
            { asset_id: 'wind', kind: 'ambience', alt_text: 'TEST-ONLY 风声', transcript: null },
          ],
        },
        {
          id: 'own_voice',
          alt_text: 'TEST-ONLY 旁白',
          assets: [
            {
              asset_id: 'own_voice',
              kind: 'narration',
              alt_text: 'TEST-ONLY 旁白',
              transcript: 'TEST-ONLY 本人故事',
            },
          ],
        },
        ...(extra
          ? [
              {
                id: 'new_effect',
                alt_text: 'TEST-ONLY 装置确认',
                assets: [
                  {
                    asset_id: 'new_effect',
                    kind: 'sfx',
                    alt_text: 'TEST-ONLY 装置确认',
                    transcript: null,
                  },
                ],
              },
            ]
          : []),
      ],
    },
  })
let wrappers: { unmount: () => void }[]
let play: ReturnType<typeof vi.fn>
beforeEach(() => {
  setActivePinia(createPinia())
  wrappers = []
  sessionStorage.clear()
  localStorage.clear()
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  play = vi.fn(async () => {})
  vi.stubGlobal(
    'Audio',
    class {
      src = ''
      loop = false
      volume = 1
      muted = false
      currentTime = 0
      play = play
      pause = vi.fn()
      load = vi.fn()
      removeAttribute = vi.fn()
    },
  )
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = vi.fn(() => 'blob:TEST')
      static revokeObjectURL = vi.fn()
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('TEST-ONLY', { headers: { 'Content-Type': 'audio/wav' } })),
  )
})
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  vi.unstubAllGlobals()
})
function panel() {
  const w = mount(AudioControls, { props: { snapshot: snapshots(), token: 'TEST' } })
  wrappers.push(w)
  return w
}
async function button(w: ReturnType<typeof panel>, text: string) {
  await w
    .findAll('button')
    .find((b) => b.text() === text)!
    .trigger('click')
  await flushPromises()
}
it('shows authorized transcript without enabling sound; accessible subtitles persist on playback failure', async () => {
  const w = panel()
  expect(w.text()).toContain('TEST-ONLY 本人故事')
  expect(play).not.toHaveBeenCalled()
  expect(w.find('[aria-live="polite"]').exists()).toBe(true)
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(Error('offline')))
  await button(w, '启用声音')
  expect(w.text()).toContain('音频资源暂不可用')
  expect(w.text()).toContain('TEST-ONLY 本人故事')
})
it('enables on a click, changes independent settings, pauses, resumes, mutes and disables', async () => {
  const w = panel()
  await button(w, '启用声音')
  expect(play).toHaveBeenCalledTimes(1)
  const sliders = w.findAll('input[type="range"]')
  await sliders[0]!.setValue('0.2')
  await sliders[1]!.setValue('0.8')
  expect(useAudioStore().preferences.volumes).toMatchObject({ ambient: 0.2, sfx: 0.8, voice: 1 })
  await button(w, '暂停声音')
  expect(useAudioStore().state.paused).toBe(true)
  await button(w, '继续声音')
  expect(useAudioStore().state.paused).toBe(false)
  await button(w, '全局静音')
  expect(useAudioStore().preferences.muted).toBe(true)
  await button(w, '恢复声音')
  expect(useAudioStore().preferences.muted).toBe(false)
  await button(w, '关闭声音')
  expect(useAudioStore().state.enabled).toBe(false)
})
it('subtitle visibility and font size work independently of sound', async () => {
  const w = panel()
  await w.findAll('input[type="range"]')[3]!.setValue('24')
  expect(w.find('.subtitles').attributes('style')).toContain('24px')
  await w.find('input[type="checkbox"]').setValue(false)
  expect(w.find('.subtitles').exists()).toBe(false)
  await w.find('input[type="checkbox"]').setValue(true)
  expect(w.text()).toContain('TEST-ONLY 本人故事')
})
it('background stops all audio; visibility restoration never restarts it', async () => {
  const w = panel()
  await button(w, '启用声音')
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  document.dispatchEvent(new Event('visibilitychange'))
  expect(useAudioStore().state.enabled).toBe(false)
  expect(URL.revokeObjectURL).toHaveBeenCalled()
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  document.dispatchEvent(new Event('visibilitychange'))
  await flushPromises()
  expect(play).toHaveBeenCalledTimes(1)
})
it.each(['unmount', 'logout', 'save'])('%s releases current media', async (change) => {
  const w = panel()
  await button(w, '启用声音')
  if (change === 'unmount') {
    w.unmount()
    wrappers = []
  }
  if (change === 'logout') await w.setProps({ token: '' })
  if (change === 'save') await w.setProps({ snapshot: { ...snapshots(), id: 'other_save' } })
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:TEST')
  expect(useAudioStore().state.enabled).toBe(false)
})
it('switching role replaces subtitle text rather than retaining private narration', async () => {
  const w = panel(),
    next = { ...snapshots(), role: 'b' as const }
  next.presentation.cues[1]!.assets[0]!.transcript = 'TEST-ONLY B 独立故事'
  await w.setProps({ snapshot: next })
  expect(w.text()).toContain('B 独立故事')
  expect(w.text()).not.toContain('本人故事')
})
it('plain transcripts remain readable after skipping, narration highlights follow playback', async () => {
  const w = panel()
  await button(w, '启用声音')
  await button(w, '重播当前旁白')
  expect(w.find('[data-active="true"]').text()).toContain('本人故事')
  await button(w, '跳过旁白')
  expect(w.find('[data-active="true"]').exists()).toBe(false)
  expect(w.text()).toContain('本人故事')
})
it('SubtitleDisplay renders authored speaker and Chinese text with audio association', () => {
  const cues = audioCues(snapshots())
  cues[1]!.speaker = '测试旁白'
  const w = mount(SubtitleDisplay, {
    props: { cues, visible: true, size: 20, voiceKey: 'own_voice:own_voice', time: 2.5 },
  })
  wrappers.push(w)
  expect(w.find('[lang="zh-CN"][data-active="true"]').text()).toContain('测试旁白')
  expect(w.text()).toContain('2 秒')
})
it('audio failure does not disable independent device controls', async () => {
  const w = panel()
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(Error('offline')))
  await button(w, '启用声音')
  const actions = mount(ActionPanel, {
    props: { actions: snapshots().available_actions, disabled: false },
  })
  wrappers.push(actions)
  expect(actions.find('button').attributes('disabled')).toBeUndefined()
})
it('only confirmed game-store response adds an audio cue; unknown/failed commands leave prior cues', async () => {
  const identity = useIdentityStore()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(me)))
  identity.token = 'TEST'
  identity.account = me.account
  identity.initialized = true
  const store = useGameStore()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(snapshots())))
  await store.load('save_one')
  const w = mount(AudioControls, { props: { snapshot: store.snapshot!, token: 'TEST' } })
  wrappers.push(w)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url, options) =>
      options?.method === 'POST'
        ? Promise.reject(Error('unknown'))
        : new Response('sound', { headers: { 'Content-Type': 'audio/wav' } }),
    ),
  )
  await button(w, '启用声音')
  const before = play.mock.calls.length
  await store.submit('adjust', { angle: 90, pattern: 'pulse' })
  await w.setProps({ snapshot: store.snapshot! })
  await flushPromises()
  expect(play).toHaveBeenCalledTimes(before)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url, options) =>
      options?.method === 'POST'
        ? json({
            receipt: {
              request_id: JSON.parse(options.body).request_id,
              status: 'accepted',
              accepted_version: 2,
              duplicate: false,
            },
            save: snapshots(2, true),
          })
        : new Response('sound', { headers: { 'Content-Type': 'audio/wav' } }),
    ),
  )
  await store.retry()
  await w.setProps({ snapshot: store.snapshot! })
  await flushPromises()
  expect(play).toHaveBeenCalledTimes(before + 1)
})
