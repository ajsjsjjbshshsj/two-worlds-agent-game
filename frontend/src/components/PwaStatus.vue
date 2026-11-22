<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { registerPwa, type InstallPrompt } from '../services/pwa'
const invitation = ref<InstallPrompt | null>(null)
const waiting = ref(false),
  failed = ref(false),
  installing = ref(false)
function offer(event: Event) {
  event.preventDefault()
  invitation.value = event as InstallPrompt
}
function installed() {
  invitation.value = null
}
async function install() {
  const event = invitation.value
  if (!event || installing.value) return
  invitation.value = null
  installing.value = true
  try {
    await event.prompt()
    await event.userChoice
  } catch {
    failed.value = true
  } finally {
    installing.value = false
  }
}
onMounted(() => {
  window.addEventListener('beforeinstallprompt', offer)
  window.addEventListener('appinstalled', installed)
  void registerPwa(() => {
    waiting.value = true
  }).catch(() => {
    failed.value = true
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeinstallprompt', offer)
  window.removeEventListener('appinstalled', installed)
})
</script>
<template>
  <aside class="pwa-status" aria-label="应用安装与更新">
    <button v-if="invitation" type="button" :disabled="installing" @click="install">
      安装 TwoWorlds
    </button>
    <p v-if="waiting" role="status">
      新版本已准备好。请先确认当前操作结果，再关闭所有 TwoWorlds
      窗口并重新打开。不会强制刷新当前游戏。
    </p>
    <p v-if="failed" role="status">
      安装或离线准备暂不可用，仍可联网使用网页。可稍后重新打开再试。
    </p>
    <details>
      <summary>安装与离线说明</summary>
      <p>
        支持的 Chrome / Edge 可通过浏览器菜单安装；iPhone / iPad 请在 Safari
        分享菜单选择“添加到主屏幕”。安装入口由浏览器支持情况决定。
      </p>
      <p>安装后仍需联网登录和游玩。离线页面只显示公共说明，不缓存私人存档、线索、图片或声音。</p>
    </details>
  </aside>
</template>
<style scoped>
.pwa-status {
  max-width: 1144px;
  margin: 0 auto;
  padding: 16px max(20px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom))
    max(20px, env(safe-area-inset-left));
  color: var(--muted);
  overflow-wrap: anywhere;
}
summary {
  min-height: 44px;
  cursor: pointer;
}
button {
  color: #eef3f5;
  background: #11283a;
}
</style>
