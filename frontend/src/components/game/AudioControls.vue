<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { AudioManager } from '../../services/audio'
import { audioCues } from '../../services/audio-assets'
import { useAudioStore } from '../../stores/audio'
import type { GameSnapshot } from '../../types/game'
import AudioSettings from './AudioSettings.vue'
import SubtitleDisplay from './SubtitleDisplay.vue'
const props = defineProps<{ snapshot: GameSnapshot; sessionGeneration?: number }>()
const emit = defineEmits<{ sessionExpired: [generation: number] }>()
const audio = useAudioStore()
const manager = new AudioManager(
  (state) => Object.assign(audio.state, state),
  undefined,
  (generation) => emit('sessionExpired', generation),
)
const cues = computed(() =>
  props.sessionGeneration !== undefined ? audioCues(props.snapshot) : [],
)
watch(
  () => [props.snapshot, props.sessionGeneration] as const,
  () => {
    if (props.sessionGeneration !== undefined)
      manager.update(props.snapshot, props.sessionGeneration)
    else manager.reset()
  },
  { immediate: true, flush: 'sync' },
)
watch(audio.preferences, (p) => manager.settings(p), { deep: true, immediate: true, flush: 'sync' })
function enable() {
  if (!document.hidden) manager.enable()
}
function visibility() {
  if (document.hidden) manager.background()
}
function pagehide() {
  manager.background()
}
onMounted(() => {
  document.addEventListener('visibilitychange', visibility)
  window.addEventListener('pagehide', pagehide)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', visibility)
  window.removeEventListener('pagehide', pagehide)
  manager.reset()
})
const labels = {
  off: '声音已关闭',
  ready: '声音已启用',
  playing: '正在播放',
  paused: '声音已暂停',
  blocked: '浏览器限制播放',
  error: '音频暂不可用',
}
</script>
<template>
  <section class="audio-panel resource-panel" aria-label="声音与字幕">
    <div class="audio-buttons">
      <button v-if="!audio.state.enabled || audio.state.status === 'blocked'" @click="enable">
        启用声音
      </button>
      <button v-if="audio.state.enabled" @click="manager.disable()">关闭声音</button>
      <button
        v-if="audio.state.enabled"
        @click="audio.state.paused ? manager.resume() : manager.pause()"
      >
        {{ audio.state.paused ? '继续声音' : '暂停声音' }}
      </button>
      <button
        :aria-pressed="audio.preferences.muted"
        @click="audio.preferences.muted = !audio.preferences.muted"
      >
        {{ audio.preferences.muted ? '恢复声音' : '全局静音' }}
      </button>
      <button v-if="audio.state.voiceKey" @click="manager.skip()">跳过旁白</button>
      <button
        v-for="cue in cues.filter((c) => c.channel === 'voice')"
        :key="cue.key"
        :disabled="!audio.state.enabled || audio.state.paused || audio.preferences.muted"
        @click="manager.replay(cue.key)"
      >
        重播当前旁白
      </button>
    </div>
    <p role="status">
      {{ labels[audio.state.status]
      }}<template v-if="audio.state.message"> · {{ audio.state.message }}</template>
    </p>
    <p class="help">
      首次读档不重播历史声音；旁白可主动重播。正式音频尚未发布，缺失资源时可继续阅读授权文字。
    </p>
    <AudioSettings />
    <SubtitleDisplay
      :cues="cues"
      :visible="audio.subtitles.visible"
      :size="audio.subtitles.size"
      :voice-key="audio.state.voiceKey"
      :time="audio.state.time"
    />
  </section>
</template>
<style scoped>
.audio-panel {
  margin-block: 1rem;
  min-width: 0;
}
.audio-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
button {
  background: #142f44;
  color: #e5edf0;
  border: 1px solid #bca477;
  border-radius: 0.5rem;
  min-width: 44px;
  min-height: 44px;
}
</style>
