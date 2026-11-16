<script setup lang="ts">
import { computed, watch, onBeforeUnmount } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import SpaceShell from '../components/SpaceShell.vue'
import { usePairsStore } from '../stores/pairs'
import { useLibraryStore } from '../stores/library'
const pairs = usePairsStore(),
  library = useLibraryStore(),
  route = useRoute(),
  router = useRouter()
const pairId = computed(() => String(route.params.pairId)),
  pair = computed(() => pairs.pairs.find((p) => p.id === pairId.value))
const difficulties = { easy: '轻松', medium: '适中', hard: '挑战' }
watch(
  pairId,
  async (id) => {
    await Promise.all([pairs.load(), library.load(id)])
  },
  { immediate: true },
)
onBeforeUnmount(() => library.reset())
async function open(id: string) {
  const saveId = await library.open(id)
  if (saveId) void router.push('/saves/' + saveId)
}
</script>
<template>
  <SpaceShell>
    <RouterLink class="back-link" :to="'/pairs/' + pairId">← 当前房间</RouterLink>
    <div class="page-heading">
      <div>
        <p class="eyebrow">今晚，选一个世界</p>
        <h1>你们的剧本书架</h1>
        <p class="identifier">{{ pairId }}</p>
        <p class="muted">每段故事独立保存。回来时，继续原来的进度与内容版本。</p>
      </div>
      <button
        class="small-action"
        :disabled="library.loading || library.busy"
        @click="library.load(pairId)"
      >
        刷新书架
      </button>
    </div>
    <p v-if="library.error || pairs.error" class="error" role="alert">
      {{ library.error?.message || pairs.error?.message }}
    </p>
    <p v-if="library.loading || pairs.loading" role="status">正在读取已发布故事与本房间进度…</p>
    <template v-else-if="!library.error && !pairs.error"
      ><p v-if="!library.cards.length" class="empty-state" data-test="empty-catalog">
        暂时没有已发布剧本。内容准备与审核完成后，会出现在这里。你的房间仍已保留。
      </p>
      <div class="script-grid">
        <article
          v-for="card in library.cards"
          :key="card.script.id + '@' + card.script.content_version"
          class="script-card"
          data-test="script-card"
        >
          <div class="cover-placeholder" aria-label="暂无封面">
            <span>TwoWorlds</span><span>故事封面准备中</span>
          </div>
          <div class="script-copy">
            <p class="eyebrow">
              {{ card.script.estimated_minutes }} 分钟 · {{ difficulties[card.script.difficulty] }}
            </p>
            <h2>{{ card.script.title }}</h2>
            <p>{{ card.script.summary }}</p>
            <p v-if="pair" class="role-intro">
              你的角色 · {{ card.script.roles.find((r) => r.id === pair?.role)?.name }}<br /><span
                class="muted"
                >{{ card.script.roles.find((r) => r.id === pair?.role)?.description }}</span
              >
            </p>
            <div class="progress-strip">
              <strong>{{
                !card.save ? '尚未开始' : card.save.completed ? '已完成' : '进行中'
              }}</strong
              ><template v-if="card.save"
                ><span>场景 {{ card.save.scene_id }} · 进度版本 {{ card.save.version }}</span
                ><span>绑定内容 {{ card.save.script_version }}</span
                ><span>最后更新 {{ card.save.updated_at }}</span
                ><span
                  v-if="card.save.script_version !== card.script.content_version"
                  class="notice"
                  >目录介绍来自 {{ card.script.content_version }}；继续时仍读取旧版
                  {{ card.save.script_version }}。</span
                ></template
              ><span v-else>内容版本 {{ card.script.content_version }}</span>
            </div>
            <button
              v-if="card.save"
              data-test="continue-save"
              class="primary"
              :disabled="library.busy"
              @click="open(card.script.id)"
            >
              {{ card.save.completed ? '查看完成存档' : '继续原存档' }}</button
            ><button
              v-else
              data-test="start-save"
              class="primary"
              :disabled="library.busy || pair?.member_count !== 2"
              @click="open(card.script.id)"
            >
              {{ pair?.member_count === 2 ? '开始这段故事' : '等待搭档加入后开始' }}
            </button>
          </div>
        </article>
      </div>
      <!-- An existing save remains reachable even if its story leaves the public catalog. -->
      <section
        v-if="library.saves.some((s) => !library.scripts.some((m) => m.id === s.script_id))"
        class="resource-panel"
      >
        <h2>目录之外的既有存档</h2>
        <p>继续按原版本读取；如果原版本不可用，服务端会明确报错。</p>
        <div
          v-for="save in library.saves.filter(
            (s) => !library.scripts.some((m) => m.id === s.script_id),
          )"
          :key="save.id"
        >
          <p>
            {{ save.script_id }} · {{ save.script_version }} ·
            {{ save.completed ? '已完成' : '进行中' }}
          </p>
          <button class="secondary" :disabled="library.busy" @click="open(save.script_id)">
            读取原存档
          </button>
        </div>
      </section>
    </template>
  </SpaceShell>
</template>
