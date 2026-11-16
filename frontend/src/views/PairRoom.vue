<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import SpaceShell from '../components/SpaceShell.vue'
import InvitePanel from '../components/InvitePanel.vue'
import { usePairsStore } from '../stores/pairs'
const pairs = usePairsStore(),
  route = useRoute()
const pair = computed(() => pairs.pairs.find((p) => p.id === route.params.pairId))
watch(
  () => route.params.pairId,
  () => {
    void pairs.load()
  },
  { immediate: true },
)
</script>
<template>
  <SpaceShell>
    <RouterLink class="back-link" to="/pairs">← 我的房间</RouterLink>
    <div class="page-heading">
      <div>
        <p class="eyebrow">两个席位，一段共同旅程</p>
        <h1>双人空间</h1>
      </div>
      <button class="small-action" :disabled="pairs.loading || pairs.busy" @click="pairs.load">
        刷新成员状态
      </button>
    </div>
    <p v-if="pairs.error" class="error" role="alert">{{ pairs.error.message }}</p>
    <p v-if="pairs.notice" class="notice" role="status">{{ pairs.notice }}</p>
    <p v-if="pairs.loading" role="status">正在读取房间…</p>
    <template v-else-if="pair"
      ><div class="room-actions">
        <section class="resource-panel">
          <p class="identifier">{{ pair.id }}</p>
          <h2>{{ pair.member_count === 1 ? '等待搭档加入' : '双方已就位' }}</h2>
          <div class="seat-mark" aria-hidden="true">
            <span>A</span><span :class="{ occupied: pair.member_count === 2 }">B</span>
          </div>
          <p>你的角色 {{ pair.role.toUpperCase() }} · {{ pair.member_count }} / 2 人已加入</p>
          <p class="help">成员状态来自最近一次读取，不代表在线。搭档加入后，请手动刷新。</p>
          <RouterLink class="action-link" :to="'/pairs/' + pair.id + '/library'"
            >进入剧本书架 →</RouterLink
          >
        </section>
        <InvitePanel v-if="pair.role === 'a' && pair.member_count === 1" :pair-id="pair.id" />
        <section v-else class="resource-panel">
          <h2>为你们保留的位置</h2>
          <p>角色由房间成员关系确定，不能在此互换。每个故事的进度都独立保存在这个房间。</p>
        </section>
      </div></template
    >
    <p v-else-if="!pairs.error" class="empty-state" role="status">
      房间不存在或你无权访问。请返回自己的房间列表。
    </p>
  </SpaceShell>
</template>
