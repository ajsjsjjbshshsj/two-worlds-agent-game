<script setup lang="ts">
import { watch, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, RouterLink, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import SpaceShell from '../components/SpaceShell.vue'
import SceneRenderer from '../components/game/SceneRenderer.vue'
import ActionPanel from '../components/game/ActionPanel.vue'
import Device from '../components/game/Device.vue'
import { useGameStore } from '../stores/game'
import { useIdentityStore } from '../stores/identity'
const route = useRoute(),
  game = useGameStore(),
  identity = useIdentityStore()
watch(
  () => route.params.saveId,
  (id) => {
    void game.load(String(id))
  },
  { immediate: true },
)
const allowLeave = () =>
  (!game.pending && !game.busy) ||
  window.confirm('操作结果仍待确认。离开会丢失本页请求记录，建议先确认原请求。仍要离开吗？')
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate(allowLeave)
function warnUnload(event: BeforeUnloadEvent) {
  if (game.pending || game.busy) {
    event.preventDefault()
    event.returnValue = true
  }
}
onMounted(() => window.addEventListener('beforeunload', warnUnload))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnUnload)
  game.reset()
})
function focusDevice(id: string) {
  document.getElementById('device-' + id)?.focus()
}
</script>
<template>
  <SpaceShell
    ><p class="eyebrow">两个世界，彼此回响</p>
    <h1>我的世界</h1>
    <p v-if="game.loading" role="status">正在读取个人快照…</p>
    <p v-if="game.error" class="error" role="alert">{{ game.error }}</p>
    <button
      class="small-action"
      :disabled="game.busy || game.loading"
      @click="game.load(String(route.params.saveId))"
    >
      重新读取 / 获取搭档进度</button
    ><button v-if="game.pending" class="secondary" :disabled="game.busy" @click="game.retry">
      手动确认原请求（相同 UUID 与参数）</button
    ><template v-if="game.snapshot"
      ><section data-test="save-entry">
        <p>
          {{ game.snapshot.script_id }} · 角色 {{ game.snapshot.role.toUpperCase() }} ·
          {{ game.snapshot.scene_id }} · 内容 {{ game.snapshot.script_version }} · 进度
          {{ game.snapshot.version }}
        </p>
        <p class="notice">
          {{ game.snapshot.completed ? '已完成，共同结局已确认' : '仅在服务端确认后改变世界' }} ·
          T11.1 原型，音频与完整演出待后续。
        </p>
        <RouterLink class="action-link" :to="'/pairs/' + game.snapshot.pair_id + '/library'"
          >返回书架 →</RouterLink
        >
      </section>
      <SceneRenderer
        :snapshot="game.snapshot"
        :token="identity.token ?? undefined"
        @focus-device="focusDevice" />
      <div class="game-columns">
        <div>
          <section class="resource-panel">
            <h2>我的设备</h2>
            <Device
              v-for="(fields, id) in game.snapshot.personal.devices"
              :key="id"
              :id="String(id)"
              :fields="fields"
            />
            <h2>当前观察</h2>
            <p v-for="o in game.snapshot.personal.observations" :key="o.topic">{{ o.text }}</p>
          </section>
          <section class="resource-panel">
            <h2>我的私人线索</h2>
            <p v-if="!game.snapshot.personal.clues.length">尚未发现私人线索。</p>
            <p v-for="c in game.snapshot.personal.clues" :key="c.id">{{ c.text }}</p>
            <h2>已公开线索</h2>
            <p v-for="c in game.snapshot.public.clues" :key="c.id">{{ c.text }}</p>
            <h2>共同事件</h2>
            <p v-for="e in game.snapshot.public.events" :key="e.ordinal">{{ e.text }}</p>
            <h2 v-if="game.snapshot.completed">共同回顾</h2>
            <p>{{ game.snapshot.public.recap.summary }}</p>
            <p v-for="m in game.snapshot.public.recap.milestones" :key="m.ordinal">{{ m.text }}</p>
          </section>
        </div>
        <ActionPanel
          :actions="game.snapshot.available_actions"
          :disabled="game.busy || game.loading || !!game.pending"
          @command="game.submit"
        /></div></template
  ></SpaceShell>
</template>
