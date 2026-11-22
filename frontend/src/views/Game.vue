<script setup lang="ts">
import { watch, inject, ref, onBeforeUnmount, onMounted, type Ref } from 'vue'
import { useRoute, RouterLink, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import SpaceShell from '../components/SpaceShell.vue'
import SceneRenderer from '../components/game/SceneRenderer.vue'
import AudioControls from '../components/game/AudioControls.vue'
import ActionPanel from '../components/game/ActionPanel.vue'
import Device from '../components/game/Device.vue'
import { useGameStore } from '../stores/game'
import { useIdentityStore } from '../stores/identity'
const route = useRoute(),
  game = useGameStore(),
  identity = useIdentityStore()
const offline = inject<Ref<boolean>>('twoworlds-offline', ref(navigator.onLine === false))
const syncLabels = {
  idle: '',
  connecting: '正在同步最新进度…',
  live: '',
  http: '实时连接正在恢复，当前进度由 HTTP 更新。',
  offline: '实时连接已中断，正在等待重新同步。',
  paused: '页面在后台，已暂停同步。',
  blocked: '当前会话无法同步此存档。',
}
watch(
  () => route.params.saveId,
  (id) => {
    if (typeof id === 'string') void game.open(id)
  },
  { immediate: true },
)
const allowLeave = () =>
  !!game.persisted ||
  (!game.pending && !game.busy) ||
  window.confirm('操作结果仍待确认。离开会丢失本页请求记录，建议先确认原请求。仍要离开吗？')
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate(allowLeave)
function warnUnload(event: BeforeUnloadEvent) {
  if (!game.persisted && (game.pending || game.busy)) {
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
  const target = document.getElementById('device-' + id)
  target?.focus()
  target?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
}
function resubmitOriginal() {
  if (
    window.confirm(
      '尚未查到回执。重新提交会沿用原 UUID 和参数，原操作未执行时可能执行一次。继续吗？',
    )
  )
    void game.resubmit()
}
function discardOriginal() {
  if (window.confirm('只清除本机核对记录，服务器可能已执行原操作。确定停止核对吗？'))
    game.discardPending()
}
</script>
<template>
  <SpaceShell
    ><p class="eyebrow">两个世界，彼此回响</p>
    <h1>我的世界</h1>
    <nav v-if="game.snapshot" class="game-jumps" aria-label="游戏分区">
      <a href="#game-scene">场景</a><a href="#game-status">进度与回执</a>
      <a v-if="!game.snapshot.completed" href="#game-actions">行动</a>
      <a href="#game-information">设备与线索</a><a href="#game-audio">声音与字幕</a>
    </nav>
    <section id="game-status" tabindex="-1" aria-label="同步与待确认操作">
      <p v-if="game.loading" role="status">正在读取个人快照…</p>
      <p v-if="syncLabels[game.realtime]" role="status">{{ syncLabels[game.realtime] }}</p>
      <p v-if="game.error" class="error" role="alert">{{ game.error }}</p>
      <p v-if="game.pendingNotice" role="status">{{ game.pendingNotice }}</p>
      <button
        class="small-action"
        v-if="game.realtime !== 'blocked'"
        :disabled="offline || game.busy || game.loading"
        @click="game.open(String(route.params.saveId))"
      >
        重新读取 / 获取搭档进度</button
      ><button
        v-if="game.pending"
        class="secondary"
        :disabled="
          offline ||
          game.busy ||
          game.pendingState === 'checking' ||
          (!game.recovered && !game.canAct)
        "
        @click="game.retry"
      >
        {{ game.recovered ? '查询原操作回执' : '手动确认原请求（相同 UUID 与参数）' }}</button
      ><button
        v-if="game.canResubmit"
        class="secondary"
        :disabled="offline || game.busy || !game.canAct"
        @click="resubmitOriginal"
      >
        使用原 UUID 重新提交 {{ game.pending?.kind }}</button
      ><button
        v-if="game.pending && game.persisted"
        class="secondary"
        :disabled="game.busy || game.pendingState === 'checking'"
        @click="discardOriginal"
      >
        清除本机待确认记录
      </button>
    </section>
    <template v-if="game.snapshot"
      ><section data-test="save-entry">
        <p>
          {{ game.snapshot.script_id }} · 角色 {{ game.snapshot.role.toUpperCase() }} ·
          {{ game.snapshot.scene_id }} · 内容 {{ game.snapshot.script_version }} · 进度
          {{ game.snapshot.version }}
        </p>
        <p class="notice">
          {{ game.snapshot.completed ? '已完成，共同结局已确认' : '仅在服务端确认后改变世界' }} ·
          T11.2 原型 · 支持音频与字幕，正式素材与完整演出待后续。
        </p>
        <RouterLink class="action-link" :to="'/pairs/' + game.snapshot.pair_id + '/library'"
          >返回书架 →</RouterLink
        >
      </section>
      <SceneRenderer
        id="game-scene"
        tabindex="-1"
        :snapshot="game.snapshot"
        :session-generation="identity.sessionGeneration"
        @session-expired="identity.expireSession"
        @focus-device="focusDevice"
      />
      <div class="game-columns">
        <ActionPanel
          id="game-actions"
          tabindex="-1"
          v-if="!game.snapshot.completed"
          :actions="game.snapshot.available_actions"
          :disabled="offline || !game.canAct || game.busy || game.loading || !!game.pending"
          @command="game.submit"
        />
        <div id="game-information" tabindex="-1" class="game-information">
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
      </div>
      <AudioControls
        id="game-audio"
        tabindex="-1"
        :snapshot="game.snapshot"
        :session-generation="identity.sessionGeneration"
        @session-expired="identity.expireSession"
      /> </template
  ></SpaceShell>
</template>
