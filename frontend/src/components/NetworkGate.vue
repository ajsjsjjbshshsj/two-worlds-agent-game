<script setup lang="ts">
import { ref, provide, onMounted, onBeforeUnmount } from 'vue'
defineProps<{ localControls?: boolean }>()
const offline = ref(navigator.onLine === false)
provide('twoworlds-offline', offline)
const update = () => {
  offline.value = navigator.onLine === false
}
onMounted(() => {
  window.addEventListener('online', update)
  window.addEventListener('offline', update)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', update)
  window.removeEventListener('offline', update)
})
</script>
<template>
  <p v-if="offline" class="network-notice" role="status">
    当前离线，游戏与账号操作已暂停。联网后会重新核对会话和服务器进度，离线期间不会推进存档。
  </p>
  <fieldset class="network-gate" :disabled="offline && !localControls" aria-label="在线应用操作">
    <slot />
  </fieldset>
</template>
<style scoped>
.network-gate {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.network-notice {
  padding: 16px;
  margin: 0 auto;
  max-width: 1144px;
  color: var(--gold);
}
</style>
