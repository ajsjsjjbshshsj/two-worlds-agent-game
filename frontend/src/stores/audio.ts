import { defineStore } from 'pinia'
import { reactive } from 'vue'
import type { AudioChannel, AudioState } from '../types/audio'
export const useAudioStore = defineStore('audio', () => {
  // Session-only preferences contain no identity, assets, transcripts or tokens.
  const preferences = reactive({ volumes: { ambient: 0.5, sfx: 0.7, voice: 1 }, muted: false })
  const subtitles = reactive({ visible: true, size: 18 })
  const state = reactive<AudioState>({
    enabled: false,
    paused: false,
    status: 'off',
    message: '',
    voiceKey: null,
    time: 0,
  })
  function volume(channel: AudioChannel, value: number) {
    if (Number.isFinite(value)) preferences.volumes[channel] = Math.max(0, Math.min(1, value))
  }
  function fontSize(value: number) {
    if (Number.isFinite(value)) subtitles.size = Math.max(16, Math.min(28, value))
  }
  return { preferences, subtitles, state, volume, fontSize }
})
