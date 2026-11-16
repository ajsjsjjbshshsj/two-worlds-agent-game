<script setup lang="ts">
import { watch, onBeforeUnmount } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import SpaceShell from '../components/SpaceShell.vue'
import { useLibraryStore } from '../stores/library'
const library = useLibraryStore(),
  route = useRoute()
watch(
  () => route.params.saveId,
  (id) => {
    void library.read(String(id))
  },
  { immediate: true },
)
onBeforeUnmount(() => library.reset())
</script>
<template>
  <SpaceShell>
    <p class="eyebrow">继续同一个世界</p>
    <h1>我的存档入口</h1>
    <p v-if="library.loading" role="status">正在读取你的角色进度…</p>
    <template v-else-if="library.error"
      ><p role="alert" class="error">{{ library.error.message }}</p>
      <button class="secondary" @click="library.read(String(route.params.saveId))">
        重新读取
      </button></template
    >
    <section v-else-if="library.entry" class="resource-panel" data-test="save-entry">
      <h2>{{ library.entry.completed ? '这段故事已完成' : '旅程已保存' }}</h2>
      <p class="identifier">{{ library.entry.id }}</p>
      <dl class="entry-details">
        <dt>剧本</dt>
        <dd>{{ library.entry.script_id }}</dd>
        <dt>绑定内容</dt>
        <dd>{{ library.entry.script_version }}</dd>
        <dt>我的角色</dt>
        <dd>{{ library.entry.role.toUpperCase() }}</dd>
        <dt>当前场景</dt>
        <dd>{{ library.entry.scene_id }}</dd>
        <dt>进度版本</dt>
        <dd>{{ library.entry.version }}</dd>
      </dl>
      <p class="notice">
        已读取当前身份的个人投影。完整游戏交互界面将在 T11 接入；此处仅展示存档信息与进度。
      </p>
      <RouterLink class="action-link" :to="'/pairs/' + library.entry.pair_id + '/library'"
        >回到这个房间的书架 →</RouterLink
      >
    </section>
  </SpaceShell>
</template>
