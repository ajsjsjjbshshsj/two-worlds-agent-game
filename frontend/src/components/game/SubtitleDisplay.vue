<script setup lang="ts">
import type { AudioCue } from '../../types/audio'
defineProps<{
  cues: AudioCue[]
  visible: boolean
  size: number
  voiceKey: string | null
  time: number
}>()
</script>
<template>
  <section
    v-if="visible"
    class="subtitles"
    aria-label="当前授权字幕"
    :style="{ fontSize: size + 'px' }"
  >
    <h2>声音与叙事文字</h2>
    <p v-if="!cues.length">当前场景暂无授权音频或字幕。</p>
    <p role="status" aria-live="polite" aria-atomic="true">
      <template v-for="cue in cues.filter((c) => c.key === voiceKey)" :key="cue.key"
        >正在播放：{{ cue.text }}</template
      >
    </p>
    <p
      v-for="cue in cues"
      :key="cue.key"
      :data-cue="cue.cue_id"
      :data-active="cue.key === voiceKey"
      :lang="cue.language"
    >
      <span
        >{{
          cue.subtitle_type === 'environment'
            ? '环境'
            : cue.subtitle_type === 'effect'
              ? '音效'
              : '旁白'
        }}<template v-if="cue.speaker"> · {{ cue.speaker }}</template
        >：</span
      >{{ cue.text }}
      <small v-if="cue.key === voiceKey">（{{ Math.floor(time) }} 秒）</small>
    </p>
  </section>
</template>
<style scoped>
.subtitles {
  color: #d4e2e8;
  background: #102b46;
  padding: 1rem;
  border-radius: 0.75rem;
  overflow-wrap: anywhere;
}
h2 {
  font-size: 1em;
  color: #e3bd7a;
}
p {
  line-height: 1.7;
}
[data-active='true'] {
  border-left: 3px solid #e3bd7a;
  padding-left: 0.75rem;
}
</style>
