<script setup lang="ts">
import { watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { retryDelay } from './services/save-recovery'
import { useIdentityStore } from './stores/identity'

const identity = useIdentityStore()
const route = useRoute()
const router = useRouter()

watch(
  () => [
    route.meta.requiresAuth,
    identity.initialized,
    identity.authenticated,
    identity.sessionSuspended,
  ],
  () => {
    if (
      route.meta.requiresAuth &&
      identity.initialized &&
      !identity.authenticated &&
      !identity.sessionSuspended
    )
      void router.replace('/')
  },
)

// The game view is unmounted while identity is suspended. Retry here so a
// transient failure of the existing /me check can still remount it safely.
watch(
  () =>
    [
      route.name,
      route.params.saveId,
      identity.account?.id,
      identity.sessionSuspended,
      identity.verificationUnavailable,
    ] as const,
  ([name, , accountId, suspended, unavailable], _, onCleanup) => {
    if (name !== 'game' || !accountId || !suspended || !unavailable) return
    let attempts = 0
    let timer: number | undefined
    let stopped = false
    const active = () => !stopped && !document.hidden && navigator.onLine
    function schedule() {
      window.clearTimeout(timer)
      if (active()) timer = window.setTimeout(recheck, retryDelay(attempts))
    }
    async function recheck() {
      if (!active()) return
      if (!identity.initializing) {
        attempts++
        await identity.verifySession()
      }
      schedule()
    }
    document.addEventListener('visibilitychange', schedule)
    window.addEventListener('online', schedule)
    window.addEventListener('offline', schedule)
    schedule()
    onCleanup(() => {
      stopped = true
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', schedule)
      window.removeEventListener('online', schedule)
      window.removeEventListener('offline', schedule)
    })
  },
)
</script>

<template>
  <main v-if="route.meta.requiresAuth && !identity.authenticated" class="space-content">
    <section class="resource-panel" aria-label="会话验证">
      <p v-if="identity.verificationUnavailable && !identity.initializing" role="alert">
        暂时无法验证身份，请检查连接后重试。
      </p>
      <p v-else role="status">正在确认当前账号，私人内容暂时隐藏。</p>
      <button
        v-if="identity.verificationUnavailable && !identity.initializing"
        class="small-action"
        type="button"
        @click="identity.verifySession()"
      >
        重试验证
      </button>
    </section>
  </main>
  <RouterView v-else v-slot="{ Component }">
    <component
      :is="Component"
      :key="route.meta.requiresAuth ? identity.sessionGeneration : undefined"
    />
  </RouterView>
</template>
