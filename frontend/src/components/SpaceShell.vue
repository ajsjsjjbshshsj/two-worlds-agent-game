<script setup lang="ts">
import { watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useIdentityStore } from '../stores/identity'
const identity = useIdentityStore(),
  router = useRouter()
watch(
  () => identity.authenticated,
  (value) => {
    if (!value) void router.replace('/')
  },
)
</script>
<template>
  <div class="space-shell">
    <header class="space-header">
      <RouterLink class="brand" to="/pairs"
        ><span class="brand-symbol" aria-hidden="true">↔</span
        ><span>TwoWorlds<small>两个人 · 两个世界</small></span></RouterLink
      >
      <nav aria-label="主要导航">
        <RouterLink to="/pairs">我的房间</RouterLink><RouterLink to="/">身份与恢复</RouterLink>
      </nav>
      <p class="help">{{ identity.account?.display_name }}</p>
    </header>
    <main v-if="identity.authenticated" class="space-content"><slot /></main>
    <footer class="site-foot">
      <span>TwoWorlds · 留一束光，给另一个世界。</span
      ><span>人数表示加入关系，非实时在线状态。</span>
    </footer>
  </div>
</template>
