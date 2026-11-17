<script setup lang="ts">
import { useAudioStore } from '../../stores/audio'
import type { AudioChannel } from '../../types/audio'
const audio = useAudioStore()
const channels: { id: AudioChannel; label: string }[] = [
  { id: 'ambient', label: '环境音' },
  { id: 'sfx', label: '设备音效' },
  { id: 'voice', label: '旁白' },
]
</script>
<template>
  <details>
    <summary>声音与字幕设置</summary>
    <label v-for="channel in channels" :key="channel.id"
      >{{ channel.label }}音量
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        :value="audio.preferences.volumes[channel.id]"
        @input="audio.volume(channel.id, Number(($event.target as HTMLInputElement).value))"
      />
    </label>
    <label><input v-model="audio.subtitles.visible" type="checkbox" />显示字幕</label>
    <label
      >字幕字号<input
        type="range"
        min="16"
        max="28"
        step="2"
        :value="audio.subtitles.size"
        @input="audio.fontSize(Number(($event.target as HTMLInputElement).value))"
    /></label>
  </details>
</template>
<style scoped>
summary,
label {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 44px;
  flex-wrap: wrap;
}
input {
  min-height: 44px;
  max-width: 100%;
}
summary {
  cursor: pointer;
}
</style>
