<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import SpaceShell from '../components/SpaceShell.vue'
import { usePairsStore } from '../stores/pairs'
import { useIdentityStore } from '../stores/identity'
const pairs = usePairsStore(),
  identity = useIdentityStore(),
  router = useRouter()
onMounted(() => {
  pairs.captureInvite()
  void pairs.load()
})
async function create() {
  const id = await pairs.create()
  if (id && router.currentRoute.value.path === '/pairs') void router.push('/pairs/' + id)
}
async function join() {
  const id = await pairs.join()
  if (id && router.currentRoute.value.path === '/pairs') void router.push('/pairs/' + id)
}
</script>
<template>
  <SpaceShell>
    <div class="page-heading">
      <div>
        <p class="eyebrow">属于两个人的旅程</p>
        <h1>我的双人房间</h1>
        <p class="muted">选择一个空间，把另一半故事留给搭档。</p>
      </div>
      <button class="small-action" :disabled="pairs.loading || pairs.busy" @click="pairs.load">
        刷新列表
      </button>
    </div>
    <p v-if="pairs.error" class="error" role="alert">{{ pairs.error.message }}</p>
    <p v-if="pairs.notice" class="notice" role="status">{{ pairs.notice }}</p>
    <div class="room-actions">
      <section class="resource-panel">
        <h2>新建一个空间</h2>
        <p>你将成为角色 A。邀请一位搭档加入后，再一起选择故事。</p>
        <button data-test="create-pair" class="primary" :disabled="pairs.busy" @click="create">
          {{ pairs.busy ? '正在处理…' : '创建新房间' }}
        </button>
      </section>
      <section class="resource-panel">
        <h2>接受搭档邀请</h2>
        <p>{{ pairs.inviteHint }}</p>
        <p v-if="identity.currentRecoveryKeyPending" class="notice">
          请先回身份页确认密钥保存情况，再加入房间。
        </p>
        <button
          v-if="pairs.hasIncomingInvite"
          data-test="join-pair"
          class="primary"
          :disabled="pairs.busy || identity.currentRecoveryKeyPending"
          @click="join"
        >
          确认以当前身份加入 · 角色 B
        </button>
      </section>
    </div>
    <p v-if="pairs.loading" role="status">正在读取你的房间…</p>
    <section v-else aria-label="已加入房间">
      <h2>
        旅程空间 <span class="muted">{{ pairs.pairs.length }}</span>
      </h2>
      <p v-if="!pairs.pairs.length && !pairs.error" class="empty-state">
        还没有房间。创建一个空间，或重新打开搭档的原邀请链接。
      </p>
      <div class="room-grid">
        <article
          v-for="pair in pairs.pairs"
          :key="pair.id"
          class="resource-panel"
          data-test="pair-card"
        >
          <div class="seat-mark" aria-hidden="true">
            <span>A</span><span :class="{ occupied: pair.member_count === 2 }">B</span>
          </div>
          <h3>双人空间</h3>
          <p class="identifier">{{ pair.id }}</p>
          <p>你的角色 {{ pair.role.toUpperCase() }} · {{ pair.member_count }} / 2 人已加入</p>
          <p class="muted">{{ pair.member_count === 1 ? '等待搭档加入' : '双方已就位' }}</p>
          <RouterLink class="action-link" :to="'/pairs/' + pair.id">进入房间 →</RouterLink>
        </article>
      </div>
    </section>
  </SpaceShell>
</template>
